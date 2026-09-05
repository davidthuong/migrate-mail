# -*- coding: utf-8 -*-
"""Giao dien dong lenh cua migrate-mail."""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import sys
from contextlib import contextmanager
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__, mailboxes, providers, report, verify
from .config import Config, load_config
from .discover import (NOSELECT, SPECIAL_ARCHIVE, SPECIAL_DRAFTS, SPECIAL_JUNK,
                       SPECIAL_SENT, SPECIAL_TRASH, DiscoveryError, Plan,
                       DestLayout, build_plan, check_login, list_folders,
                       open_connection)
from .hints import diagnose
from .runner import (MODE_DRY, MODE_FOLDERS, MODE_SIZES, MODE_SYNC,
                     OAUTH_MIN_VERSION, Result, flags_used, imapsync_available,
                     imapsync_run, imapsync_version, run_user,
                     unsupported_flags, user_statedir)
from .users import User, check_permissions, filter_users, load_users

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


def _users(args, cfg: Config) -> List[User]:
    """Doc users.csv theo dung kieu xac thuc dang cau hinh.

    Nguon chay OAuth2 thi khong ai co mat khau cua user, nen cot src_password
    duoc phep de trong.
    """
    return load_users(args.users, need_src_password=not cfg.source.uses_oauth)


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #

def cmd_doctor(args, cfg: Config) -> int:
    problems = 0

    say("migrate-mail %s | Python %s" % (__version__, sys.version.split()[0]))
    say("config      : %s" % cfg.path)
    say("nguon       : %s | %s:%d (ssl=%s, auth=%s)"
        % (cfg.source.provider.name, cfg.source.host, cfg.source.port,
           cfg.source.ssl, cfg.source.auth))
    say("dich        : %s | %s:%d (ssl=%s, auth=%s)"
        % (cfg.dest.provider.name, cfg.dest.host, cfg.dest.port,
           cfg.dest.ssl, cfg.dest.auth))
    say("")

    problems += _check_oauth(cfg)

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
        users = _users(args, cfg)
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
    if problems:
        say("")
        _print_prep(cfg.source.provider, "nguon")
    return 0 if problems == 0 else 1


def _check_oauth(cfg: Config) -> int:
    """Kiem cau hinh OAuth2 va thu lay token that su -- doi khi la cach duy
    nhat biet client secret con han hay khong."""
    if not (cfg.source.uses_oauth or cfg.dest.uses_oauth):
        return 0

    problems = 0
    version = imapsync_version(cfg)
    if version is not None and version < OAUTH_MIN_VERSION:
        # Doi chieu ten tuy chon (unsupported_flags) khong bat duoc cho nay:
        # --oauthaccesstoken1 co tu 2.113, nhung truoc 2.251 imapsync van doi
        # co --password1 di kem nen se dung ngay.
        say("[LOI ] imapsync %d.%d qua cu cho auth = oauth2, can tu %d.%d tro len."
            % (version[0], version[1], OAUTH_MIN_VERSION[0], OAUTH_MIN_VERSION[1]))
        problems += 1

    warn = check_permissions(cfg.path)
    if warn:
        # config.ini luc nay chua client secret, khong con la file vo hai.
        say("[CANH] %s" % warn)

    for side, server in (("nguon", cfg.source), ("dich", cfg.dest)):
        if not server.uses_oauth:
            continue
        try:
            from .oauth import request_token
            _token, expires = request_token(server.oauth)
            say("[ OK ] OAuth2 %s: lay duoc token (han %d phut)"
                % (side, max(1, expires // 60)))
        except Exception as exc:
            say("[LOI ] OAuth2 %s: %s" % (side, exc))
            problems += 1
    return problems


def _print_prep(provider, side: str = "") -> None:
    if not provider.prep:
        return
    if side:
        say("Chuan bi phia %s (%s):" % (side, provider.name))
    else:
        say("Chuan bi truoc khi dung:")
    for step in provider.prep:
        say("  - %s" % report._wrap(step, indent=4))


# --------------------------------------------------------------------------- #
# mkusers
# --------------------------------------------------------------------------- #

# So dong dia chi in ra de nguoi chay soi bang mat. Loi hay gap nhat khong
# phai thieu mailbox ma la dia chi dich sai domain, va cho do chi can nhin
# vai dong dau la thay.
_SAMPLE_ROWS = 10


def cmd_mkusers(args, cfg: Config) -> int:
    out = Path(args.out or args.users)
    if out.exists() and not args.force:
        say("Loi: %s da ton tai." % out)
        say("File nay thuong dang chua mat khau that. Ghi ra cho khac bang")
        say("--out, hoac them --force neu chac chan muon thay the.")
        return 2
    if args.blank_passwords and args.dst_password:
        say("Loi: --blank-passwords va --dst-password nguoc nhau, chon mot cai.")
        return 2

    if args.input == "-":
        raw = sys.stdin.buffer.read()
        label = "(stdin)"
    else:
        try:
            raw = Path(args.input).read_bytes()
        except OSError as exc:
            say("Loi: khong doc duoc %s: %s" % (args.input, exc))
            return 2
        label = str(args.input)

    parsed = mailboxes.parse(
        mailboxes.decode(raw),
        keep_all_types=args.keep_all_types,
        domains=[d for d in (args.domain or "").split(",") if d.strip()])

    say("Doc %s: %d dong du lieu%s"
        % (label, parsed.rows_read,
           (", cot dia chi '%s'" % parsed.address_column)
           if parsed.address_column else ""))
    say("")

    if parsed.skipped:
        say("BO QUA %d dong:" % len(parsed.skipped))
        for who, reason in parsed.skipped:
            say("    - %-36s %s" % (who, reason))
        say("")
    if not parsed.mailboxes:
        say("Khong con mailbox nao sau khi loc, khong ghi file.")
        return 1

    say("LAY %d mailbox:" % len(parsed.mailboxes))
    for kind, count in parsed.kind_counts():
        say("    %-30s %d" % (kind, count))
    say("")

    # Cot src_password luon de trong: Get-Mailbox khong cho ra mat khau cua
    # user. Voi nguon chay OAuth2 thi nhu vay la du (load_users cho phep trong),
    # voi nguon chay password thi phai dien tay -- noi ro o cuoi lenh.
    rows = mailboxes.build_rows(
        parsed.mailboxes, dst_domain=args.dst_domain,
        dst_password=args.dst_password,
        blank_passwords=args.blank_passwords)

    say("Dia chi ben dich (%s):"
        % ("doi domain sang @%s" % args.dst_domain.strip().lstrip("@")
           if args.dst_domain else "giu nguyen dia chi nguon"))
    for row in rows[:_SAMPLE_ROWS]:
        say("    %-38s -> %s" % (row[0], row[2]))
    if len(rows) > _SAMPLE_ROWS:
        say("    ... va %d dong nua" % (len(rows) - _SAMPLE_ROWS))

    if parsed.warnings:
        say("")
        for warn in parsed.warnings:
            say("CANH BAO: %s" % report._wrap(warn, indent=10))

    notes = [
        "Sinh boi mm.py mkusers luc %s" % time.strftime("%Y-%m-%d %H:%M"),
        "Nguon danh sach: %s (%d mailbox)" % (label, len(rows)),
        "",
    ]
    mailboxes.write_users(out, rows, notes)
    say("")
    say("Da ghi %d dong vao %s" % (len(rows), out))
    if os.name == "posix":
        say("Da dat quyen 600 cho file nay.")

    say("")
    if args.blank_passwords:
        say("Cot dst_password dang de trong: users.csv chua doc duoc, phai dien")
        say("vao truoc khi chay preflight.")
    elif args.dst_password:
        say("Moi mailbox dich dung chung mot mat khau. Nho doi lai sau cutover.")
    else:
        say("Mat khau ben dich do tool sinh ra. Phai tao mailbox ben dich VOI")
        say("DUNG nhung mat khau nay, hoac sua lai cot dst_password cho khop.")
    if cfg.source.uses_oauth:
        say("Nguon chay OAuth2 nen cot src_password de trong la dung.")
    else:
        say("Nguon dang auth = %s: phai dien cot src_password tay, Get-Mailbox"
            % cfg.source.auth)
        say("khong cho ra mat khau cua user.")
    say("")
    say("Buoc tiep: ./mm.py preflight")
    return 0


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #

def cmd_preflight(args, cfg: Config) -> int:
    users = filter_users(_users(args, cfg), args.only)
    say("Kiem tra dang nhap %d mailbox: %s -> %s\n"
        % (len(users), cfg.source.provider.name, cfg.dest.provider.name))

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
        # Goi y o day lay tu chinh cau bao loi cua server, chu khong doan theo
        # provider: cung mot provider co the hong vi mat khau sai, vi IMAP bi
        # tat, hay vi IP bi chan -- ba viec can lam khac han nhau.
        for user, src, dst in bad:
            for side, (ok, msg) in (("nguon", src), ("dich", dst)):
                if ok:
                    continue
                tips = diagnose(msg, limit=2, source=cfg.source.provider.key,
                                dest=cfg.dest.provider.key)
                for tip in tips:
                    say("  %s (%s): %s" % (user.src_user, side,
                                           report._wrap(tip, indent=4)))
        say("")
        _print_prep(cfg.source.provider, "nguon")
        say("")
        _print_prep(cfg.dest.provider, "dich")
    return 0 if not bad else 1


# --------------------------------------------------------------------------- #
# discover
# --------------------------------------------------------------------------- #

def _discover_one(cfg: Config, user: User,
                  dest: Optional[DestLayout] = None) -> Tuple[User, Optional[Plan], str]:
    try:
        folders = list_folders(cfg, user)
        layout = dest.get(user) if dest is not None else None
        return user, build_plan(folders, cfg.sync, cfg.source.provider,
                                dest=layout), ""
    except DiscoveryError as exc:
        return user, None, str(exc)
    except Exception as exc:                                # pragma: no cover
        return user, None, "%s: %s" % (type(exc).__name__, exc)


def _print_plan(user: User, plan: Plan, cfg: Config) -> None:
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
    _print_collisions(plan, cfg)


def _print_unmappable(plan: Plan) -> None:
    if not plan.unmappable:
        return
    say("")
    say("  !! KHONG DOI TEN DUOC !!")
    say("  Ten folder co chua dau '=' ma imapsync dung dau do lam dau phan cach")
    say("  cho --f1f2, nen khong dien ta duoc. Cac folder sau se GIU NGUYEN ten:")
    for folder, wanted in plan.unmappable:
        say("    %s  (le ra -> %s)" % (folder.display, wanted))
    say("  Cach xu ly: doi ten folder do ben nguon cho het dau '=', roi chay lai.")


def _print_collisions(plan: Plan, cfg: Config) -> None:
    collisions = plan.collisions()
    if not collisions:
        return
    say("")
    say("  !! TRUNG TEN FOLDER DICH !!")
    say("  Nhieu folder ben %s se do chung vao mot folder ben %s:"
        % (cfg.source.provider.name, cfg.dest.provider.name))
    for dest, sources in collisions:
        say("    %s  <-  %s" % (dest, ", ".join(f.display for f in sources)))
    say("")
    say("  Thuong gap khi hop thu nguon truoc day da tung import tu noi khac:")
    say("  ben canh folder chuan con sot lai mot folder cu cung cong dung.")
    say("  Neu muon giu rieng, doi ten label cu bang extra_args trong config.ini:")
    for dest, _sources in collisions:
        say("    extra_args = --regextrans2 s,^%s$,%s-cu," % (dest, dest))
    say("  Neu tron chung la y muon thi cu chay tiep, khong mat mail.")


def _print_dest_folders(cfg: Config, user: User) -> int:
    """Liet ke folder co san ben dich va canh bao neu ten map khong khop.

    Can buoc nay vi neu server dich goi folder rac la 'Junk E-mail' ma ta lai
    map sang 'Spam', imapsync se tao them mot folder 'Spam' moi -- ket qua la
    hop thu co hai folder rac song song, va bo loc cua server van dung folder cu.
    """
    dest_name = cfg.dest.provider.name
    say("")
    say("=== %s (ben %s) ===" % (user.dst_user, dest_name))
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
                            (SPECIAL_TRASH, "Trash"), (SPECIAL_JUNK, "Junk"),
                            (SPECIAL_ARCHIVE, "Archive")):
            if f.has(flag):
                marks.append("special-use: %s" % label)
        say("    - %-38s %s" % (f.display, "  ".join(marks)))

    wanted = {
        "sent_folder": cfg.sync.sent_folder,
        "drafts_folder": cfg.sync.drafts_folder,
        "trash_folder": cfg.sync.trash_folder,
        "junk_folder": cfg.sync.junk_folder,
        "archive_folder": cfg.sync.archive_folder,
    }
    missing = {k: v for k, v in wanted.items() if v and v not in existing}
    if missing:
        say("")
        say("  CANH BAO: cac ten sau trong config.ini chua co ben %s," % dest_name)
        say("  imapsync se TAO MOI folder trung ten:")
        for key, value in missing.items():
            say("    %-14s = %s" % (key, value))
        say("  Neu ben dich da co folder cung cong dung nhung khac ten, hay sua")
        say("  config.ini cho khop de mail khong bi tach ra hai noi.")
    return 0


def cmd_discover(args, cfg: Config) -> int:
    users = filter_users(_users(args, cfg), args.only)

    if args.dest:
        say("Liet ke folder cua %d mailbox tren %s (%s)..."
            % (len(users), cfg.dest.host, cfg.dest.provider.name))
        failed = sum(_print_dest_folders(cfg, u) for u in users)
        say("")
        say("Xong. %d/%d mailbox doc duoc." % (len(users) - failed, len(users)))
        return 0 if failed == 0 else 1

    say("Do folder cua %d mailbox tren %s (%s)...\n"
        % (len(users), cfg.source.host, cfg.source.provider.name))
    dest = DestLayout(cfg)
    failed = 0
    with futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(users)))) as pool:
        jobs = [pool.submit(_discover_one, cfg, u, dest) for u in users]
        for job in jobs:
            user, plan, err = job.result()
            if plan is None:
                failed += 1
                say("")
                say("=== %s ===" % user.src_user)
                say("  LOI: %s" % err)
                continue
            _print_plan(user, plan, cfg)
    say("")
    _print_dest_layout(dest)
    say("Xong. %d/%d mailbox do duoc." % (len(users) - failed, len(users)))
    return 0 if failed == 0 else 1


def _print_dest_layout(dest: DestLayout) -> None:
    """Noi ra tien to ben dich da do duoc, vi no doi ten MOI folder."""
    layout = dest.peek()
    if dest.error:
        say("CANH BAO: khong doc duoc namespace ben dich (%s)." % dest.error)
        say("Ke hoach o tren dung theo gia thiet ben dich khong co tien to.")
        say("")
        return
    if layout is not None and layout.prefix:
        say("Ben dich de folder duoi tien to '%s' (dau phan cach '%s'), nen moi"
            % (layout.prefix, layout.delim or "/"))
        say("ten dich o tren da duoc them tien to do.")
        say("")


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #

def _done_marker(cfg: Config, user: User) -> Path:
    return user_statedir(cfg, user) / "done.marker"


def cmd_sync(args, cfg: Config) -> int:
    users = filter_users(_users(args, cfg), args.only)
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

    src_name = cfg.source.provider.name
    dst_name = cfg.dest.provider.name

    say("Che do  : %s%s" % (mode, " (--since-days %d)" % args.since_days if args.since_days else ""))
    say("Chuyen  : %s -> %s" % (src_name, dst_name))
    say("Mailbox : %d | song song: %d" % (len(users), workers))
    say("Log     : %s" % cfg.paths.logdir)
    if mode == MODE_DRY:
        say("Day la chay thu, khong mail nao duoc ghi vao %s." % dst_name)
    elif mode == MODE_FOLDERS:
        say("Chi tao cay folder ben %s, khong chuyen mail nao." % dst_name)
    elif mode == MODE_SIZES:
        say("Chi dem dung luong ben %s, khong chuyen mail nao." % src_name)
    say("")

    # Buoc 1: do folder. Neu khong do duoc thi KHONG chay mailbox do -- chay mu
    # se rat de keo ca folder ao (All Mail cua Gmail, Sync Issues cua Exchange)
    # sang, lam phinh dung luong hoac do rac vao hop thu moi.
    say("[1/2] Do folder %s..." % src_name)
    plans: Dict[str, Plan] = {}
    predelivered: List[Result] = []
    dest_layout = DestLayout(cfg)
    with futures.ThreadPoolExecutor(max_workers=min(8, len(users))) as pool:
        for user, plan, err in pool.map(
                lambda u: _discover_one(cfg, u, dest_layout), users):
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

    _print_dest_layout(dest_layout)

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

    rows = report.rows_from_results(results, cfg)
    say("")
    if mode == MODE_SIZES:
        _print_sizes(results, cfg)
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


def _print_sizes(results: List[Result], cfg: Config) -> None:
    """Bao cao dung luong, kem tran tren so ngay neu nguon co han muc/ngay.

    Cot "Ngay toi da" chi hien khi nha cung cap nguon that su cong bo mot han
    muc tai ve theo ngay -- hien nay chi Gmail. Voi cac nguon khac, con so do
    khong ton tai: cai chan ho la so ket noi dong thoi, khong phai dung luong.

    Ngay ca voi Gmail day cung la kich ban XAU NHAT chu khong phai du bao. Do
    thuc te cho thay account Workspace tai lien mach vuot xa 2500 MB ma khong
    bi chan, nen thuong xong som hon nhieu.
    """
    provider = cfg.source.provider
    limit = provider.daily_limit
    header = "%-34s %10s %12s %13s" % ("Mailbox", "Mail", "Dung luong",
                                       "Mail lon nhat")
    if limit:
        header += " %10s" % "Ngay toi da"
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
        total_bytes += size
        total_msgs += msgs
        line = ("%-34s %10s %12s %13s"
                % (r.user.src_user, "{:,}".format(msgs).replace(",", "."),
                   report.human_bytes(size),
                   report.human_bytes(r.get("source_biggest"))))
        if limit:
            days = _days_needed(size, limit)
            max_days = max(max_days, days)
            line += " %10s" % days
        say(line)
    say("")
    say("Tong: %s mail, %s."
        % ("{:,}".format(total_msgs).replace(",", "."), report.human_bytes(total_bytes)))
    say("")
    if provider.daily_limit_note:
        say(report._wrap(provider.daily_limit_note))
        say("")
    if limit:
        say("Day la TRAN TREN, khong phai du bao. Thuc te da gap account tai lien")
        say("mach vuot xa muc do ma khong bi chan, xong som hon nhieu.")
    say("Muon biet con bao lau that su thi xem toc do trong log luc dang chay:")
    say("  tail -1 logs/<mailbox>.sync.*.log")
    say("dong do co san so mail/s va tong da chep.")
    if max_days > 1:
        say("")
        say("Neu dung phai gioi han, hop thu lon nhat can toi da %d ngay." % max_days)
        say("Moi ngay chay lai dung lenh sync: mail da chuyen khong bi chep lai,")
        say("no chi lam tiep phan con thieu.")


def _days_needed(size_bytes: int, daily_limit: int) -> int:
    if size_bytes <= 0 or daily_limit <= 0:
        return 0
    return -(-size_bytes // daily_limit)      # lam tron len



# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #

def _verify_one(cfg: Config, user: User, cap: int,
                dest: Optional[DestLayout] = None) -> verify.UserCheck:
    check = verify.UserCheck(src_user=user.src_user, dst_user=user.dst_user)
    src_conn = dst_conn = None
    try:
        folders = list_folders(cfg, user)
        # Phai dung cung ke hoach nhu luc sync, khong thi verify se di tim
        # folder o sai ten va bao "thieu ben dich" cho ca hop thu day du.
        plan = build_plan(folders, cfg.sync, cfg.source.provider,
                          dest=dest.get(user) if dest is not None else None)
        src_conn = open_connection(cfg, user, "source")
        dst_conn = open_connection(cfg, user, "dest")

        pairs = [(f, dest) for f, dest in plan.mapped] + [(f, f.raw) for f in plan.kept]
        for folder, dest_name in pairs:
            fc = verify.FolderCheck(source_folder=folder.display, dest_folder=dest_name)
            try:
                # Lay mau ben nguon (dat: co the bi bop bang thong va bi dem
                # lenh), nhung lay HET ben dich (re: server nha, khong han muc).
                #
                # Truoc day lay mau ca hai dau voi cung `cap`. Hai folder gan
                # nhu khong bao gio cung so luong, va thu tu cung khac nhau
                # (ben dich xep theo thu tu imapsync chep sang), nen hai mau
                # roi vao hai tap mail khac nhau. Phan khong giao nhau bi tinh
                # thanh "thieu ben dich" -- co lan bao thieu 504 mail tren mot
                # hop thu ma imapsync da xac nhan la day du.
                src_index, fc.source_total = verify.fetch_index(src_conn, folder.raw, cap)
                dst_index, fc.dest_total = verify.fetch_index(dst_conn, dest_name, 0)
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
    users = filter_users(_users(args, cfg), args.only)
    cap = args.sample

    # verify la bang chung cuoi cung truoc cutover, nen phai luu lai duoc.
    # Truoc day no chi in ra man hinh: chay bang `screen -dmS` roi mat phien
    # la mat sach ket qua, trong khi `sync` thi ghi log tung mailbox tu dau.
    logdir = Path(cfg.paths.logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    logpath = logdir / ("verify-%s.txt" % time.strftime("%Y%m%d-%H%M%S"))
    fh = logpath.open("w", encoding="utf-8", newline="\n")

    def out(line: str = "") -> None:
        say(line)
        fh.write(line + "\n")
        fh.flush()          # xa ngay de `tail -f` doc duoc trong luc dang chay

    try:
        out("Doi chieu ngay thang cua mail giua hai dau.")
        out("Lay mau toi da %d mail moi folder o ben %s, doi chieu voi toan "
            "bo folder ben %s."
            % (cap, cfg.source.provider.name, cfg.dest.provider.name))
        out("Sai lech duoi %ds coi nhu khop.\n" % verify.TOLERANCE_SECONDS)

        dest_layout = DestLayout(cfg)
        checks: List[verify.UserCheck] = []
        with futures.ThreadPoolExecutor(max_workers=min(4, max(1, len(users)))) as pool:
            for check in pool.map(
                    lambda u: _verify_one(cfg, u, cap, dest_layout), users):
                checks.append(check)
                if check.error:
                    out("LOI  %-32s %s" % (check.src_user, check.error))
                    continue
                flag = "OK  " if check.ok else "LECH"
                out("%s %-32s doi chieu %d mail, lech %d, thieu ben dich %d"
                    % (flag, check.src_user, check.compared, check.mismatched,
                       check.missing))
                for fc in check.folders:
                    if fc.error:
                        out("       %-28s loi: %s" % (fc.source_folder, fc.error))
                    elif fc.mismatched:
                        out("       %-28s %d/%d lech ngay"
                            % (fc.source_folder, fc.mismatched, fc.compared))
                        for msgid, src_e, dst_e in fc.samples:
                            out("         %s" % msgid[:60])
                            out("           nguon: %s" % _fmt_epoch(src_e))
                            out("           dich : %s" % _fmt_epoch(dst_e))

        total_cmp = sum(c.compared for c in checks)
        total_bad = sum(c.mismatched for c in checks)
        total_missing = sum(c.missing for c in checks)
        failed = [c for c in checks if not c.ok]

        out("")
        if total_cmp == 0:
            out("Khong doi chieu duoc mail nao. Da chay sync chua? Folder ben "
                "dich co ton tai khong?")
            return 1
        out("Ket qua: %d mail doi chieu, %d lech ngay (%.2f%%)."
            % (total_cmp, total_bad, 100.0 * total_bad / total_cmp))
        if total_missing:
            out("%d mail trong mau khong tim thay ben dich. Mot phan la mail von "
                "khong co Message-Id (hay gap o Drafts) duoc --addheader gan cho "
                "mot cai luc chep sang, nen hai dau khong ghep duoc. Con lai la "
                "mail thieu that -- doi chieu voi dong 'Messages found in host1 "
                "not in host2' o cuoi log sync, do la so dem day du chu khong "
                "phai lay mau." % total_missing)
        if total_bad:
            out("")
            out("Ngay KHONG duoc giu nguyen. Kiem tra theo thu tu nay:")
            out("  1. Xem log sync co dong 'Info: turned ON syncinternaldates' khong.")
            out("  2. Neu co ma van lech, %s dang bo qua ngay trong lenh APPEND."
                % cfg.dest.provider.name)
            out("     Doi date_source = header trong config.ini roi sync lai mailbox do")
            out("     bang: ./mm.py sync --only <dia chi>")
            out("  3. Neu van lech, hoi nha cung cap %s ve viec server ghi de"
                % cfg.dest.provider.name)
            out("     INTERNALDATE luc APPEND.")
        elif failed:
            out("Ngay khop het, nhung co folder khong doi chieu duoc (xem o tren).")
        else:
            out("Ngay thang duoc giu nguyen tren toan bo mau kiem tra.")
        return 0 if not failed else 1
    finally:
        fh.close()
        say("")
        say("Da ghi %s" % logpath)


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

    merged = report.latest_rows(runs_dir)
    note = ""
    if args.all:
        # Gop moi lan chay. Day moi la thu dung de bao cao toan bo cuoc migrate.
        rows = report.refresh_hints(report.merged_rows(runs_dir))
        note = ("Gop %d mailbox tu %d lan chay. Cot Mail, Dung luong va T.gian "
                "la tong cong don qua tat ca cac lan chay; cot KQ va Folder la "
                "cua lan chay moi nhat." % (len(rows), len(runs)))
        say(note + "\n")
    else:
        target = runs_dir / args.run if args.run else runs[-1]
        if not target.exists():
            say("Khong thay %s" % target)
            return 1
        rows = report.refresh_hints(report.load_run(target))
        say("Lan chay: %s\n" % target.name)
        # Mot lan chay chi chua mailbox cua lan do. Rat de tuong nhan nham
        # bao cao mot mailbox thanh bao cao ca cuoc migrate.
        if len(rows) < len(merged):
            say("Lan chay nay chi co %d/%d mailbox da tung chay. Dung --all "
                "de gop tat ca.\n" % (len(rows), len(merged)))
    report.print_table(rows, emit=say)
    report.print_summary(rows, emit=say)
    if args.out:
        out = Path(args.out)
        if out.suffix.lower() == ".html":
            say("\nDa ghi %s" % report.write_html(rows, out, note))
        else:
            say("\nDa ghi %s" % report.write_csv(rows, out))
    return 0


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #

def cmd_providers(args, cfg: Optional[Config]) -> int:
    """Liet ke cac nha cung cap tool biet, kem viec phai chuan bi truoc."""
    wanted = (args.name or "").strip()
    if wanted:
        try:
            chosen = [providers.get(wanted)]
        except ValueError as exc:
            say("Loi: %s" % exc)
            return 2
    else:
        chosen = providers.all_providers()

    if not wanted:
        say("Dat gia tri nay vao 'provider =' trong [source] hoac [dest] cua")
        say("config.ini. Xem chi tiet mot cai: ./mm.py providers <ten>\n")
        say("%-10s %-34s %s" % ("ten", "nha cung cap", "host mac dinh"))
        say("-" * 74)
        for p in chosen:
            say("%-10s %-34s %s" % (p.key, p.name, p.host or "(phai tu dien)"))
        say("")
        say("Nguon nao chua co trong danh sach thi dung provider = imap va dien")
        say("host tay; tool van do folder theo co SPECIAL-USE va theo ten.")
        return 0

    for p in chosen:
        say("=== %s (provider = %s) ===" % (p.name, p.key))
        say("host mac dinh : %s" % (p.host or "(phai tu dien trong config.ini)"))
        say("cong          : %d (ssl=%s)" % (p.port, p.ssl))
        # 'master' co trong danh sach de config nhan ra, nhung phan dang nhap
        # bang tai khoan quan tri chua lam -- noi ro thay vi de nguoi doc tuong
        # la dung duoc ngay.
        say("xac thuc      : %s"
            % ", ".join(m + " (chua ho tro)" if m == providers.AUTH_MASTER else m
                        for m in p.auth_modes))
        if p.aliases:
            say("goi khac      : %s" % ", ".join(p.aliases))
        if p.max_connections:
            say("ket noi/account: toi da %d cung luc" % p.max_connections)
        say("han muc/ngay  : %s"
            % (report.human_bytes(p.daily_limit) if p.daily_limit else "khong cong bo"))
        if p.daily_limit_note:
            say("                %s" % report._wrap(p.daily_limit_note, indent=16))
        if p.folders:
            say("ten folder khi lam dich:")
            for role, name in sorted(p.folders.items()):
                say("    %-8s -> %s" % (role, name))
        if p.skip_names:
            say("folder khong phai mail (tu bo qua): %d loai" % len(p.skip_names))
        say("")
        _print_prep(p)
        say("")
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
        description="Migrate mail giua cac nha cung cap IMAP bang imapsync. "
                    "Chay 'mm providers' de xem cac nguon duoc ho tro.",
    )
    p.add_argument("--config", default="config.ini", help="mac dinh: config.ini")
    p.add_argument("--users", default="users.csv", help="mac dinh: users.csv")
    p.add_argument("--version", action="version", version="migrate-mail " + __version__)
    sub = p.add_subparsers(dest="command")

    pr = sub.add_parser("providers", help="cac nguon/dich duoc ho tro va cach chuan bi")
    pr.add_argument("name", nargs="?", default="",
                    help="xem chi tiet mot cai, vd: m365")
    # Lenh nay phai chay duoc TRUOC khi co config.ini: nguoi dung can biet
    # dien gi vao 'provider =' truoc da.
    pr.set_defaults(func=cmd_providers, needs_config=False)

    d = sub.add_parser("doctor", help="kiem tra moi truong truoc khi lam gi khac")
    d.set_defaults(func=cmd_doctor)

    mk = sub.add_parser(
        "mkusers",
        help="sinh users.csv tu danh sach mailbox ben nguon (Get-Mailbox)",
        description="Doc file danh sach mailbox xuat tu he thong nguon roi "
                    "sinh users.csv. Nhan CSV cua Export-Csv (ke ca ban UTF-16 "
                    "hoac con dong #TYPE), hoac danh sach dia chi tho moi dong "
                    "mot cai. Dung '-' de doc tu stdin.")
    mk.add_argument("input", help="file danh sach mailbox, hoac '-' cho stdin")
    mk.add_argument("--out", default="",
                    help="ghi ra duong dan nay thay vi --users (users.csv)")
    mk.add_argument("--force", action="store_true",
                    help="cho phep ghi de file da co -- can nho file cu co the "
                         "dang chua mat khau that")
    mk.add_argument("--dst-domain", default="",
                    help="doi domain ben dich, vd congty.vn; mac dinh giu "
                         "nguyen dia chi nguon")
    mk.add_argument("--domain", default="",
                    help="chi lay mailbox thuoc domain nay, nhieu cai cach "
                         "nhau bang dau phay")
    mk.add_argument("--dst-password", default="",
                    help="dung chung mot mat khau cho moi mailbox dich; "
                         "mac dinh sinh ngau nhien tung cai")
    mk.add_argument("--blank-passwords", action="store_true",
                    help="de trong cot dst_password de dien tay sau")
    mk.add_argument("--keep-all-types", action="store_true",
                    help="giu ca phong hop, thiet bi va hop thu he thong")
    mk.set_defaults(func=cmd_mkusers)

    pf = sub.add_parser("preflight", help="thu dang nhap ca hai dau cho tung mailbox")
    pf.add_argument("--only", default="", help="chi chay vai dia chi, cach nhau bang dau phay")
    pf.set_defaults(func=cmd_preflight)

    dc = sub.add_parser("discover", help="xem folder ben nguon va ke hoach chuyen doi")
    dc.add_argument("--only", default="")
    dc.add_argument("--dest", action="store_true",
                    help="liet ke folder co san ben dich thay vi ben nguon")
    dc.set_defaults(func=cmd_discover)

    s = sub.add_parser("sync", help="chay migration")
    s.add_argument("--only", default="")
    s.add_argument("--dry", action="store_true", help="chay thu, khong ghi gi vao dich")
    s.add_argument("--sizes", action="store_true",
                   help="chi dem dung luong ben nguon va uoc luong so ngay can chay")
    s.add_argument("--folders-only", action="store_true",
                   help="chi tao cay folder ben dich, khong chuyen mail; "
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
    r.add_argument("--all", action="store_true",
                   help="gop tat ca lan chay: dong moi nhat cua tung mailbox. "
                        "Dung cai nay khi bao cao ca cuoc migrate")
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

    cfg = None
    if getattr(args, "needs_config", True):
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
