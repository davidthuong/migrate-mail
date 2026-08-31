"""Do folder tren server nguon va sinh ke hoach exclude / mapping cho imapsync.

Vi sao khong hardcode ten folder: cung mot hop thu co the goi folder gui di la
"[Gmail]/Sent Mail", "[Gmail]/Thu da gui", "Sent Items", hay "INBOX.Sent" -- tuy
nha cung cap va tuy ngon ngu cua account. Nen thu tu uu tien la:

  1. Co SPECIAL-USE (Sent / Drafts / Trash / Junk / Archive). Gmail, Exchange
     doi moi va Dovecot doi moi deu gan co nay, va no khong doi theo ngon ngu.
  2. Ten folder, doi chieu voi bang trong providers.py. Chi dung khi server
     khong gan co -- Courier, Exchange doi cu, mot so ban Dovecot cu.

Viec phan loai nam trong providers.Provider.classify; file nay lo phan noi
chuyen voi server va rap ket qua thanh mot Plan.
"""

from __future__ import annotations

import imaplib
import re
import socket
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import oauth, providers
from .config import Config, ServerConf, SyncConf
from .imaputf7 import decode as utf7_decode
from .oauth import OAuthError
from .providers import (SPECIAL_ALL, SPECIAL_ARCHIVE, SPECIAL_DRAFTS,
                        SPECIAL_FLAGGED, SPECIAL_IMPORTANT, SPECIAL_JUNK,
                        SPECIAL_SENT, SPECIAL_TRASH, Provider, strip_namespace)
from .users import User

# Regex tach dong tra ve cua LIST: (flags) "delim" name
_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?:"(?P<delim>[^"]*)"|NIL)\s+(?P<name>.*)$')

# Tra ve cua NAMESPACE: (("INBOX." ".")) NIL NIL   hoac   (("" "/")) NIL NIL
_NS_RE = re.compile(rb'^\s*\(\(\s*"(?P<prefix>[^"]*)"\s+(?:"(?P<delim>[^"]*)"|NIL)')

NOSELECT = "noselect"
BACKSLASH = chr(92)

__all__ = [
    "Folder", "Plan", "DiscoveryError", "NOSELECT", "SPECIAL_ALL",
    "SPECIAL_ARCHIVE", "SPECIAL_DRAFTS", "SPECIAL_FLAGGED", "SPECIAL_IMPORTANT",
    "SPECIAL_JUNK", "SPECIAL_SENT", "SPECIAL_TRASH", "build_plan", "check_login",
    "clean_imap_error", "list_folders", "open_connection",
]


@dataclass
class Folder:
    raw: str          # ten IMAP tho -> day chinh la thu imapsync nhin thay
    display: str      # ten da decode, chi de doc
    flags: set        # cac co, viet thuong
    delim: str
    # Tien to namespace cua server ("INBOX."), lay tu lenh NAMESPACE. Chuoi
    # rong voi gan het cac server; Courier va Dovecot kieu Maildir++ thi khong.
    prefix: str = ""

    def has(self, flag: str) -> bool:
        return flag in self.flags


@dataclass
class Plan:
    """Ke hoach chuyen doi folder cho mot mailbox."""
    folders: List[Folder] = field(default_factory=list)
    excluded: List[Tuple[Folder, str]] = field(default_factory=list)   # (folder, ly do)
    mapped: List[Tuple[Folder, str]] = field(default_factory=list)     # (folder, ten dich)
    kept: List[Folder] = field(default_factory=list)                   # giu nguyen ten
    # Folder le ra phai doi ten nhung ten nguon co chua dau '=' -- xem
    # imapsync_args() de biet vi sao khong dien ta duoc.
    unmappable: List[Tuple[Folder, str]] = field(default_factory=list)

    def imapsync_args(self) -> List[str]:
        args: List[str] = []
        for folder, _reason in self.excluded:
            args += ["--exclude", "^%s$" % re.escape(folder.raw)]
        for folder, dest in self.mapped:
            # imapsync tach chuoi nay bang dau '=' (sub split_around_equal),
            # KHONG phai dau ':'. Dung sai dau thi imapsync coi ca cum la mot
            # ten folder, mapping im lang khong co tac dung nao.
            args += ["--f1f2", "%s=%s" % (folder.raw, dest)]
        return args

    def destinations(self) -> "OrderedDict":
        """Ten folder ben dich -> danh sach folder nguon se do vao do."""
        out: "OrderedDict[str, List[Folder]]" = OrderedDict()
        for folder, dest in self.mapped:
            out.setdefault(dest, []).append(folder)
        for folder in self.kept:
            out.setdefault(folder.raw, []).append(folder)
        return out

    def collisions(self) -> List[Tuple[str, List["Folder"]]]:
        """Cac folder dich co nhieu hon mot folder nguon do vao.

        Hay gap khi hop thu nguon truoc day da tung import tu noi khac: ben
        canh folder chuan (co SPECIAL-USE) con mot folder ten "Drafts" sot lai.
        Ca hai deu ra "Drafts" ben dich va bi tron lam mot.
        """
        return [(dest, sources) for dest, sources in self.destinations().items()
                if len(sources) > 1]


class DiscoveryError(Exception):
    pass


def _parse_list_line(line) -> Optional[Folder]:
    # imaplib tra ve bytes, hoac tuple (prefix, literal) khi ten folder la literal {n}
    if isinstance(line, tuple):
        head, literal = line[0], line[1]
        name_bytes = literal
        m = _LIST_RE.match(head + b'""')
    else:
        m = _LIST_RE.match(line)
        name_bytes = None
    if not m:
        return None

    if name_bytes is None:
        raw = m.group("name").strip()
        if raw.startswith(b'"') and raw.endswith(b'"'):
            raw = raw[1:-1]
        name_bytes = raw

    name = name_bytes.decode("ascii", "replace")
    flags = {f.decode("ascii", "replace").lower().lstrip(BACKSLASH)
             for f in m.group("flags").split()}
    delim = (m.group("delim") or b"/").decode("ascii", "replace")
    return Folder(raw=name, display=utf7_decode(name), flags=flags, delim=delim)


def _connect(server: ServerConf, timeout: int):
    if server.ssl:
        return imaplib.IMAP4_SSL(server.host, server.port, timeout=timeout)
    return imaplib.IMAP4(server.host, server.port, timeout=timeout)


class _Xoauth2:
    """Callback cho imaplib.authenticate('XOAUTH2', ...).

    imaplib goi lai callback khi server gui challenge. Voi XOAUTH2, challenge
    thu hai co nghia la server DA tu choi va dang cho mot dong rong de ket
    thuc trao doi -- gui lai token se treo phien.
    """

    def __init__(self, user: str, token: str):
        self.data = oauth.xoauth2(user, token)
        self.sent = False

    def __call__(self, _challenge) -> bytes:
        if self.sent:
            return b""
        self.sent = True
        return self.data


def _login(conn, server: ServerConf, login: str, password: str) -> None:
    """Dang nhap theo dung kieu xac thuc cua dau nay."""
    if server.uses_oauth:
        token = oauth.source_for(server.oauth).token()
        conn.authenticate("XOAUTH2", _Xoauth2(login, token))
        return
    conn.login(login, password)


@dataclass
class Layout:
    """Cach mot server dat ten folder: tien to namespace va dau phan cach."""
    prefix: str = ""
    delim: str = ""

    @property
    def known(self) -> bool:
        return bool(self.prefix or self.delim)


def _namespace(conn) -> Layout:
    """Tien to va dau phan cach cua namespace ca nhan, vd ("INBOX.", ".").

    Doc bang lenh NAMESPACE thay vi doan tu danh sach folder: tren server
    KHONG co tien to, folder "INBOX/Luu tru" that su la con cua INBOX va cat
    di la sai. Server khong ho tro NAMESPACE thi coi nhu khong co tien to.
    """
    try:
        typ, data = conn.namespace()
    except Exception:
        return Layout()
    if typ != "OK" or not data:
        return Layout()
    raw = data[0] if isinstance(data[0], bytes) else bytes(data[0])
    m = _NS_RE.match(raw)
    if not m:
        return Layout()
    delim = m.group("delim")
    return Layout(prefix=m.group("prefix").decode("ascii", "replace"),
                  delim=(delim or b"").decode("ascii", "replace"))


def resolve_layout(server: ServerConf, detected: Layout) -> Layout:
    """Ghep cai do duoc voi cai viet trong config. Config thang."""
    if server.detect_prefix:
        return detected
    return Layout(prefix=server.fixed_prefix, delim=detected.delim)


def server_layout(cfg: Config, user: User, side: str, timeout: int = 60) -> Layout:
    """Dang nhap mot dau chi de doc NAMESPACE. Nem DiscoveryError neu hong."""
    server, login, password = _side(cfg, user, side)
    if not server.detect_prefix:
        return Layout(prefix=server.fixed_prefix)
    try:
        conn = _connect(server, timeout)
    except (socket.error, OSError) as exc:
        raise DiscoveryError("khong ket noi %s (%s:%s): %s"
                             % (server.label, server.host, server.port, exc))
    try:
        _login(conn, server, login, password)
        return _namespace(conn)
    except (imaplib.IMAP4.error, OAuthError) as exc:
        raise DiscoveryError("login %s that bai: %s"
                             % (server.label, clean_imap_error(exc)))
    finally:
        try:
            conn.logout()
        except Exception:
            pass


class DestLayout:
    """Cach dat ten folder cua ben dich, do mot lan roi dung chung ca lan chay.

    Vi sao do mot lan chu khong do tung mailbox: namespace la thuoc tinh cua
    server chu khong phai cua tung hop thu, va mot lan chay 20 mailbox thi 20
    lan dang nhap chi de hoi cung mot cau la phi. Neu do khong duoc thi quay
    ve "khong co tien to" -- dung hanh vi cu -- chu khong chan ca lan chay:
    ben dich hong that thi imapsync se bao, khong can ta chan truoc.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.error = ""
        self._lock = threading.Lock()
        self._value: Optional[Layout] = None

    def get(self, user: User) -> Layout:
        with self._lock:
            if self._value is not None:
                return self._value
            try:
                self._value = server_layout(self.cfg, user, "dest")
            except DiscoveryError as exc:
                self.error = str(exc)
                self._value = Layout()
            return self._value

    def peek(self) -> Optional[Layout]:
        """Cai da do duoc, None neu chua ai hoi toi. Khong ket noi."""
        return self._value


def _side(cfg: Config, user: User, side: str):
    server = cfg.source if side == "source" else cfg.dest
    login = user.src_user if side == "source" else user.dst_user
    password = user.src_password if side == "source" else user.dst_password
    return server, login, password


def list_folders(cfg: Config, user: User, side: str = "source",
                 timeout: int = 60) -> List[Folder]:
    """Dang nhap mot dau va liet ke toan bo folder. side = 'source' | 'dest'."""
    server, login, password = _side(cfg, user, side)
    try:
        conn = _connect(server, timeout)
    except (socket.error, OSError) as exc:
        raise DiscoveryError("khong ket noi duoc %s:%s (%s)"
                             % (server.host, server.port, exc))

    try:
        try:
            _login(conn, server, login, password)
        except imaplib.IMAP4.error as exc:
            raise DiscoveryError("login that bai: %s" % clean_imap_error(exc))
        except OAuthError as exc:
            raise DiscoveryError("khong lay duoc OAuth2 token: %s" % exc)

        prefix = resolve_layout(server, _namespace(conn)).prefix

        typ, data = conn.list()
        if typ != "OK":
            raise DiscoveryError("lenh LIST that bai: %s" % typ)

        folders = []
        for line in data:
            if not line:
                continue
            f = _parse_list_line(line)
            if f:
                f.prefix = prefix
                folders.append(f)
        if not folders:
            raise DiscoveryError("LIST khong tra ve folder nao")
        return folders
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def open_connection(cfg: Config, user: User, side: str, timeout: int = 120):
    """Mo va dang nhap mot dau. side = 'source' | 'dest'. Nem DiscoveryError neu hong."""
    server, login, password = _side(cfg, user, side)
    label = server.label
    try:
        conn = _connect(server, timeout)
    except (socket.error, OSError) as exc:
        raise DiscoveryError("khong ket noi %s (%s:%s): %s"
                             % (label, server.host, server.port, exc))
    try:
        _login(conn, server, login, password)
    except (imaplib.IMAP4.error, OAuthError) as exc:
        try:
            conn.logout()
        except Exception:
            pass
        raise DiscoveryError("login %s that bai: %s" % (label, clean_imap_error(exc)))
    return conn


def check_login(cfg: Config, user: User, side: str, timeout: int = 60) -> Tuple[bool, str]:
    """Thu login mot dau. side = 'source' | 'dest'."""
    server, login, password = _side(cfg, user, side)
    try:
        conn = _connect(server, timeout)
    except (socket.error, OSError) as exc:
        return False, "khong ket noi %s:%s (%s)" % (server.host, server.port, exc)
    try:
        _login(conn, server, login, password)
        return True, "OK"
    except (imaplib.IMAP4.error, OAuthError) as exc:
        return False, clean_imap_error(exc)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def clean_imap_error(exc: Exception) -> str:
    msg = str(exc)
    if msg.startswith("b'") or msg.startswith('b"'):
        msg = msg[2:-1]
    return msg.replace("\n", " ").strip()


def invert_separator(name: str, src_delim: str, dst_delim: str) -> str:
    """Doi dau phan cach cua nguon thanh cua dich, giu nguyen cay thu muc.

    Trao doi hai ky tu chu khong thay the mot chieu, giong sub separator_invert
    cua imapsync: mot dau '.' co san trong ten folder ben nguon (dau phan cach
    la '/') phai thanh '/' ben dich (dau phan cach la '.'), neu khong no se bi
    doc thanh mot cap thu muc moi ma nguoi dung khong he tao.
    """
    if not src_delim or not dst_delim or src_delim == dst_delim:
        return name
    placeholder = "\x00"
    out = name.replace(dst_delim, placeholder)
    out = out.replace(src_delim, dst_delim)
    return out.replace(placeholder, src_delim)


def _with_dest_prefix(name: str, prefix: str) -> str:
    """Them tien to cua ben dich. INBOX khong bao gio duoc them (giong imapsync).

    Ten da mang san tien to thi khong them lan nua: nguoi dung viet
    "sent_folder = INBOX.Sent" trong config phai ra dung cai ho viet, khong
    phai "INBOX.INBOX.Sent".
    """
    if not prefix or name.upper() == "INBOX" or name.startswith(prefix):
        return name
    return prefix + name


def build_plan(folders: List[Folder], sync: SyncConf,
               provider: Optional[Provider] = None,
               prefix: Optional[str] = None,
               dest: Optional[Layout] = None) -> Plan:
    """Phan loai folder nguon thanh: bo qua / doi ten / giu nguyen.

    `dest` la cach ben dich dat ten folder. Phai tinh o day chu khong pho mac
    cho imapsync: imapsync CHI tu them tien to va doi dau phan cach cho nhung
    folder no tu suy ra ten (sub prefix_seperator_invertion). Ten nao di qua
    --f1f2 thi no lay nguyen van -- ma o day gan nhu folder nao cung co --f1f2.
    """
    prov = provider or providers.DEFAULT_SOURCE
    dest = dest or Layout()
    plan = Plan(folders=list(folders))
    if prefix is None:
        prefix = folders[0].prefix if folders else ""

    for f in folders:
        if f.has(NOSELECT):
            # Container thuan tuy nhu "[Gmail]" - khong chua mail, khong the SELECT.
            plan.excluded.append((f, "Noselect - folder container, khong chua mail"))
            continue

        # Folder ao nhan ra bang co, va chi bo khi config cho phep bo.
        virtual = next((fl for fl in prov.virtual_flags if f.has(fl)), None)
        if virtual is not None:
            spec = prov.virtual_flags[virtual]
            if getattr(sync, spec.setting, True):
                plan.excluded.append((f, spec.reason))
                continue

        rel_display = strip_namespace(f.display, prefix)
        rel_raw = strip_namespace(f.raw, prefix)
        kind, value = prov.classify(rel_display, f.flags, f.delim)

        if kind == "skip":
            plan.excluded.append((f, value))
            continue

        if kind == "role" and sync.folder_for(value):
            # Ten viet trong config la ten ben dich roi: chi them tien to,
            # khong dong vao dau phan cach cua no.
            dest_name = _with_dest_prefix(sync.folder_for(value), dest.prefix)
        else:
            # Ten suy ra tu nguon: doi dau phan cach roi moi them tien to,
            # dung thu tu imapsync lam trong prefix_seperator_invertion.
            dest_name = _with_dest_prefix(
                invert_separator(rel_raw, f.delim, dest.delim), dest.prefix)

        if dest_name == f.raw:
            plan.kept.append(f)
        elif "=" in f.raw:
            # --f1f2 dung '=' lam dau phan cach nen khong co cach nao dien ta
            # ten nguon co chua '='. Bao ra thay vi sinh mot mapping hong ma
            # khong ai biet.
            plan.unmappable.append((f, dest_name))
            plan.kept.append(f)
        else:
            plan.mapped.append((f, dest_name))

    return plan
