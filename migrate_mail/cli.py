# -*- coding: utf-8 -*-
"""Giao dien dong lenh cua migrate-mail."""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__, report
from .config import Config, load_config
from .discover import DiscoveryError, Plan, build_plan, check_login, list_folders
from .runner import (MODE_DRY, MODE_SYNC, Result, flags_used, imapsync_available,
                     imapsync_run, run_user, unsupported_flags, user_statedir)
from .users import User, filter_users, load_users

_print_lock = threading.Lock()


def say(msg: str = "") -> None:
    with _print_lock:
        print(msg, flush=True)


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
            say("[CANH] ban imapsync nay khong nhac toi cac flag sau trong --help:")
            say("       %s" % " ".join(missing))
            say("       Kiem tra lai bang 'imapsync --help' truoc khi chay that.")
            problems += 1
        else:
            say("[ OK ] moi flag tool dung deu co trong 'imapsync --help'")

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


def cmd_discover(args, cfg: Config) -> int:
    users = filter_users(load_users(args.users), args.only)
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
    mode = MODE_DRY if args.dry else MODE_SYNC

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
    report.print_table(rows)
    report.print_summary(rows)

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
    rows = report.load_run(target)
    say("Lan chay: %s\n" % target.name)
    report.print_table(rows)
    report.print_summary(rows)
    if args.out:
        out = Path(args.out)
        if out.suffix.lower() == ".html":
            say("\nDa ghi %s" % report.write_html(rows, out))
        else:
            say("\nDa ghi %s" % report.write_csv(rows, out))
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
    dc.set_defaults(func=cmd_discover)

    s = sub.add_parser("sync", help="chay migration")
    s.add_argument("--only", default="")
    s.add_argument("--dry", action="store_true", help="chay thu, khong ghi gi vao IceWarp")
    s.add_argument("--workers", type=int, default=0, help="ghi de [sync] workers")
    s.add_argument("--since-days", type=int, default=0,
                   help="chi chuyen mail moi hon N ngay (dung cho vong delta luc cutover)")
    s.add_argument("--resume", action="store_true",
                   help="bo qua mailbox da chay xong thanh cong truoc do")
    s.set_defaults(func=cmd_sync)

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
