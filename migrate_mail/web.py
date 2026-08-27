# -*- coding: utf-8 -*-
"""Dashboard web cho migrate-mail. Chi dung thu vien chuan.

An toan -- doc truoc khi mo ra ngoai:

Giao dien nay doc va ghi users.csv, tuc la no cham vao mat khau. Mac dinh no
chi lang nghe tren 127.0.0.1 va doi mot token ngau nhien sinh luc khoi dong.
Cach dung dung la SSH tunnel tu may ban:

    ssh -L 8765:127.0.0.1:8765 root@vps

roi mo dia chi ma server in ra. Khong bao gio mo cong nay ra Internet.

Mat khau khong bao gio duoc gui nguoc ve trinh duyet: API chi tra ve mot co
cho biet o do da co mat khau hay chua.
"""

from __future__ import annotations

import html
import json
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import __version__, cli, report
from .config import Config
from .users import User, load_users
from .web_ui import PAGE

MAX_LOG_LINES = 400

ACTIONS = {
    "preflight": "Kiem tra dang nhap",
    "discover": "Xem ke hoach folder",
    "dest": "Xem folder ben IceWarp",
    "folders": "Tao cay folder",
    "dry": "Chay khan",
    "sync": "Chay that",
    "verify": "Doi chieu ngay thang",
}


@dataclass
class Job:
    action: str
    only: List[str]
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    lines: List[str] = field(default_factory=list)
    error: str = ""
    exit_code: Optional[int] = None

    @property
    def running(self) -> bool:
        return self.finished == 0.0

    def append(self, line: str) -> None:
        self.lines.append(line)
        # Gioi han bo nho: giu lai phan dau (thong tin cau hinh) va phan cuoi
        if len(self.lines) > MAX_LOG_LINES * 2:
            head = self.lines[:40]
            tail = self.lines[-MAX_LOG_LINES:]
            self.lines = head + ["... (da luot bot phan giua) ..."] + tail

    def as_dict(self) -> Dict:
        return {
            "action": self.action,
            "action_label": ACTIONS.get(self.action, self.action),
            "only": self.only,
            "running": self.running,
            "started": self.started,
            "elapsed": (self.finished or time.time()) - self.started,
            "lines": self.lines[-MAX_LOG_LINES:],
            "error": self.error,
            "exit_code": self.exit_code,
        }


class JobManager:
    """Chay mot job tai mot thoi diem. Yeu cau nay lam cho viec huong output
    ve giao dien web tro nen don gian va khong the lan lon giua cac job."""

    def __init__(self, cfg: Config, users_path: Path):
        self.cfg = cfg
        self.users_path = users_path
        self.lock = threading.Lock()
        self.job: Optional[Job] = None
        self.history: List[Job] = []

    def busy(self) -> bool:
        return self.job is not None and self.job.running

    def start(self, action: str, only: List[str]) -> Job:
        with self.lock:
            if self.busy():
                raise RuntimeError("dang co mot tac vu chay, cho no xong da")
            if action not in ACTIONS:
                raise ValueError("khong biet tac vu '%s'" % action)
            job = Job(action=action, only=list(only))
            self.job = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        try:
            args = _make_args(job.action, job.only, self.users_path)
            fn = _ACTION_FN[job.action]
            with cli.capture(job.append):
                job.exit_code = fn(args, self.cfg)
        except Exception as exc:
            job.error = "%s: %s" % (type(exc).__name__, exc)
            job.append("LOI: %s" % job.error)
        finally:
            job.finished = time.time()
            self.history.append(job)
            del self.history[:-20]


class _Args:
    """Thay cho argparse.Namespace, chi mang cac truong cac lenh can den."""

    def __init__(self, **kw):
        self.only: List[str] = []
        self.users = ""
        self.dry = False
        self.folders_only = False
        self.workers = 0
        self.since_days = 0
        self.resume = False
        self.dest = False
        self.sample = 200
        self.list = False
        self.run = ""
        self.out = ""
        self.__dict__.update(kw)


def _make_args(action: str, only: List[str], users_path: Path) -> _Args:
    args = _Args(only=list(only), users=str(users_path))
    if action == "dry":
        args.dry = True
    elif action == "folders":
        args.folders_only = True
    elif action == "dest":
        args.dest = True
    return args


_ACTION_FN: Dict[str, Callable] = {
    "preflight": lambda a, c: cli.cmd_preflight(a, c),
    "discover": lambda a, c: cli.cmd_discover(a, c),
    "dest": lambda a, c: cli.cmd_discover(a, c),
    "folders": lambda a, c: cli.cmd_sync(a, c),
    "dry": lambda a, c: cli.cmd_sync(a, c),
    "sync": lambda a, c: cli.cmd_sync(a, c),
    "verify": lambda a, c: cli.cmd_verify(a, c),
}


# --------------------------------------------------------------------------- #
# Doc trang thai
# --------------------------------------------------------------------------- #

def _latest_rows(cfg: Config) -> Dict[str, Dict]:
    """Ket qua sync gan nhat cho tung mailbox, gop tu cac lan chay da luu."""
    runs_dir = Path(cfg.paths.statedir) / "runs"
    out: Dict[str, Dict] = {}
    if not runs_dir.exists():
        return out
    for path in sorted(runs_dir.glob("*.json")):     # cu -> moi, ban sau de len
        try:
            for row in report.load_run(path):
                if row.get("mode") in ("sync", "dry"):
                    out[row.get("src_user", "")] = dict(row, run=path.stem)
        except (OSError, ValueError):
            continue
    return out


def _mailboxes(cfg: Config, users_path: Path) -> List[Dict]:
    try:
        users = load_users(users_path)
    except Exception:
        return []
    latest = _latest_rows(cfg)
    done_dir = Path(cfg.paths.statedir)
    rows = []
    for u in users:
        row = latest.get(u.src_user, {})
        rows.append({
            "src_user": u.src_user,
            "dst_user": u.dst_user,
            # Khong bao gio gui mat khau ve trinh duyet, chi bao la co hay khong
            "has_src_password": bool(u.src_password),
            "has_dst_password": bool(u.dst_password),
            "done": (done_dir / u.slug / "done.marker").exists(),
            "ket_qua": row.get("ket_qua", ""),
            "folder": row.get("folder", ""),
            "mail": row.get("mail_chuyen", ""),
            "dung_luong": row.get("dung_luong", ""),
            "thoi_gian": row.get("thoi_gian", ""),
            "loi": row.get("loi", ""),
            # Dung chung quy tac voi bao cao: dong OK khong co ghi chu
            "ghi_chu": report._note(row) if row else "",
            "goi_y": [t for t in (row.get("goi_y") or "").split(" | ") if t],
            "mode": row.get("mode", ""),
            "run": row.get("run", ""),
        })
    return rows


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = "migrate-mail/" + __version__
    manager: JobManager = None          # type: ignore[assignment]
    token: str = ""
    users_path: Path = None             # type: ignore[assignment]

    def log_message(self, fmt, *args):   # bot on hon log mac dinh
        return

    # -- tien ich -----------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra=None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Trang tu phuc vu, khong nhung gi ben ngoai
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorised(self) -> bool:
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "mmtoken" and secrets.compare_digest(value, self.token):
                return True
        return False

    def _body(self) -> Dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- routing ------------------------------------------------------------
    def do_GET(self):                                    # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            supplied = (query.get("t") or [""])[0]
            if secrets.compare_digest(supplied, self.token):
                # Dat cookie roi bo token khoi thanh dia chi, tranh no nam lai
                # trong lich su trinh duyet.
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header(
                    "Set-Cookie",
                    "mmtoken=%s; Path=/; HttpOnly; SameSite=Strict" % self.token)
                self.end_headers()
                return
            if not self._authorised():
                self._send(401, b"Thieu hoac sai token. Mo dung dia chi ma "
                                b"server in ra luc khoi dong.", "text/plain; charset=utf-8")
                return
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if not self._authorised():
            self._json({"error": "khong co quyen"}, 401)
            return

        if parsed.path == "/api/state":
            self._json({
                "version": __version__,
                "source": "%s:%d" % (self.manager.cfg.source.host,
                                     self.manager.cfg.source.port),
                "dest": "%s:%d" % (self.manager.cfg.dest.host,
                                   self.manager.cfg.dest.port),
                "config": str(self.manager.cfg.path),
                "users_file": str(self.users_path),
                "actions": ACTIONS,
                "mailboxes": _mailboxes(self.manager.cfg, self.users_path),
                "job": self.manager.job.as_dict() if self.manager.job else None,
            })
            return

        self._json({"error": "khong tim thay"}, 404)

    def do_POST(self):                                   # noqa: N802
        if not self._authorised():
            self._json({"error": "khong co quyen"}, 401)
            return
        parsed = urllib.parse.urlparse(self.path)
        body = self._body()

        if parsed.path == "/api/run":
            try:
                job = self.manager.start(str(body.get("action", "")),
                                         list(body.get("only") or []))
            except (RuntimeError, ValueError) as exc:
                self._json({"error": str(exc)}, 409)
                return
            self._json({"job": job.as_dict()})
            return

        if parsed.path == "/api/users":
            try:
                added = _add_user(self.users_path, body)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            self._json({"ok": True, "src_user": added})
            return

        self._json({"error": "khong tim thay"}, 404)


def _add_user(users_path: Path, body: Dict) -> str:
    """Them mot dong vao users.csv. Tra ve dia chi nguon vua them."""
    import csv

    fields = ["src_user", "src_password", "dst_user", "dst_password"]
    values = {k: str(body.get(k) or "").strip() for k in fields}
    missing = [k for k in fields if not values[k]]
    if missing:
        raise ValueError("thieu: %s" % ", ".join(missing))
    if "@" not in values["src_user"] or "@" not in values["dst_user"]:
        raise ValueError("dia chi phai co dang user@domain")

    existing = []
    try:
        existing = [u.src_user.lower() for u in load_users(users_path)]
    except Exception:
        pass
    if values["src_user"].lower() in existing:
        raise ValueError("%s da co trong danh sach" % values["src_user"])

    new_file = not users_path.exists() or users_path.stat().st_size == 0
    with users_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if new_file:
            writer.writeheader()
        writer.writerow(values)
    try:
        users_path.chmod(0o600)
    except OSError:
        pass
    return values["src_user"]


def serve(cfg: Config, users_path: Path, host: str = "127.0.0.1",
          port: int = 8765) -> None:
    token = secrets.token_urlsafe(24)
    Handler.manager = JobManager(cfg, Path(users_path))
    Handler.token = token
    Handler.users_path = Path(users_path)

    httpd = ThreadingHTTPServer((host, port), Handler)
    print("migrate-mail dashboard %s" % __version__)
    print("")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("  CANH BAO: dang lang nghe tren %s, tuc la mo ra ngoai may nay." % host)
        print("  Giao dien nay cham vao mat khau. Nen dung 127.0.0.1 + SSH tunnel.")
        print("")
    else:
        print("  Tao tunnel tu may ban:")
        print("    ssh -L %d:127.0.0.1:%d %s@<vps>" % (port, port, "root"))
        print("")
    print("  Mo dia chi nay (token chi dung mot lan de dat cookie):")
    print("    http://%s:%d/?t=%s" % (host, port, token))
    print("")
    print("  Ctrl-C de dung.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDa dung.")
    finally:
        httpd.server_close()
