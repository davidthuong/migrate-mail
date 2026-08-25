"""Do folder tren Gmail va sinh ke hoach exclude / mapping cho imapsync.

Vi sao khong hardcode ten folder: Gmail dat ten folder IMAP theo ngon ngu cua
account. Cung mot hop thu co the la "[Gmail]/Sent Mail", "[Gmail]/Thu da gui"
hay "[Google Mail]/Gesendet". Nhung Gmail LUON gan cac co SPECIAL-USE
(All / Sent / Drafts / Trash / Junk / Important / Flagged) nen ta phan loai
theo co, khong theo ten.
"""

from __future__ import annotations

import imaplib
import re
import socket
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import Config, SyncConf
from .imaputf7 import decode as utf7_decode
from .users import User

# Regex tach dong tra ve cua LIST: (flags) "delim" name
_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?:"(?P<delim>[^"]*)"|NIL)\s+(?P<name>.*)$')

# Ten cac co SPECIAL-USE, da bo dau backslash dan dau (xem _parse_list_line).
# Co tinh khong viet backslash trong source de tranh moi loi escape.
SPECIAL_ALL = "all"
SPECIAL_IMPORTANT = "important"
SPECIAL_FLAGGED = "flagged"
SPECIAL_SENT = "sent"
SPECIAL_DRAFTS = "drafts"
SPECIAL_TRASH = "trash"
SPECIAL_JUNK = "junk"
NOSELECT = "noselect"
BACKSLASH = chr(92)


@dataclass
class Folder:
    raw: str          # ten IMAP tho -> day chinh la thu imapsync nhin thay
    display: str      # ten da decode, chi de doc
    flags: set        # cac co, viet thuong
    delim: str

    def has(self, flag: str) -> bool:
        return flag in self.flags


@dataclass
class Plan:
    """Ke hoach chuyen doi folder cho mot mailbox."""
    folders: List[Folder] = field(default_factory=list)
    excluded: List[Tuple[Folder, str]] = field(default_factory=list)   # (folder, ly do)
    mapped: List[Tuple[Folder, str]] = field(default_factory=list)     # (folder, ten dich)
    kept: List[Folder] = field(default_factory=list)                   # giu nguyen ten

    def imapsync_args(self) -> List[str]:
        args: List[str] = []
        for folder, _reason in self.excluded:
            args += ["--exclude", "^%s$" % re.escape(folder.raw)]
        for folder, dest in self.mapped:
            args += ["--f1f2", "%s:%s" % (folder.raw, dest)]
        return args


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


def _connect(server, timeout: int):
    if server.ssl:
        return imaplib.IMAP4_SSL(server.host, server.port, timeout=timeout)
    return imaplib.IMAP4(server.host, server.port, timeout=timeout)


def list_folders(cfg: Config, user: User, timeout: int = 60) -> List[Folder]:
    """Dang nhap Gmail bang app password va liet ke toan bo folder."""
    try:
        conn = _connect(cfg.source, timeout)
    except (socket.error, OSError) as exc:
        raise DiscoveryError("khong ket noi duoc %s:%s (%s)" % (cfg.source.host, cfg.source.port, exc))

    try:
        try:
            conn.login(user.src_user, user.src_password)
        except imaplib.IMAP4.error as exc:
            raise DiscoveryError("login that bai: %s" % clean_imap_error(exc))

        typ, data = conn.list()
        if typ != "OK":
            raise DiscoveryError("lenh LIST that bai: %s" % typ)

        folders = []
        for line in data:
            if not line:
                continue
            f = _parse_list_line(line)
            if f:
                folders.append(f)
        if not folders:
            raise DiscoveryError("LIST khong tra ve folder nao")
        return folders
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def check_login(cfg: Config, user: User, side: str, timeout: int = 60) -> Tuple[bool, str]:
    """Thu login mot dau. side = 'source' | 'dest'."""
    server = cfg.source if side == "source" else cfg.dest
    login = user.src_user if side == "source" else user.dst_user
    password = user.src_password if side == "source" else user.dst_password
    try:
        conn = _connect(server, timeout)
    except (socket.error, OSError) as exc:
        return False, "khong ket noi %s:%s (%s)" % (server.host, server.port, exc)
    try:
        conn.login(login, password)
        return True, "OK"
    except imaplib.IMAP4.error as exc:
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


def build_plan(folders: List[Folder], sync: SyncConf) -> Plan:
    """Phan loai folder Gmail thanh: bo qua / doi ten / giu nguyen."""
    plan = Plan(folders=list(folders))

    exclude_by_flag: Dict[str, Tuple[bool, str]] = {
        SPECIAL_ALL: (sync.exclude_all_mail,
                      "All Mail - ban sao cua moi mail, copy se nhan doi dung luong"),
        SPECIAL_IMPORTANT: (sync.exclude_important, "Important - folder ao cua Gmail"),
        SPECIAL_FLAGGED: (sync.exclude_starred, "Starred - folder ao cua Gmail"),
    }
    map_by_flag: Dict[str, str] = {
        SPECIAL_SENT: sync.sent_folder,
        SPECIAL_DRAFTS: sync.drafts_folder,
        SPECIAL_TRASH: sync.trash_folder,
        SPECIAL_JUNK: sync.junk_folder,
    }

    for f in folders:
        if f.has(NOSELECT):
            # Container thuan tuy nhu "[Gmail]" - khong chua mail, khong the SELECT.
            plan.excluded.append((f, "Noselect - folder container, khong chua mail"))
            continue

        hit = next((fl for fl in exclude_by_flag if f.has(fl)), None)
        if hit and exclude_by_flag[hit][0]:
            plan.excluded.append((f, exclude_by_flag[hit][1]))
            continue

        hit = next((fl for fl in map_by_flag if f.has(fl)), None)
        if hit:
            dest = map_by_flag[hit]
            if dest and dest != f.raw:
                plan.mapped.append((f, dest))
            else:
                plan.kept.append(f)
            continue

        plan.kept.append(f)

    return plan
