# -*- coding: utf-8 -*-
"""Dung lenh imapsync, chay no, va doc ket qua.

Ba diem quan trong khi chay nhieu mailbox song song:

1. Password di qua --passfile1/--passfile2 chu KHONG qua tham so dong lenh.
   Tham so dong lenh hien trong `ps aux` cho moi user tren VPS.
2. Moi mailbox co --pidfile rieng. imapsync mac dinh dung chung mot pidfile
   va se tu choi chay khi thay tien trinh khac.
3. Moi mailbox co --tmpdir rieng. Do la noi imapsync giu cache dong bo, giu
   lai giua cac lan chay se lam vong delta (luc cutover) nhanh hon rat nhieu.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config
from .discover import Plan
from .hints import diagnose
from .users import User

MODE_SYNC = "sync"
MODE_DRY = "dry"
MODE_FOLDERS = "folders"

# Cac dong thong ke o cuoi output imapsync
_STAT_PATTERNS = {
    "messages_transferred": r"Messages transferred\s*:\s*(\d+)",
    "messages_skipped": r"Messages skipped\s*:\s*(\d+)",
    "messages_deleted1": r"Messages deleted on host1\s*:\s*(\d+)",
    "bytes_transferred": r"Total bytes transferred\s*:\s*(\d+)",
    "bytes_skipped": r"Total bytes skipped\s*:\s*(\d+)",
    "biggest_message": r"Biggest message\s*:\s*(\d+)",
    "errors": r"Detected\s+(\d+)\s+errors?",
}
_TIME_RE = re.compile(r"Transfer time\s*:\s*([\d.]+)\s*sec")
_FOLDERS_RE = re.compile(r"Folders synced\s*:\s*(\d+)\s*/\s*(\d+)")
# imapsync tu in ten ma loi cua no, khong can ta doan
_EXIT_RE = re.compile(r"Exiting with return value\s+(\d+)\s*\(([^)]*)\)")


@dataclass
class Result:
    user: User
    mode: str
    exit_code: int = -1
    exit_label: str = ""
    started: float = 0.0
    finished: float = 0.0
    stats: Dict[str, int] = field(default_factory=dict)
    transfer_time: float = 0.0
    folders_synced: str = ""
    logfile: Optional[Path] = None
    error: str = ""
    hints: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.error

    @property
    def duration(self) -> float:
        return max(0.0, self.finished - self.started)

    def get(self, key: str, default: int = 0) -> int:
        return self.stats.get(key, default)


def _write_secret(path: Path, value: str) -> None:
    """Ghi file chi chu so huu doc duoc, tao voi quyen dung ngay tu dau."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)


def user_statedir(cfg: Config, user: User) -> Path:
    return Path(cfg.paths.statedir) / user.slug


def build_command(cfg: Config, user: User, plan: Optional[Plan], mode: str,
                  passfile1: Path, passfile2: Path, statedir: Path,
                  since_days: int = 0) -> List[str]:
    sync = cfg.sync
    cmd: List[str] = list(cfg.paths.imapsync_argv)

    cmd += ["--host1", cfg.source.host, "--port1", str(cfg.source.port)]
    cmd += ["--ssl1"] if cfg.source.ssl else ["--notls1"]
    cmd += ["--user1", user.src_user, "--passfile1", str(passfile1)]

    cmd += ["--host2", cfg.dest.host, "--port2", str(cfg.dest.port)]
    cmd += ["--ssl2"] if cfg.dest.ssl else ["--notls2"]
    cmd += ["--user2", user.dst_user, "--passfile2", str(passfile2)]

    if plan is not None:
        cmd += plan.imapsync_args()

    # --- Giu ngay thang cua mail -------------------------------------------
    # Day la nguyen nhan cua trieu chung "mail nhay het ve ngay migrate".
    # imapsync mac dinh da bat syncinternaldates, nhung ta viet ra tuong minh
    # de nhin thay trong log, va de khong phu thuoc vao mac dinh co the doi.
    #   internal: dung INTERNALDATE cua Gmail (ngay mail vao hop thu Gmail)
    #   header  : dung header Date: trong than mail (ngay nguoi gui gui di)
    if sync.date_source == "header":
        cmd += ["--idatefromheader"]
    else:
        cmd += ["--syncinternaldates"]

    # Gmail co the sua header Received, nen chi dinh danh mail bang Message-Id.
    cmd += ["--useheader", "Message-Id"]
    # Mail thieu Message-Id (hay gap o Drafts) se bi coi la moi o moi lan chay
    # -> nhan ban khi chay vong delta. --addheader gan dinh danh on dinh cho chung.
    cmd += ["--addheader"]

    if sync.filterflags:
        # Bo cac flag ma IceWarp khong nhan, thay vi de imapsync bao loi tung mail.
        cmd += ["--filterflags"]
    if sync.skipcrossduplicates:
        cmd += ["--skipcrossduplicates"]
    if not sync.usecache:
        cmd += ["--nousecache"]

    if sync.maxsize > 0:
        cmd += ["--maxsize", str(sync.maxsize)]
    if sync.maxbytespersecond > 0:
        cmd += ["--maxbytespersecond", str(sync.maxbytespersecond)]
    if since_days > 0:
        cmd += ["--maxage", str(since_days)]

    cmd += ["--timeout", str(sync.timeout)]
    cmd += ["--errorsmax", str(sync.errorsmax)]
    cmd += ["--nofoldersizes"]        # bo buoc dem dung luong dau vao cho nhanh
    cmd += ["--noreleasecheck"]       # khong goi ra internet kiem tra ban moi
    cmd += ["--nolog"]                # ta tu giu log, khong dung LOG_imapsync/
    cmd += ["--tmpdir", str(statedir)]
    cmd += ["--pidfile", str(statedir / "imapsync.pid")]

    if mode == MODE_DRY:
        cmd += ["--dry"]
    elif mode == MODE_FOLDERS:
        cmd += ["--dry", "--justfolders"]

    cmd += sync.extra_args
    return cmd


def parse_output(text: str) -> Dict[str, object]:
    out: Dict[str, object] = {"stats": {}}
    for key, pattern in _STAT_PATTERNS.items():
        m = re.search(pattern, text)
        if m:
            out["stats"][key] = int(m.group(1))
    m = _TIME_RE.search(text)
    if m:
        out["transfer_time"] = float(m.group(1))
    m = _FOLDERS_RE.search(text)
    if m:
        out["folders_synced"] = "%s/%s" % (m.group(1), m.group(2))
    m = None
    for m in _EXIT_RE.finditer(text):
        pass                      # lay lan xuat hien cuoi cung
    if m:
        out["exit_label"] = m.group(2).strip()
    return out


def run_user(cfg: Config, user: User, plan: Optional[Plan], mode: str = MODE_SYNC,
             since_days: int = 0, on_line=None) -> Result:
    """Chay imapsync cho mot mailbox. Tra ve Result, khong nem exception."""
    result = Result(user=user, mode=mode, started=time.time())

    statedir = user_statedir(cfg, user)
    statedir.mkdir(parents=True, exist_ok=True)
    logdir = Path(cfg.paths.logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    logfile = logdir / ("%s.%s.%s.log" % (user.slug, mode, stamp))
    result.logfile = logfile

    pass1 = statedir / "src.pass"
    pass2 = statedir / "dst.pass"

    try:
        _write_secret(pass1, user.src_password)
        _write_secret(pass2, user.dst_password)
        cmd = build_command(cfg, user, plan, mode, pass1, pass2, statedir, since_days)

        chunks: List[str] = []
        with logfile.open("w", encoding="utf-8", errors="replace", newline="\n") as fh:
            fh.write("# lenh: %s\n" % " ".join(_redact(cmd)))
            fh.write("# bat dau: %s\n\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            fh.flush()
            # encoding phai chi dinh ro: mac dinh Python doc theo locale cua he
            # thong, va imapsync in ra ten folder tieng Viet -- gap locale kieu
            # C/latin-1 se nem UnicodeDecodeError va giet ca phien sync.
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", bufsize=1,
            )
            # `with proc` dam bao dong pipe va wait() ke ca khi co exception
            with proc:
                assert proc.stdout is not None
                for line in proc.stdout:
                    fh.write(line)
                    chunks.append(line)
                    if on_line:
                        on_line(user, line.rstrip("\n"))
            result.exit_code = proc.returncode

        parsed = parse_output("".join(chunks))
        result.stats = parsed.get("stats", {})            # type: ignore[assignment]
        result.transfer_time = float(parsed.get("transfer_time", 0.0))  # type: ignore[arg-type]
        result.folders_synced = str(parsed.get("folders_synced", ""))
        result.exit_label = str(parsed.get("exit_label", ""))
        if result.exit_code != 0 and not result.exit_label:
            result.exit_label = "exit code %d" % result.exit_code
        if result.exit_code != 0 or result.get("errors") > 0:
            result.hints = diagnose("".join(chunks))

    except FileNotFoundError:
        result.error = ("khong tim thay lenh '%s'. Chay ./install.sh hoac sua "
                        "[paths] imapsync trong config.ini" % cfg.paths.imapsync)
    except KeyboardInterrupt:
        result.error = "bi nguoi dung dung"
        raise
    except Exception as exc:                              # pragma: no cover
        result.error = "%s: %s" % (type(exc).__name__, exc)
    finally:
        for p in (pass1, pass2):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        result.finished = time.time()

    return result


def _redact(cmd: List[str]) -> List[str]:
    """Che duong dan passfile khi ghi lenh vao log."""
    out = []
    skip = False
    for token in cmd:
        if skip:
            out.append("<passfile>")
            skip = False
            continue
        out.append(token)
        if token in ("--passfile1", "--passfile2"):
            skip = True
    return out


def imapsync_available(cfg: Config) -> Optional[str]:
    """Tra ve duong dan imapsync neu tim thay, None neu khong."""
    exe = cfg.paths.imapsync_exe
    path = shutil.which(exe)
    if path:
        return path
    p = Path(exe)
    return str(p) if p.exists() else None


def imapsync_run(cfg: Config, flag: str, timeout: int = 30) -> str:
    """Chay imapsync voi mot flag doc thong tin (--help, --version)."""
    try:
        proc = subprocess.run(
            list(cfg.paths.imapsync_argv) + [flag], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout,
        )
        return proc.stdout or ""
    except Exception:
        return ""


def imapsync_help(cfg: Config, timeout: int = 30) -> str:
    return imapsync_run(cfg, "--help", timeout)


def unsupported_flags(cfg: Config, flags: List[str]) -> List[str]:
    """Doi chieu cac flag ta dinh dung voi `imapsync --help` cua ban dang cai."""
    help_text = imapsync_help(cfg)
    if not help_text:
        return []
    return [f for f in flags if f not in help_text]


def flags_used(cfg: Config) -> List[str]:
    """Danh sach flag tool nay co the sinh ra, de lenh `doctor` kiem tra."""
    base = [
        "--host1", "--port1", "--ssl1", "--notls1", "--user1", "--passfile1",
        "--host2", "--port2", "--ssl2", "--notls2", "--user2", "--passfile2",
        "--exclude", "--f1f2", "--useheader", "--addheader", "--filterflags",
        "--skipcrossduplicates", "--nousecache", "--maxsize", "--maxbytespersecond",
        "--maxage", "--timeout", "--errorsmax", "--nofoldersizes", "--noreleasecheck",
        "--nolog", "--tmpdir", "--pidfile", "--dry", "--justfolders",
    ]
    return base
