"""Doc config.ini thanh cac dataclass co kieu."""

from __future__ import annotations

import configparser
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _unquote(token: str) -> str:
    if len(token) > 1 and token[0] == token[-1] and token[0] in ('"', "'"):
        return token[1:-1]
    return token


@dataclass
class ServerConf:
    host: str
    port: int
    ssl: bool = True


@dataclass
class SyncConf:
    # So mailbox chay song song. Gmail bop bang thong theo tung account nen
    # tang workers chi giup khi migrate nhieu user cung luc, khong giup 1 user.
    workers: int = 3
    timeout: int = 300
    errorsmax: int = 50
    # 0 = khong gioi han. IceWarp thuong chan mail qua lon -> dat theo limit cua server.
    maxsize: int = 0
    maxbytespersecond: int = 0

    # Gmail dung "label" chu khong phai folder: All Mail chua ban sao cua moi thu,
    # Important/Starred la folder ao. Copy chung se nhan doi/gap ba dung luong.
    exclude_all_mail: bool = True
    exclude_important: bool = True
    exclude_starred: bool = True

    # Chi bat khi CO copy All Mail. Khi da exclude All Mail thi bat cai nay
    # se lam mat mail nam trong nhieu label.
    skipcrossduplicates: bool = False

    # Ten folder dich tren IceWarp cho tung loai special-use cua Gmail.
    sent_folder: str = "Sent"
    drafts_folder: str = "Drafts"
    trash_folder: str = "Trash"
    junk_folder: str = "Spam"

    # Nguon ngay thang gan cho mail ben IceWarp:
    #   internal = INTERNALDATE cua Gmail (ngay mail vao hop thu) -- mac dinh
    #   header   = header Date: trong than mail (ngay nguoi gui gui di)
    date_source: str = "internal"

    filterflags: bool = True
    usecache: bool = True
    extra_args: List[str] = field(default_factory=list)


@dataclass
class Paths:
    # Co the la ten lenh ("imapsync"), duong dan tuyet doi, hoac ca mot dong
    # lenh ("perl /opt/imapsync/imapsync"). Truong hop cuoi huu ich khi
    # imapsync khong duoc dat quyen thuc thi hoac chay qua mot wrapper.
    imapsync: str = "imapsync"
    logdir: Path = Path("logs")
    statedir: Path = Path("state")

    @property
    def imapsync_argv(self) -> List[str]:
        # posix=False tren Windows de khong nuot backslash trong duong dan,
        # nhung che do do giu lai dau nhay nen phai tu go.
        argv = shlex.split(self.imapsync, posix=(os.name != "nt"))
        argv = [_unquote(t) for t in argv]
        return argv or ["imapsync"]

    @property
    def imapsync_exe(self) -> str:
        return self.imapsync_argv[0]


@dataclass
class Config:
    source: ServerConf
    dest: ServerConf
    sync: SyncConf
    paths: Paths
    path: Path


def _date_source(value: str) -> str:
    v = (value or "internal").strip().lower()
    if v not in ("internal", "header"):
        raise ValueError(
            "[sync] date_source phai la 'internal' hoac 'header', dang co: %r" % value)
    return v


def _server(cp: configparser.ConfigParser, section: str, default_host: str = "") -> ServerConf:
    if not cp.has_section(section):
        raise ValueError("config thieu section [%s]" % section)
    host = cp.get(section, "host", fallback=default_host).strip()
    if not host:
        raise ValueError("[%s] chua dat host" % section)
    ssl = cp.getboolean(section, "ssl", fallback=True)
    port = cp.getint(section, "port", fallback=993 if ssl else 143)
    return ServerConf(host=host, port=port, ssl=ssl)


def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            "khong thay %s -- copy config.example.ini thanh config.ini roi sua" % path
        )
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cp.read(path, encoding="utf-8")

    s = "sync"
    sync = SyncConf(
        workers=cp.getint(s, "workers", fallback=3),
        timeout=cp.getint(s, "timeout", fallback=300),
        errorsmax=cp.getint(s, "errorsmax", fallback=50),
        maxsize=cp.getint(s, "maxsize", fallback=0),
        maxbytespersecond=cp.getint(s, "maxbytespersecond", fallback=0),
        exclude_all_mail=cp.getboolean(s, "exclude_all_mail", fallback=True),
        exclude_important=cp.getboolean(s, "exclude_important", fallback=True),
        exclude_starred=cp.getboolean(s, "exclude_starred", fallback=True),
        skipcrossduplicates=cp.getboolean(s, "skipcrossduplicates", fallback=False),
        sent_folder=cp.get(s, "sent_folder", fallback="Sent").strip(),
        drafts_folder=cp.get(s, "drafts_folder", fallback="Drafts").strip(),
        trash_folder=cp.get(s, "trash_folder", fallback="Trash").strip(),
        junk_folder=cp.get(s, "junk_folder", fallback="Spam").strip(),
        date_source=_date_source(cp.get(s, "date_source", fallback="internal")),
        filterflags=cp.getboolean(s, "filterflags", fallback=True),
        usecache=cp.getboolean(s, "usecache", fallback=True),
        extra_args=shlex.split(cp.get(s, "extra_args", fallback="")),
    ) if cp.has_section(s) else SyncConf()

    base = path.parent
    p = "paths"
    paths = Paths(
        imapsync=cp.get(p, "imapsync", fallback="imapsync").strip(),
        logdir=base / cp.get(p, "logdir", fallback="logs").strip(),
        statedir=base / cp.get(p, "statedir", fallback="state").strip(),
    ) if cp.has_section(p) else Paths(logdir=base / "logs", statedir=base / "state")

    return Config(
        source=_server(cp, "source", "imap.gmail.com"),
        dest=_server(cp, "dest"),
        sync=sync,
        paths=paths,
        path=path,
    )
