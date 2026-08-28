# -*- coding: utf-8 -*-
"""Giao dien dong lenh cua migrate-mail."""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import sys
from contextlib import contextmanager
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__, report, verify
from .config import Config, load_config
from .discover import (NOSELECT, SPECIAL_DRAFTS, SPECIAL_JUNK, SPECIAL_SENT,
                       SPECIAL_TRASH, DiscoveryError, Plan, build_plan,
                       check_login, list_folders, open_connection)
from .runner import (GMAIL_DAILY_LIMIT, MODE_DRY, MODE_FOLDERS,
                     MODE_SIZES, MODE_SYNC, Result, flags_used, imapsync_available,
                     imapsync_run, run_user, unsupported_flags, user_statedir)
from .users import User, filter_users, load_users

_print_lock = threading.Lock()

# Noi nhan output. Mac dinh la stdout; giao dien web tam thoi doi huong ve no
# de hien tien do truc tiep, khong phai viet lai logic cua tung lenh.
# Dung bien toan cuc (khong phai thread-local) vi cac lenh chay song song bang
# thread pool -- thread con se khong thay thread-local cua thread cha.
# An toan vi web chi cho chay mot job tai mot thoi diem.
_sink = None


def say(msg: str = "") -> None:
    sink = _sink
    if sink is not None:
        sink(msg)
        return
    with _print_lock:
        print(msg, flush=True)


@contextmanager
def capture(fn):
    """Doi huong moi say() trong khoi nay sang fn."""
    global _sink
    previous = _sink
    _sink = fn
    try:
        yield
    finally:
        _sink = previous


def _now() -> str:
    return time.strftime("%H:%M:%S")


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #

def cmd_doctor(args, cfg: Config) -> int:
    problems = 0

    say("migrate-mail %s | Python %s" % (__version__, sys.version.split()[0]))
    say("config      : %s" % cfg.path)
    say("nguon       : %s:%d (ssl=%s)" % (cfg.source.host, cfg.source.port, cfg.source.ssl))
    say("dich        : %s:%d (ssl=%s)" % (cfg.dest.host, cfg.dest.port, cfg.dest.ssl))
    say("")

    path = imapsync_available(cfg)
    if not path:
        say("[LOI ] khong tim thay imapsync (%s). Chay ./install.sh" % cfg.paths.imapsync)
        problems += 1
    else:
        say("[ OK ] imapsync: %s" % path)
        version = imapsync_run(cfg, "--version").strip().splitlines()
        if version:
            say("       version: %s" % version[0])
        else:
            say("[CANH] khong chay duoc 'imapsync --version' -- thuong la thieu module Perl")
            problems += 1

        missing = unsupported_flags(cfg, flags_used(cfg))
        if missing:
            say("[LOI ] ban imapsync nay khong chap nhan cac flag sau:")
            say("       %s" % " ".join(missing))
            say("       imapsync se dung ngay khi gap tuy chon la, nen phai sua")
            say("       truoc khi chay that.")
            problems += 1
        else:
            say("[ OK ] ban imapsync nay chap nhan moi flag tool dung")

    try:
        users = load_users(args.users)
        say("[ OK ] users.csv: %d mailbox" % len(users))
    except Exception as exc:
        say("[LOI ] users.csv: %s" % exc)
        problems += 1

    for label, d in (("logdir", cfg.paths.logdir), ("statedir", cfg.paths.statedir)):
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            probe = Path(d) / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            say("[ OK ] %s ghi duoc: %s" % (label, d))
        except Exception as exc:
            say("[LOI ] khong ghi duoc %s (%s): %s" % (label, d, exc))
            problems += 1

    say("")
    say("Ket luan: %s" % ("san sang" if problems == 0 else "%d van de can xu ly" % problems))
    return 0 if problems == 0 else 1


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #

def cmd_preflight(args, cfg: Config) -> int:
    users = filter_users(load_users(args.users), args.only)
    say("Kiem tra dang nhap %d mailbox (ca hai dau)...\n" % len(users))

    def probe(user: User) -> Tuple[User, Tuple[bool, str], Tuple[bool, str]]:
        src = check_login(cfg, user, "source")
        dst = check_login(cfg, user, "dest")
        return user, src, dst

    results = []
    with futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(users)))) as pool:
        for user, src, dst in pool.map(probe, users):
            results.append((user, src, dst))
            flag = "OK  " if (src[0] and dst[0]) else "LOI "
            say("%s %-32s nguon=%s  dich=%s"
                % (flag, user.src_user,
                   "OK" if src[0] else "FAIL", "OK" if dst[0] else "FAIL"))
            if not src[0]:
                say("       nguon: %s" % src[1])
            if not dst[0]:
                say("       dich : %s" % dst[1])

    bad = [r for r in results if not (r[1][0] and r[2][0])]
    say("")
    say("Ket qua: %d/%d mailbox dang nhap duoc ca hai dau." % (len(results) - len(bad), len(results)))
    if bad:
        say("")
        say("Goi y xu ly loi hay gap:")
        say("  - Gmail bao 'Invalid credentials': mat khau dang dung la mat khau")
        say("    thuong chu khong phai App Password, hoac account chua bat 2FA.")
        say("  - Gmail bao 'Application-specific password required': dung App Password.")
        say("  - IceWarp bao 'Authentication failed': kiem tra dung dia chi day du")
        say("    user@domain va tai khoan da duoc tao chua.")
    return 0 if not bad else 1


# --------------------------------------------------------------------------- #
# discover
# --------------------------------------------------------------------------- #

def _discover_one(cfg: Config, user: User) -> Tuple[User, Optional[Plan], str]:
    try:
        folders = list_folders(cfg, user)
        return user, build_plan(folders, cfg.sync), ""
    except DiscoveryError as exc:
        return user, None, str(exc)
    except Exception as exc:                                # pragma: no cover
        return user, None, "%s: %s" % (type(exc).__name__, exc)


def _print_plan(user: User, plan: Plan) -> None:
    say("")
    say("=== %s (%d folder) ===" % (user.src_user, len(plan.folders)))
    if plan.excluded:
        say("  BO QUA:")
        for f, reason in plan.excluded:
            say("    - %-40s %s" % (f.display, reason))
    if plan.mapped:
        say("  DOI TEN:")
        for f, dest in plan.mapped:
            say("    - %-40s -> %s" % (f.display, dest))
    if plan.kept:
        say("  GIU NGUYEN:")
        for f in plan.kept:
            say("    - %s" % f.display)
    _print_unmappable(plan)
    _print_collisions(plan)


def _print_unmappable(plan: Plan) -> None:
    if not plan.unmappable:
        return
    say("")
    say("  !! KHONG DOI TEN DUOC !!")
    say("  Ten folder co chua dau '=' ma imapsync dung dau do lam dau phan cach")
    say("  cho --f1f2, nen khong dien ta duoc. Cac folder sau se GIU NGUYEN ten:")
    for folder, wanted in plan.unmappable:
        say("    %s  (le ra -> %s)" % (folder.display, wanted))
    say("  Cach xu ly: doi ten label do ben Gmail cho het dau '=', roi chay lai.")


def _print_collisions(plan: Plan) -> None:
    collisions = plan.collisions()
    if not collisions:
        return
    say("")
    say("  !! TRUNG TEN FOLDER DICH !!")
    say("  Nhieu folder Gmail se do chung vao mot folder ben IceWarp:")
    for dest, sources in collisions:
        say("    %s  <-  %s" % (dest, ", ".join(f.display for f in sources)))
    say("")
    say("  Thuong gap khi hop thu Gmail truoc day da import tu Outlook: ben canh")
    say("  folder chuan cua Gmail con sot lai label cu cung cong dung.")
    say("  Neu muon giu rieng, doi ten label cu bang extra_args trong config.ini:")
    for dest, _sources in collisions:
        say("    extra_args = --regextrans2 s,^%s$,%s-cu," % (dest, dest))
    say("  Neu tron chung la y muon thi cu chay tiep, khong mat mail.")


def _print_dest_folders(cfg: Config, user: User) -> int:
    """Liet ke folder co san ben IceWarp va canh bao neu ten map khong khop.

    Can buoc nay vi neu IceWarp goi folder rac la 'Junk E-mail' ma ta lai map
    sang 'Spam', imapsync se tao them mot folder 'Spam' moi -- ket qua la hop
    thu co hai folder rac song song, va bo loc cua IceWarp van dung folder cu.
    """
    say("")
    say("=== %s (ben IceWarp) ===" % user.dst_user)
    try:
        folders = list_folders(cfg, user, side="dest")
    except DiscoveryError as exc:
        say("  LOI: %s" % exc)
        return 1

    existing = {f.display for f in folders}
    for f in sorted(folders, key=lambda x: x.display.lower()):
        marks = []
        if f.has(NOSELECT):
            marks.append("khong chua mail")
        for flag, label in ((SPECIAL_SENT, "Sent"), (SPECIAL_DRAFTS, "Drafts"),
                            (SPECIAL_TRASH, "Trash"), (SPECIAL_JUNK, "Junk")):
            if f.has(flag):
                marks.append("special-use: %s" % label)
        say("    - %-38s %s" % (f.display, "  ".join(marks)))

    wanted = {
        "sent_folder": cfg.sync.sent_folder,
        "drafts_folder": cfg.sync.drafts_folder,
        "trash_folder": cfg.sync.trash_folder,
        "junk_folder": cfg.sync.junk_folder,
    }
    missing = {k: v for k, v in wanted.items() if v not in existing}
    if missing:
        say("")
        say("  CANH BAO: cac ten sau trong config.ini chua co ben IceWarp,")
        say("  imapsync se TAO MOI folder trung ten:")
        for key, value in missing.items():
            say("    %-14s = %s" % (key, value))
        say("  Neu IceWarp da co folder cung cong dung nhung khac ten, hay sua")
        say("  config.ini cho khop de mail khong bi tach ra hai noi.")
    return 0


def cmd_discover(args, cfg: Config) -> int:
    users = filter_users(load_users(args.users), args.only)

    if args.dest:
        say("Liet ke folder cua %d mailbox tren %s..." % (len(users), cfg.dest.host))
        failed = sum(_print_dest_folders(cfg, u) for u in users)
        say("")
        say("Xong. %d/%d mailbox doc duoc." % (len(users) - failed, len(users)))
        return 0 if failed == 0 else 1

    say("Do folder cua %d mailbox tren %s...\n" % (len(users), cfg.source.host))
    failed = 0
    with futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(users)))) as pool:
        jobs = [pool.submit(_discover_one, cfg, u) for u in users]
        for job in jobs:
            user, plan, err = job.result()
            if plan is None:
                failed += 1
                say("")
                say("=== %s ===" % user.src_user)
                say("  LOI: %s" % err)
                continue
            _print_plan(user, plan)
    say("")
    say("Xong. %d/%d mailbox do duoc." % (len(users) - failed, len(users)))
    return 0 if failed == 0 else 1


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #

def _done_marker(cfg: Config, user: User) -> Path:
    return user_statedir(cfg, user) / "done.marker"


def cmd_sync(args, cfg: Config) -> int:
    users = filter_users(load_users(args.users), args.only)
    if args.sizes:
        mode = MODE_SIZES
    elif args.folders_only:
        mode = MODE_FOLDERS
    elif args.dry:
        mode = MODE_DRY
    else:
        mode = MODE_SYNC

    if args.resume:
        remaining = [u for u in users if not _done_marker(cfg, u).exists()]
        skipped = len(users) - len(remaining)
        if skipped:
            say("--resume: bo qua %d mailbox da chay xong truoc do." % skipped)
        users = remaining
        if not users:
            say("Khong con mailbox nao can chay.")
            return 0

    workers = args.workers or cfg.sync.workers
    workers = max(1, min(workers, len(users)))

    say("Che do  : %s%s" % (mode, " (--since-days %d)" % args.since_days if args.since_days else ""))
    say("Mailbox : %d | song song: %d" % (len(users), workers))
    say("Log     : %s" % cfg.paths.logdir)
    if mode == MODE_DRY:
        say("Day la chay thu, khong mail nao duoc ghi vao IceWarp.")
    elif mode == MODE_FOLDERS:
        say("Chi tao cay folder ben IceWarp, khong chuyen mail nao.")
    elif mode == MODE_SIZES:
        say("Chi dem dung luong ben Gmail, khong chuyen mail nao.")
    say("")

    # Buoc 1: do folder. Neu khong do duoc thi KHONG chay mailbox do -- chay mu
    # se rat de keo ca [Gmail]/All Mail sang, lam phinh gap doi/gap ba dung luong.
    say("[1/2] Do folder Gmail...")
    plans: Dict[str, Plan] = {}
    predelivered: List[Result] = []
    with futures.ThreadPoolExecutor(max_workers=min(8, len(users))) as pool:
        for user, plan, err in pool.map(lambda u: _discover_one(cfg, u), users):
            if plan is None:
                say("  LOI  %-32s %s" % (user.src_user, err))
                r = Result(user=user, mode=mode, started=time.time())
                r.finished = time.time()
                r.error = "khong do duoc folder: %s" % err
                predelivered.append(r)
            else:
                plans[user.src_user] = plan
                say("  OK   %-32s %d folder chuyen, %d bo qua"
                    % (user.src_user, len(plan.mapped) + len(plan.kept), len(plan.excluded)))
                for folder, wanted in plan.unmappable:
                    say("       CANH BAO: '%s' khong doi ten duoc thanh '%s' "
                        "(ten chua dau '=')" % (folder.display, wanted))
                for dest, sources in plan.collisions():
                    say("       CANH BAO: %d folder do chung vao '%s': %s"
                        % (len(sources), dest, ", ".join(f.display for f in sources)))
                    say("       Xem './mm.py discover' de biet cach tach rieng.")

    todo = [u for u in users if u.src_user in plans]
    if not todo:
        say("")
        say("Khong mailbox nao do duoc folder. Chay 'preflight' de kiem tra dang nhap.")
        return 1

    say("")
    say("[2/2] Chay imapsync...")
    results: List[Result] = list(predelivered)
    counter = {"done": 0}

    def work(user: User) -> Result:
        say("  %s bat dau  %s" % (_now(), user.src_user))
        r = run_user(cfg, user, plans[user.src_user], mode, since_days=args.since_days)
        with _print_lock:
            counter["done"] += 1
            n = counter["done"]
        status = "OK " if r.ok else "LOI"
        detail = ("%s mail, %s, %s" % (r.get("messages_transferred"),
                                       report.human_bytes(r.get("bytes_transferred")),
                                       report.human_duration(r.duration))
                  if r.ok else (r.error or r.exit_label or "exit %d" % r.exit_code))
        say("  %s %s [%d/%d] %-30s %s" % (_now(), status, n, len(todo), user.src_user, detail))
        if r.ok and mode == MODE_SYNC:
            try:
                _done_marker(cfg, user).write_text(time.strftime("%Y-%m-%d %H:%M:%S"),
                                                   encoding="utf-8")
            except OSError:
                pass
        return r

    try:
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for r in pool.map(work, todo):
                results.append(r)
    except KeyboardInterrupt:
        say("")
        say("Da dung. Cac mailbox dang chay bi cat giua chung; chay lai lenh nay")
        say("de tiep tuc -- imapsync bo qua mail da co san nen khong nhan doi.")
        return 130

    rows = report.rows_from_results(results)
    say("")
    if mode == MODE_SIZES:
        _print_sizes(results)
    else:
        report.print_table(rows, emit=say)
        report.print_summary(rows, emit=say)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = Path(cfg.paths.logdir)
    csv_path = report.write_csv(rows, outdir / ("report-%s.csv" % stamp))
    html_path = report.write_html(rows, outdir / ("report-%s.html" % stamp))
    json_path = report.save_run(rows, Path(cfg.paths.statedir) / "runs" / ("%s.json" % stamp))
    say("")
    say("Bao cao: %s" % csv_path)
    say("         %s" % html_path)
    say("         %s" % json_path)

    return 0 if all(r.ok for r in results) else 1


def _print_sizes(results: List[Result]) -> None:
    """Bao cao dung luong, kem tran tren so ngay theo gioi han Gmail cong bo.

    Cot "Ngay toi da" la kich ban XAU NHAT, khong phai du bao. Do thuc te cho
    thay co account Workspace tai lien mach vuot xa 2500 MB ma khong bi chan,
    nen thuong xong som hon nhieu. Xem ghi chu in kem ben duoi bang.
    """
    header = "%-34s %10s %12s %10s %10s" % ("Mailbox", "Mail", "Dung luong",
                                            "Mail lon nhat", "Ngay toi da")
    say(header)
    say("-" * len(header))
    total_bytes = total_msgs = 0
    max_days = 0
    for r in results:
        if not r.ok:
            say("%-34s  %s" % (r.user.src_user, r.error or r.exit_label or "loi"))
            continue
        size = r.get("source_bytes")
        msgs = r.get("source_messages")
        days = _days_needed(size)
        total_bytes += size
        total_msgs += msgs
        max_days = max(max_days, days)
        say("%-34s %10s %12s %10s %10s"
            % (r.user.src_user, "{:,}".format(msgs).replace(",", "."),
               report.human_bytes(size), report.human_bytes(r.get("source_biggest")),
               days))
    say("")
    say("Tong: %s mail, %s."
        % ("{:,}".format(total_msgs).replace(",", "."), report.human_bytes(total_bytes)))
    say("")
    # Google cong bo con so nay la "2500 MB", viet y nguyen de doi chieu duoc
    # voi tai lieu cua ho thay vi quy ra GiB.
    say("Cot 'Ngay toi da' tinh theo gioi han Google cong bo: 2500 MB tai ve")
    say("moi ngay cho MOI account. Gioi han tinh rieng tung account nen chay")
    say("nhieu mailbox song song KHONG bi cong don.")
    say("")
    say("Day la TRAN TREN, khong phai du bao. Thuc te da gap account Workspace")
    say("tai lien mach vuot xa muc do ma khong bi chan, xong som hon nhieu.")
    say("Muon biet con bao lau that su thi xem toc do trong log luc dang chay:")
    say("  tail -1 logs/<mailbox>.sync.*.log")
    say("dong do co san so mail/s va tong da chep.")
    if max_days > 1:
        say("")
        say("Neu dung phai gioi han, hop thu lon nhat can toi da %d ngay." % max_days)
        say("Moi ngay chay lai dung lenh sync: mail da chuyen khong bi chep lai,")
        say("no chi lam tiep phan con thieu.")


def _days_needed(size_bytes: int) -> int:
    if size_bytes <= 0:
        return 0
    return -(-size_bytes // GMAIL_DAILY_LIMIT)      # lam tron len


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #

def _verify_one(cfg: Config, user: User, cap: int) -> verify.UserCheck:
    check = verify.UserCheck(src_user=user.src_user, dst_user=user.dst_user)
    src_conn = dst_conn = None
    try:
        folders = list_folders(cfg, user)
        plan = build_plan(folders, cfg.sync)
        src_conn = open_connection(cfg, user, "source")
        dst_conn = open_connection(cfg, user, "dest")

        pairs = [(f, dest) for f, dest in plan.mapped] + [(f, f.raw) for f in plan.kept]
        for folder, dest_name in pairs:
            fc = verify.FolderCheck(source_folder=folder.display, dest_folder=dest_name)
            try:
                src_index, fc.source_total = verify.fetch_index(src_conn, folder.raw, cap)
                dst_index, fc.dest_total = verify.fetch_index(dst_conn, dest_name, cap)
            except Exception as exc:
                fc.error = str(exc)
                check.folders.append(fc)
                continue
            fc.compared, fc.matched, fc.mismatched, fc.samples = verify.compare_indexes(
                src_index, dst_index)
            fc.missing_on_dest = max(0, len(src_index) - fc.compared)
            check.folders.append(fc)
    except DiscoveryError as exc:
        check.error = str(exc)
    except Exception as exc:                                # pragma: no cover
        check.error = "%s: %s" % (type(exc).__name__, exc)
    finally:
        for conn in (src_conn, dst_conn):
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
    return check


def _fmt_epoch(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))


def cmd_verify(args, cfg: Config) -> int:
    users = filter_users(load_users(args.users), args.only)
    cap = args.sample
    say("Doi chieu ngay thang cua mail giua hai dau.")
    say("Lay mau toi da %d mail moi folder. Sai lech duoi %ds coi nhu khop.\n"
        % (cap, verify.TOLERANCE_SECONDS))

    checks: List[verify.UserCheck] = []
    with futures.ThreadPoolExecutor(max_workers=min(4, max(1, len(users)))) as pool:
        for check in pool.map(lambda u: _verify_one(cfg, u, cap), users):
            checks.append(check)
            if check.error:
                say("LOI  %-32s %s" % (check.src_user, check.error))
                continue
            flag = "OK  " if check.ok else "LECH"
            say("%s %-32s doi chieu %d mail, lech %d, thieu ben dich %d"
                % (flag, check.src_user, check.compared, check.mismatched, check.missing))
            for fc in check.folders:
                if fc.error:
                    say("       %-28s loi: %s" % (fc.source_folder, fc.error))
                elif fc.mismatched:
                    say("       %-28s %d/%d lech ngay"
                        % (fc.source_folder, fc.mismatched, fc.compared))
                    for msgid, src_e, dst_e in fc.samples:
                        say("         %s" % msgid[:60])
                        say("           Gmail  : %s" % _fmt_epoch(src_e))
                        say("           IceWarp: %s" % _fmt_epoch(dst_e))

    total_cmp = sum(c.compared for c in checks)
    total_bad = sum(c.mismatched for c in checks)
    failed = [c for c in checks if not c.ok]

    say("")
    if total_cmp == 0:
        say("Khong doi chieu duoc mail nao. Da chay sync chua? Folder ben dich co ton tai khong?")
        return 1
    say("Ket qua: %d mail doi chieu, %d lech ngay (%.2f%%)."
        % (total_cmp, total_bad, 100.0 * total_bad / total_cmp))
    if total_bad:
        say("")
        say("Ngay KHONG duoc giu nguyen. Kiem tra theo thu tu nay:")
        say("  1. Xem log sync co dong 'Info: turned ON syncinternaldates' khong.")
        say("  2. Neu co ma van lech, IceWarp dang bo qua ngay trong lenh APPEND.")
        say("     Doi date_source = header trong config.ini roi sync lai mailbox do")
        say("     bang: ./mm.py sync --only <dia chi>")
        say("  3. Neu van lech, hoi nha cung cap IceWarp ve viec server ghi de")
        say("     INTERNALDATE luc APPEND.")
    elif failed:
        say("Ngay khop het, nhung co folder khong doi chieu duoc (xem o tren).")
    else:
        say("Ngay thang duoc giu nguyen tren toan bo mau kiem tra.")
    return 0 if not failed else 1


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def cmd_report(args, cfg: Config) -> int:
    runs_dir = Path(cfg.paths.statedir) / "runs"
    runs = sorted(runs_dir.glob("*.json")) if runs_dir.exists() else []
    if not runs:
        say("Chua co lan chay nao duoc luu trong %s" % runs_dir)
        return 1
    if args.list:
        say("Cac lan chay da luu:")
        for r in runs:
            say("  %s" % r.name)
        return 0

    target = runs_dir / args.run if args.run else runs[-1]
    if not target.exists():
        say("Khong thay %s" % target)
        return 1
    rows = report.refresh_hints(report.load_run(target))
    say("Lan chay: %s\n" % target.name)
    report.print_table(rows, emit=say)
    report.print_summary(rows, emit=say)
    if args.out:
        out = Path(args.out)
        if out.suffix.lower() == ".html":
            say("\nDa ghi %s" % report.write_html(rows, out))
        else:
            say("\nDa ghi %s" % report.write_csv(rows, out))
    return 0


# --------------------------------------------------------------------------- #
# web
# --------------------------------------------------------------------------- #

def cmd_web(args, cfg: Config) -> int:
    from .web import serve
    serve(cfg, Path(args.users), host=args.host, port=args.port)
    return 0


# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mm",
        description="Migrate mail Google/Gmail -> IceWarp bang imapsync.",
    )
    p.add_argument("--config", default="config.ini", help="mac dinh: config.ini")
    p.add_argument("--users", default="users.csv", help="mac dinh: users.csv")
    p.add_argument("--version", action="version", version="migrate-mail " + __version__)
    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("doctor", help="kiem tra moi truong truoc khi lam gi khac")
    d.set_defaults(func=cmd_doctor)

    pf = sub.add_parser("preflight", help="thu dang nhap ca hai dau cho tung mailbox")
    pf.add_argument("--only", default="", help="chi chay vai dia chi, cach nhau bang dau phay")
    pf.set_defaults(func=cmd_preflight)

    dc = sub.add_parser("discover", help="xem folder Gmail va ke hoach chuyen doi")
    dc.add_argument("--only", default="")
    dc.add_argument("--dest", action="store_true",
                    help="liet ke folder co san ben IceWarp thay vi ben Gmail")
    dc.set_defaults(func=cmd_discover)

    s = sub.add_parser("sync", help="chay migration")
    s.add_argument("--only", default="")
    s.add_argument("--dry", action="store_true", help="chay thu, khong ghi gi vao IceWarp")
    s.add_argument("--sizes", action="store_true",
                   help="chi dem dung luong ben Gmail va uoc luong so ngay can chay")
    s.add_argument("--folders-only", action="store_true",
                   help="chi tao cay folder ben IceWarp, khong chuyen mail; "
                        "chay truoc --dry de lan chay khan cho so lieu day du")
    s.add_argument("--workers", type=int, default=0, help="ghi de [sync] workers")
    s.add_argument("--since-days", type=int, default=0,
                   help="chi chuyen mail moi hon N ngay (dung cho vong delta luc cutover)")
    s.add_argument("--resume", action="store_true",
                   help="bo qua mailbox da chay xong thanh cong truoc do")
    s.set_defaults(func=cmd_sync)

    v = sub.add_parser("verify", help="doi chieu ngay thang cua mail giua hai dau")
    v.add_argument("--only", default="")
    v.add_argument("--sample", type=int, default=200,
                   help="so mail lay mau moi folder (mac dinh 200, 0 = lay het)")
    v.set_defaults(func=cmd_verify)

    w = sub.add_parser("web", help="mo dashboard tren trinh duyet")
    w.add_argument("--host", default="127.0.0.1",
                   help="mac dinh 127.0.0.1; chi doi khi that su can, giao dien "
                        "nay cham vao mat khau")
    w.add_argument("--port", type=int, default=8765)
    w.set_defaults(func=cmd_web)

    r = sub.add_parser("report", help="xem lai bao cao cua lan chay truoc")
    r.add_argument("--list", action="store_true", help="liet ke cac lan chay da luu")
    r.add_argument("--run", default="", help="ten file run, vd 20260825-101500.json")
    r.add_argument("--out", default="", help="ghi ra file .csv hoac .html")
    r.set_defaults(func=cmd_report)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    if isinstance(getattr(args, "only", None), str):
        args.only = [s for s in args.only.split(",") if s.strip()]

    try:
        cfg = load_config(Path(args.config))
    except Exception as exc:
        say("Loi config: %s" % exc)
        return 2

    try:
        return args.func(args, cfg)
    except KeyboardInterrupt:
        say("\nDa dung.")
        return 130
    except FileNotFoundError as exc:
        say("Loi: %s" % exc)
        return 2
    except ValueError as exc:
        say("Loi du lieu: %s" % exc)
        return 2
