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
import os
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import __version__, cli, report
from .config import Config, load_config
from .hints import diagnose
from . import users as users_module
from .users import User, load_users
from .web_ui import PAGE

MAX_LOG_LINES = 400

ACTIONS = {
    "preflight": "Kiem tra dang nhap",
    "discover": "Xem ke hoach folder",
    "dest": "Xem folder ben dich",
    "sizes": "Do dung luong",
    "folders": "Tao cay folder",
    "dry": "Chay khan",
    "sync": "Chay that",
    "resume": "Chay tiep (bo qua hop da xong)",
    "verify": "Doi chieu ngay thang",
    "doctor": "Kiem tra moi truong",
    "providers": "Nguon duoc ho tro",
    "report": "Xuat bao cao",
    "handover": "Bien ban ban giao",
}

# Tac vu lam viec tren CA cuoc migrate, khong phai tren mailbox duoc chon.
# Giao dien gui only=[] cho chung, va _make_args cung bo qua only -- neu khong
# thi chon vai mailbox roi bam "Xuat bao cao" se ra mot bao cao trong khi nguoi
# bam tuong no da loc theo lua chon.
GLOBAL_ACTIONS = frozenset(["doctor", "providers", "report", "handover"])


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
            # Doc lai config truoc moi job. Nho vay sua config.ini (vd workers)
            # la lan chay sau an ngay, khong phai khoi dong lai server.
            try:
                self.cfg = load_config(self.cfg.path)
            except Exception as exc:
                job.append("Canh bao: khong doc lai duoc config (%s), dung ban cu"
                           % exc)
            args = _make_args(job.action, job.only, self.users_path, self.cfg)
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
        self.sizes = False
        self.workers = 0
        self.since_days = 0
        self.resume = False
        self.dest = False
        self.sample = 200
        self.list = False
        self.all = False
        self.run = ""
        self.out = ""
        self.name = ""          # providers: xem chi tiet mot nha cung cap
        self.customer = ""      # handover: ghi de ten khach hang
        self.__dict__.update(kw)


def _make_args(action: str, only: List[str], users_path: Path,
               cfg: Optional[Config] = None) -> _Args:
    """cfg chi can cho cac tac vu SINH RA FILE (report, handover) -- chung phai
    biet logdir de dat file vao dung cho ma trang tai ve doc duoc. Khong co cfg
    thi chung van chay, chi la khong ghi file.
    """
    args = _Args(only=[] if action in GLOBAL_ACTIONS else list(only),
                 users=str(users_path))
    if action == "dry":
        args.dry = True
    elif action == "folders":
        args.folders_only = True
    elif action == "sizes":
        args.sizes = True
    elif action == "dest":
        args.dest = True
    elif action == "resume":
        # Giong "sync" nhung bo qua mailbox da co state/<mailbox>/done.marker.
        args.resume = True
    elif action == "report":
        # Luon --all. Mot bao cao chi chua mot lan chay thi tren dashboard no
        # gan nhu luon la bao cao sai: nguoi ta bam nut nay sau nhieu dem chay.
        args.all = True
        if cfg is not None:
            args.out = str(Path(cfg.paths.logdir)
                           / ("report-%s.html" % time.strftime("%Y%m%d-%H%M%S")))
    # handover tu dat ten file trong logdir khi args.out rong, nen khong can
    # lam gi o day.
    return args


_ACTION_FN: Dict[str, Callable] = {
    "preflight": lambda a, c: cli.cmd_preflight(a, c),
    "discover": lambda a, c: cli.cmd_discover(a, c),
    "dest": lambda a, c: cli.cmd_discover(a, c),
    "folders": lambda a, c: cli.cmd_sync(a, c),
    "sizes": lambda a, c: cli.cmd_sync(a, c),
    "dry": lambda a, c: cli.cmd_sync(a, c),
    "sync": lambda a, c: cli.cmd_sync(a, c),
    "resume": lambda a, c: cli.cmd_sync(a, c),
    "verify": lambda a, c: cli.cmd_verify(a, c),
    "doctor": lambda a, c: cli.cmd_doctor(a, c),
    "providers": lambda a, c: cli.cmd_providers(a, c),
    "report": lambda a, c: cli.cmd_report(a, c),
    "handover": lambda a, c: cli.cmd_handover(a, c),
}


# --------------------------------------------------------------------------- #
# Doc trang thai
# --------------------------------------------------------------------------- #

def _latest_rows(cfg: Config) -> Dict[str, Dict]:
    """Ket qua sync gan nhat cho tung mailbox, gop tu cac lan chay da luu.

    Logic gop nam trong report.latest_rows de lenh `report --all` dung chung,
    khong de dashboard va CLI bao cao lech nhau nua.
    """
    return report.latest_rows(Path(cfg.paths.statedir) / "runs")


def _mailboxes(cfg: Config, users_path: Path) -> List[Dict]:
    try:
        users = load_users(users_path,
                           need_src_password=cfg.source.needs_mailbox_password,
                           need_dst_password=cfg.dest.needs_mailbox_password)
    except Exception:
        return []
    latest = _latest_rows(cfg)
    done_dir = Path(cfg.paths.statedir)
    preflight = report.load_preflight(done_dir)
    rows = []
    for u in users:
        row = latest.get(u.src_user, {})
        pf = preflight.get(u.src_user) or {}
        rows.append({
            "src_user": u.src_user,
            "dst_user": u.dst_user,
            # Khong bao gio gui mat khau ve trinh duyet, chi bao la co hay khong.
            # Dau nao khong dang nhap bang mat khau cua tung hop thu (OAuth2,
            # master) thi coi nhu du: neu khong, ca danh sach se deo huy hieu
            # "thieu mat khau" trong khi khong ai thieu gi.
            "has_src_password": bool(u.src_password) or not cfg.source.needs_mailbox_password,
            "has_dst_password": bool(u.dst_password) or not cfg.dest.needs_mailbox_password,
            "done": (done_dir / u.slug / "done.marker").exists(),
            "ket_qua": row.get("ket_qua", ""),
            "folder": row.get("folder", ""),
            "mail": row.get("mail_chuyen", ""),
            "dung_luong": row.get("dung_luong", ""),
            "thoi_gian": row.get("thoi_gian", ""),
            "loi": row.get("loi", ""),
            # Dung chung quy tac voi bao cao: dong OK khong co ghi chu
            "ghi_chu": report._note(row) if row else "",
            # Tinh lai tu log chu khong doc goi y da dong bang trong file run:
            # luat chan doan tot len thi bao cao cu phai tu dung theo.
            "goi_y": report.hints_for_row(row) if row else [],
            "mode": row.get("mode", ""),
            "run": row.get("run", ""),
            # Preflight: None neu chua kiem bao gio. Ghi ro hong o DAU nao --
            # "nguon hay dich" la cau dau tien phai tra loi, va imapsync lan
            # tool deu phan biet duoc nen dashboard khong duoc lam mo di.
            "preflight": _preflight_row(pf, cfg) if pf else None,
        })
    return rows


def _preflight_row(pf: Dict, cfg: Config) -> Dict:
    """Mot lan preflight cua mot mailbox, gon lai cho trinh duyet."""
    sides = []
    if not pf.get("src_ok"):
        sides.append(("nguon", cfg.source.provider.name, pf.get("src_msg", "")))
    if not pf.get("dst_ok"):
        sides.append(("dich", cfg.dest.provider.name, pf.get("dst_msg", "")))
    tips = []
    for side, _name, msg in sides:
        for tip in diagnose(msg, limit=2, source=cfg.source.provider.key,
                            dest=cfg.dest.provider.key):
            tips.append("%s: %s" % (side, tip))
    return {
        "ok": not sides,
        "when": pf.get("when", ""),
        # Danh sach chu khong phai chuoi da ghep: ma nguon Python trong repo
        # viet khong dau, con trang thi co dau. Ghep o day thi "dich" khong dau
        # loi thang ra giao dien. De trinh duyet tu doi sang "nguon"/"dich" co
        # dau.
        "hong": [side for side, _n, _m in sides],
        "loi": " | ".join("%s: %s" % (side, msg) for side, _n, msg in sides if msg),
        "goi_y": tips,
    }


# --------------------------------------------------------------------------- #
# Tep trong logs/
# --------------------------------------------------------------------------- #
# Truoc day muon lay bao cao hay log ve may thi phai SCP. Voi bien ban ban
# giao -- thu ma ca muc dich la dua cho khach -- thi bat nguoi ta mo terminal
# moi cam duoc to giay minh vua bam nut sinh ra la vo ly.

MAX_FILES = 60

# Bao cao va bien ban len dau danh sach, log xuong duoi. Moi lan sync sinh ra
# mot file log CHO MOI MAILBOX, nen xep thuan theo thoi gian thi chi mot dem
# chay 200 hop la day het bao cao ra khoi gioi han.
_REPORT_PREFIXES = ("ban-giao-", "report-")


def _file_kind(name: str) -> str:
    return "bao-cao" if name.startswith(_REPORT_PREFIXES) else "log"


def _files(cfg: Config) -> List[Dict]:
    logdir = Path(cfg.paths.logdir)
    try:
        entries = list(os.scandir(str(logdir)))
    except OSError:                      # chua chay lan nao -> chua co logs/
        return []
    rows = []
    for entry in entries:
        try:
            if not entry.is_file():
                continue
            st = entry.stat()
        except OSError:                  # file bien mat giua luc quet
            continue
        rows.append({"name": entry.name, "size": st.st_size,
                     "mtime": st.st_mtime, "kind": _file_kind(entry.name)})
    rows.sort(key=lambda r: (r["kind"] != "bao-cao", -r["mtime"]))
    return rows[:MAX_FILES]


def _safe_log_path(cfg: Config, name: str) -> Optional[Path]:
    """Duong dan that cua mot tep trong logs/, hoac None neu ten khong hop le.

    Kiem tren duong dan DA GIAI chu khong tren chuoi. Loc '..' bang cach doc
    chuoi thi con sot nhieu kieu viet, va mot cho hong o day cho tai ve bat ky
    file nao tren may -- ke ca config.ini, tuc la mat khau cua ca cuoc migrate.
    Symlink tro ra ngoai cung bi chan boi phep so thu muc cha sau khi resolve.

    Chan luon ky tu dieu khien va dau nhay kep: ten file di thang vao header
    Content-Disposition, ma mot ky tu xuong dong trong do la header injection.
    """
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    if '"' in name or any(ord(ch) < 32 for ch in name):
        return None
    logdir = Path(cfg.paths.logdir)
    try:
        base = logdir.resolve()
        path = (logdir / name).resolve()
    except OSError:
        return None
    if path.parent != base or not path.is_file():
        return None
    return path


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

    def _send_file(self, path: Path) -> None:
        """Gui mot tep trong logs/ ve trinh duyet, LUON dang dinh kem.

        Khong bao gio de trinh duyet mo tai cho, ke ca voi file .html. Bao cao
        HTML co chua noi dung lay tu log imapsync; no da duoc escape luc sinh
        ra, nhung mo mot trang HTML o CUNG GOC voi dashboard nghia la chi can
        mot cho escape sot la script trong do chay duoc kem cookie dang nhap.
        Tai ve roi mo tu o dia thi no la mot goc khac, van de bien mat. In ra
        PDF cung phai mo tu o dia, nen cach nay khong bot tien gi.
        """
        try:
            size = path.stat().st_size
            fh = path.open("rb")
        except OSError as exc:
            self._json({"error": "khong doc duoc tep: %s" % exc}, 404)
            return
        with fh:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition",
                             'attachment; filename="%s"' % path.name)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            # Doc theo khuc chu khong nap ca file vao bo nho: log cua mot lan
            # chay 12 tieng co the vai tram MB, va VPS 1GB RAM se chet dung
            # luc nguoi ta can chinh cai log do nhat.
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _authorised(self) -> bool:
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "mmtoken" and secrets.compare_digest(value, self.token):
                return True
        return False

    def _content_length(self) -> int:
        """Do dai body, hoac 0 neu thieu, hong, hoac lon qua muc chap nhan."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return 0
        return length if 0 < length <= 1_000_000 else 0

    def _body(self) -> Dict:
        length = self._content_length()
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _drain(self) -> None:
        """Doc het body roi vut di, khong dong den noi dung.

        Phai goi truoc khi tu choi mot request co body. Neu server dap xong
        roi dong socket trong luc client CON DANG GHI body, thu client nhan
        duoc la connection reset chu khong phai cau tra loi 401 -- no khong
        bao gio doc duoc ly do bi tu choi. Tren dashboard trieu chung la bam
        nut khong thay gi xay ra, thay vi mot dong bao het phien dang nhap.

        Doc chu khong parse: JSON o day chua qua cua xac thuc.
        """
        remaining = self._content_length()
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

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

        if parsed.path == "/api/file":
            path = _safe_log_path(self.manager.cfg,
                                  (query.get("name") or [""])[0])
            if path is None:
                self._json({"error": "khong tim thay tep"}, 404)
                return
            self._send_file(path)
            return

        if parsed.path == "/api/state":
            cfg = self.manager.cfg
            self._json({
                "version": __version__,
                "source": "%s:%d" % (cfg.source.host, cfg.source.port),
                "dest": "%s:%d" % (cfg.dest.host, cfg.dest.port),
                # Giao dien lay ten nha cung cap tu day chu khong viet cung
                # trong HTML: mot ban cai co the chay Gmail -> IceWarp, ban
                # khac chay Microsoft 365 -> Zimbra.
                "source_provider": cfg.source.provider.name,
                "dest_provider": cfg.dest.provider.name,
                "source_auth": cfg.source.auth,
                "dest_auth": cfg.dest.auth,
                "needs_src_password": cfg.source.needs_mailbox_password,
                "needs_dst_password": cfg.dest.needs_mailbox_password,
                "config": str(cfg.path),
                "workers": cfg.sync.workers,
                "users_file": str(self.users_path),
                "actions": ACTIONS,
                "global_actions": sorted(GLOBAL_ACTIONS),
                "logdir": str(cfg.paths.logdir),
                "mailboxes": _mailboxes(cfg, self.users_path),
                "files": _files(cfg),
                "job": self.manager.job.as_dict() if self.manager.job else None,
            })
            return

        self._json({"error": "khong tim thay"}, 404)

    def do_POST(self):                                   # noqa: N802
        if not self._authorised():
            # Doc het body truoc da -- xem _drain(). Chi POST moi can: GET cua
            # dashboard khong mang body bao gio.
            self._drain()
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
                cfg = self.manager.cfg
                added = _add_user(
                    self.users_path, body,
                    need_src_password=cfg.source.needs_mailbox_password,
                    need_dst_password=cfg.dest.needs_mailbox_password)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            self._json({"ok": True, "src_user": added})
            return

        if parsed.path == "/api/users/remove":
            if self.manager.busy():
                self._json({"error": "dang co tac vu chay, cho xong roi hay xoa"}, 409)
                return
            try:
                removed = _remove_user(self.users_path, str(body.get("src_user") or ""))
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            self._json({"ok": True, "src_user": removed})
            return

        self._json({"error": "khong tim thay"}, 404)


def _existing_header(users_path: Path) -> Optional[List[str]]:
    """Ten cot o dong dau cua users.csv, hoac None neu file chua co.

    Phai doc lai chu khong duoc dung COLUMNS: file that hay THIEU cot. Chay
    auth = master hoac oauth2 thi khong ai co mat khau cua tung hop thu, va
    README bao xoa han cot do di -- luc do file chi con ba cot, co khi hai.
    Ghi du bon cot vao mot file ba cot thi moi dong moi deu thua mot truong,
    va ca danh sach hong: `preflight` chet voi "users.csv dong 5 thieu gia tri:
    dst_user". Do thay khi bam "Them vao danh sach" tren dashboard cua rig.
    """
    import csv

    if not users_path.exists() or users_path.stat().st_size == 0:
        return None
    try:
        with users_path.open("r", newline="", encoding="utf-8-sig") as fh:
            for row in csv.reader(fh):
                # Bo dong trong va dong ghi chu, giong load_users
                if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                    continue
                header = [c.strip() for c in row]
                return header if any(c in users_module.COLUMNS for c in header) else None
    except OSError:
        return None
    return None


def _add_user(users_path: Path, body: Dict, need_src_password: bool = True,
              need_dst_password: bool = True) -> str:
    """Them mot dong vao users.csv. Tra ve dia chi nguon vua them."""
    import csv

    fields = _existing_header(users_path) or list(users_module.COLUMNS)
    values = {k: str(body.get(k) or "").strip() for k in users_module.COLUMNS}
    # Dau chay OAuth2 hoac master thi khong ai co mat khau cua tung user; cot
    # van duoc ghi ra cho dung dinh dang file, chi de trong.
    required = users_module.required_columns(need_src_password, need_dst_password)
    missing = [k for k in required if not values[k]]
    if missing:
        raise ValueError("thieu: %s" % ", ".join(missing))
    if "@" not in values["src_user"] or "@" not in values["dst_user"]:
        raise ValueError("dia chi phai co dang user@domain")

    existing = []
    try:
        existing = [u.src_user.lower()
                    for u in load_users(users_path, need_src_password,
                                        need_dst_password)]
    except Exception:
        pass
    if values["src_user"].lower() in existing:
        raise ValueError("%s da co trong danh sach" % values["src_user"])

    # Mot gia tri co that ma cot tuong ung khong co trong file thi im lang mat
    # di. Tha bao ra con hon: nguoi ta vua go mat khau vao mot o ma he thong
    # se vut bo.
    dropped = [k for k in users_module.COLUMNS
               if values[k] and k not in fields]
    if dropped:
        raise ValueError(
            "file %s khong co cot: %s. Them cot do vao dong dau cua file, "
            "hoac de trong o tuong ung." % (users_path.name, ", ".join(dropped)))

    new_file = not users_path.exists() or users_path.stat().st_size == 0
    with users_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields,
                                extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(values)
    try:
        users_path.chmod(0o600)
    except OSError:
        pass
    return values["src_user"]


def _remove_user(users_path: Path, src_user: str) -> str:
    """Xoa mot dong khoi users.csv.

    Sua tren tung dong van ban thay vi doc-roi-ghi-lai bang csv writer, de giu
    nguyen ghi chu va dinh dang ma nguoi dung da viet trong file.

    Chi dong trong users.csv bi xoa. Thu muc state/ va logs/ cua mailbox do
    KHONG bi dung toi -- day la du lieu, khong tu y xoa ho nguoi dung.
    """
    import csv as _csv

    src_user = src_user.strip()
    if not src_user:
        raise ValueError("thieu src_user")
    if not users_path.exists():
        raise ValueError("khong thay %s" % users_path)

    lines = users_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    keep, removed = [], None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            keep.append(line)
            continue
        try:
            fields = next(_csv.reader([stripped]))
        except Exception:
            keep.append(line)
            continue
        if fields and fields[0].strip().lower() == src_user.lower():
            removed = fields[0].strip()
            continue
        keep.append(line)

    if removed is None:
        raise ValueError("%s khong co trong danh sach" % src_user)

    tmp = users_path.with_suffix(users_path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(keep)
    os.replace(str(tmp), str(users_path))
    return removed


def serve(cfg: Config, users_path: Path, host: str = "127.0.0.1",
          port: int = 8765) -> None:
    token = secrets.token_urlsafe(24)
    Handler.manager = JobManager(cfg, Path(users_path))
    Handler.token = token
    Handler.users_path = Path(users_path)

    httpd = ThreadingHTTPServer((host, port), Handler)
    # cli.say chu khong phai print: say() co flush=True. Python gom dem stdout
    # theo khoi khi dau ra khong phai terminal, va khoi chu duoi day chi vai
    # tram byte -- chay bang `nohup ... > web.log` hay systemd thi no nam lai
    # trong dem, va vi server sau do khong in gi nua nen no nam do MAI MAI.
    # Nguoi chay mat token, tuc la mat luon duong vao dashboard cua chinh minh,
    # trong khi server van dang phuc vu binh thuong.
    cli.say("migrate-mail dashboard %s" % __version__)
    cli.say()
    if host not in ("127.0.0.1", "localhost", "::1"):
        cli.say("  CANH BAO: dang lang nghe tren %s, tuc la mo ra ngoai may nay." % host)
        cli.say("  Giao dien nay cham vao mat khau. Nen dung 127.0.0.1 + SSH tunnel.")
        cli.say()
    else:
        cli.say("  Tao tunnel tu may ban:")
        cli.say("    ssh -L %d:127.0.0.1:%d %s@<vps>" % (port, port, "root"))
        cli.say()
    cli.say("  Mo dia chi nay (token chi dung mot lan de dat cookie):")
    cli.say("    http://%s:%d/?t=%s" % (host, port, token))
    cli.say()
    cli.say("  Ctrl-C de dung.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        cli.say()
        cli.say("Da dung.")
    finally:
        httpd.server_close()
