"""Doc config.ini thanh cac dataclass co kieu."""

from __future__ import annotations

import configparser
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import providers
from .oauth import DEFAULT_AUTHORITY, DEFAULT_SCOPE, OAuthConf
from .providers import (AUTH_MASTER, AUTH_OAUTH2, AUTH_PASSWORD, ROLE_ARCHIVE,
                        ROLE_DRAFTS, ROLE_JUNK, ROLE_SENT, ROLE_TRASH,
                        Provider)

PREFIX_AUTO = "auto"
PREFIX_NONE = "none"

# Cach dua tai khoan quan tri len server khi auth = master. Hai kieu nay khac
# nhau o giao thuc chu khong phai o so thich:
#   authzid   : SASL PLAIN gui ba truong "hop_thu \0 quan_tri \0 mat_khau"
#               (RFC 4616). Chuan chung, Dovecot va Zimbra deu hieu.
#   separator : ghep thanh mot ten dang nhap "hop_thu*quan_tri" roi LOGIN nhu
#               binh thuong. Cach rieng cua Dovecot, chi chay khi server co bat
#               auth_master_user_separator -- nhung lai la cach DUY NHAT khi
#               server khong cho SASL PLAIN mang authzid.
MASTER_AUTHZID = "authzid"
MASTER_SEPARATOR = "separator"
MASTER_STYLES = (MASTER_AUTHZID, MASTER_SEPARATOR)
DEFAULT_MASTER_SEPARATOR = "*"


def _unquote(token: str) -> str:
    if len(token) > 1 and token[0] == token[-1] and token[0] in ('"', "'"):
        return token[1:-1]
    return token


@dataclass
class MasterConf:
    """Tai khoan quan tri dung de mo hop thu cua nguoi khac.

    Duoc cho auth = master. Thay vi xin mat khau cua tung mailbox, ta dang nhap
    mot lan bang tai khoan nay va noi voi server "mo giup hop thu X".
    """
    user: str = ""
    password: str = ""
    style: str = MASTER_AUTHZID
    separator: str = DEFAULT_MASTER_SEPARATOR

    def missing(self) -> List[str]:
        return [name for name in ("user", "password")
                if not getattr(self, name).strip()]


@dataclass
class Login:
    """Thong tin that su gui len server de mo MOT hop thu.

    Phai tach khoi User vi voi auth = master khong con quan he mot-doi-mot
    giua hop thu va cap ten/mat khau nua: ten dang nhap co the bi ghep them
    tai khoan quan tri, mat khau la cua quan tri chu khong phai cua hop thu,
    va o kieu authzid thi hai danh tinh di song song trong cung mot lenh.
    """
    user: str                  # ten dang nhap (--user1 cua imapsync)
    password: str
    # Tai khoan XAC THUC, khi khac voi hop thu duoc mo. Rong = dang nhap thang.
    authuser: str = ""

    @property
    def via_authzid(self) -> bool:
        return bool(self.authuser)


@dataclass
class ServerConf:
    host: str
    port: int
    ssl: bool = True
    provider: Provider = providers.IMAP
    # password | oauth2 | master -- xem providers.AUTH_*
    auth: str = AUTH_PASSWORD
    oauth: OAuthConf = field(default_factory=OAuthConf)
    master: MasterConf = field(default_factory=MasterConf)
    # Tien to namespace cua server nay: "auto" (doc bang lenh NAMESPACE),
    # "none" (khong co), hoac mot chuoi co dinh nhu "INBOX.".
    # Ben nguon tien to nay bi CAT khoi ten folder, ben dich no duoc THEM vao.
    prefix: str = PREFIX_AUTO

    @property
    def label(self) -> str:
        return self.provider.name

    @property
    def uses_oauth(self) -> bool:
        return self.auth == AUTH_OAUTH2

    @property
    def uses_master(self) -> bool:
        return self.auth == AUTH_MASTER

    @property
    def needs_mailbox_password(self) -> bool:
        """Co phai lay mat khau cua tung hop thu tu users.csv khong.

        Chi auth = password moi can. OAuth2 di bang token cua ca tenant, master
        di bang mat khau cua mot tai khoan quan tri -- ca hai deu khong ai co
        mat khau cua tung user, va doi cho bang duoc la doi nham.
        """
        return self.auth == AUTH_PASSWORD

    def login_for(self, mailbox: str, password: str) -> Login:
        """Dung thong tin dang nhap de mo `mailbox` o dau nay."""
        if not self.uses_master:
            return Login(user=mailbox, password=password)
        m = self.master
        if m.style == MASTER_SEPARATOR:
            return Login(user=mailbox + m.separator + m.user, password=m.password)
        return Login(user=mailbox, password=m.password, authuser=m.user)

    @property
    def detect_prefix(self) -> bool:
        return self.prefix.strip().lower() == PREFIX_AUTO

    @property
    def fixed_prefix(self) -> str:
        """Tien to viet cung trong config. Rong = khong co, hoac dang de auto."""
        value = self.prefix.strip()
        if value.lower() in (PREFIX_AUTO, PREFIX_NONE, ""):
            return ""
        return value


@dataclass
class SyncConf:
    # So mailbox chay song song. Nguon thuong bop bang thong hoac gioi han so
    # ket noi theo tung account, nen tang workers chi giup khi migrate nhieu
    # user cung luc, khong giup mot user chay nhanh hon.
    workers: int = 3
    timeout: int = 300
    errorsmax: int = 50
    # 0 = khong gioi han. Server dich thuong chan mail qua lon -> dat theo limit.
    maxsize: int = 0
    maxbytespersecond: int = 0

    # Gmail dung "label" chu khong phai folder: All Mail chua ban sao cua moi thu,
    # Important/Starred la folder ao. Copy chung se nhan doi/gap ba dung luong.
    # Chi co tac dung khi nguon la Gmail; provider khac khong co folder ao nay.
    exclude_all_mail: bool = True
    exclude_important: bool = True
    exclude_starred: bool = True

    # Chi bat khi CO copy All Mail. Khi da exclude All Mail thi bat cai nay
    # se lam mat mail nam trong nhieu label.
    skipcrossduplicates: bool = False

    # Ten folder ben dich cho tung vai tro folder dac biet cua nguon.
    sent_folder: str = "Sent"
    drafts_folder: str = "Drafts"
    trash_folder: str = "Trash"
    junk_folder: str = "Spam"
    # De trong = giu nguyen ten folder luu tru cua nguon.
    archive_folder: str = ""

    # Nguon ngay thang gan cho mail ben dich:
    #   internal = INTERNALDATE cua nguon (ngay mail vao hop thu) -- mac dinh
    #   header   = header Date: trong than mail (ngay nguoi gui gui di)
    date_source: str = "internal"

    filterflags: bool = True
    usecache: bool = True
    extra_args: List[str] = field(default_factory=list)

    def folder_for(self, role: str) -> str:
        """Ten folder dich cho mot vai tro. Chuoi rong = giu nguyen ten nguon."""
        return {
            ROLE_SENT: self.sent_folder,
            ROLE_DRAFTS: self.drafts_folder,
            ROLE_TRASH: self.trash_folder,
            ROLE_JUNK: self.junk_folder,
            ROLE_ARCHIVE: self.archive_folder,
        }.get(role, "")


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


def _read_secret_file(path: str, base: Path,
                      key: str = "oauth_client_secret_file") -> str:
    """Doc mot bi mat tu file rieng, de khong phai de no trong config.ini."""
    p = Path(path.strip())
    if not p.is_absolute():
        p = base / p
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("khong doc duoc %s (%s): %s" % (key, p, exc))


def _oauth(cp: configparser.ConfigParser, section: str, base: Path) -> OAuthConf:
    secret = cp.get(section, "oauth_client_secret", fallback="").strip()
    secret_file = cp.get(section, "oauth_client_secret_file", fallback="").strip()
    if secret_file:
        secret = _read_secret_file(secret_file, base)
    return OAuthConf(
        tenant=cp.get(section, "oauth_tenant", fallback="").strip(),
        client_id=cp.get(section, "oauth_client_id", fallback="").strip(),
        client_secret=secret,
        scope=cp.get(section, "oauth_scope", fallback=DEFAULT_SCOPE).strip(),
        authority=cp.get(section, "oauth_authority", fallback=DEFAULT_AUTHORITY).strip(),
    )


def _master(cp: configparser.ConfigParser, section: str, base: Path) -> MasterConf:
    password = cp.get(section, "master_password", fallback="").strip()
    pass_file = cp.get(section, "master_password_file", fallback="").strip()
    if pass_file:
        password = _read_secret_file(pass_file, base, "master_password_file")

    style = cp.get(section, "master_style", fallback=MASTER_AUTHZID).strip().lower()
    if style not in MASTER_STYLES:
        raise ValueError("[%s] master_style phai la mot trong: %s (dang co: %r)"
                         % (section, ", ".join(MASTER_STYLES), style))

    # Dau phan cach hay la mot ky tu configparser giu nguyen nhung mat nhin
    # ("*"), nen cho phep boc trong dau nhay de nguoi dung nhin ro no o dau.
    sep = _unquote(cp.get(section, "master_separator",
                          fallback=DEFAULT_MASTER_SEPARATOR).strip())
    if style == MASTER_SEPARATOR and not sep:
        raise ValueError("[%s] master_separator khong duoc de rong khi "
                         "master_style = separator" % section)

    return MasterConf(
        user=cp.get(section, "master_user", fallback="").strip(),
        password=password,
        style=style,
        separator=sep,
    )


def _auth(cp: configparser.ConfigParser, section: str, provider: Provider) -> str:
    value = cp.get(section, "auth", fallback=AUTH_PASSWORD).strip().lower()
    known = (AUTH_PASSWORD, AUTH_OAUTH2, AUTH_MASTER)
    if value not in known:
        raise ValueError("[%s] auth phai la mot trong: %s (dang co: %r)"
                         % (section, ", ".join(known), value))
    if not provider.supports(value):
        raise ValueError(
            "[%s] provider %s khong dung duoc auth = %s. Cach hop le: %s"
            % (section, provider.key, value, ", ".join(provider.auth_modes)))
    return value


def _server(cp: configparser.ConfigParser, section: str, base: Path,
            default_provider: Provider) -> ServerConf:
    if not cp.has_section(section):
        raise ValueError("config thieu section [%s]" % section)

    provider = providers.get(
        cp.get(section, "provider", fallback=""), default_provider)
    auth = _auth(cp, section, provider)

    host = cp.get(section, "host", fallback=provider.host).strip()
    if not host:
        raise ValueError(
            "[%s] chua dat host. Provider %s la server tu dung nen khong co "
            "dia chi mac dinh." % (section, provider.key))
    ssl = cp.getboolean(section, "ssl", fallback=provider.ssl)
    port = cp.getint(section, "port",
                     fallback=(provider.port if ssl else 143))

    conf = ServerConf(
        host=host, port=port, ssl=ssl, provider=provider, auth=auth,
        oauth=_oauth(cp, section, base),
        master=_master(cp, section, base),
        prefix=cp.get(section, "prefix", fallback=PREFIX_AUTO).strip(),
    )
    if conf.uses_oauth:
        missing = conf.oauth.missing()
        if missing:
            raise ValueError(
                "[%s] auth = oauth2 nhung thieu: %s"
                % (section, ", ".join("oauth_" + m for m in missing)))
    if conf.uses_master:
        missing = conf.master.missing()
        if missing:
            raise ValueError(
                "[%s] auth = master nhung thieu: %s"
                % (section, ", ".join("master_" + m for m in missing)))
    return conf


def _sync(cp: configparser.ConfigParser, dest: Provider) -> SyncConf:
    s = "sync"
    if not cp.has_section(s):
        return SyncConf(
            sent_folder=dest.folder_default(ROLE_SENT, "Sent"),
            drafts_folder=dest.folder_default(ROLE_DRAFTS, "Drafts"),
            trash_folder=dest.folder_default(ROLE_TRASH, "Trash"),
            junk_folder=dest.folder_default(ROLE_JUNK, "Spam"),
        )
    return SyncConf(
        workers=cp.getint(s, "workers", fallback=3),
        timeout=cp.getint(s, "timeout", fallback=300),
        errorsmax=cp.getint(s, "errorsmax", fallback=50),
        maxsize=cp.getint(s, "maxsize", fallback=0),
        maxbytespersecond=cp.getint(s, "maxbytespersecond", fallback=0),
        exclude_all_mail=cp.getboolean(s, "exclude_all_mail", fallback=True),
        exclude_important=cp.getboolean(s, "exclude_important", fallback=True),
        exclude_starred=cp.getboolean(s, "exclude_starred", fallback=True),
        skipcrossduplicates=cp.getboolean(s, "skipcrossduplicates", fallback=False),
        # Khong dat thi lay ten mac dinh cua provider DICH: IceWarp goi folder
        # rac la Spam, Exchange goi la Junk Email, Dovecot goi la Junk.
        sent_folder=cp.get(s, "sent_folder",
                           fallback=dest.folder_default(ROLE_SENT, "Sent")).strip(),
        drafts_folder=cp.get(s, "drafts_folder",
                             fallback=dest.folder_default(ROLE_DRAFTS, "Drafts")).strip(),
        trash_folder=cp.get(s, "trash_folder",
                            fallback=dest.folder_default(ROLE_TRASH, "Trash")).strip(),
        junk_folder=cp.get(s, "junk_folder",
                           fallback=dest.folder_default(ROLE_JUNK, "Spam")).strip(),
        archive_folder=cp.get(s, "archive_folder",
                              fallback=dest.folder_default(ROLE_ARCHIVE, "")).strip(),
        date_source=_date_source(cp.get(s, "date_source", fallback="internal")),
        filterflags=cp.getboolean(s, "filterflags", fallback=True),
        usecache=cp.getboolean(s, "usecache", fallback=True),
        extra_args=shlex.split(cp.get(s, "extra_args", fallback="")),
    )


def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            "khong thay %s -- copy config.example.ini thanh config.ini roi sua" % path
        )
    # interpolation=None: mac dinh configparser coi '%' la cu phap thay the va
    # nem InterpolationSyntaxError khi gap mot dau '%' don doc. Mat khau thi
    # rat hay co '%' -- va loi nem ra khong he nhac den mat khau, nen nguoi
    # dung se di tim o cho khac. File nay khong dung thay the bao gio.
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"),
                                   interpolation=None)
    # utf-8-sig chu khong phai utf-8: Notepad va PowerShell tren Windows ghi
    # them BOM o dau file, va configparser doc BOM do thanh mot phan cua ten
    # section dau tien -> "File contains no section headers".
    cp.read(path, encoding="utf-8-sig")
    base = path.parent

    source = _server(cp, "source", base, providers.DEFAULT_SOURCE)
    dest = _server(cp, "dest", base, providers.DEFAULT_DEST)

    p = "paths"
    paths = Paths(
        imapsync=cp.get(p, "imapsync", fallback="imapsync").strip(),
        logdir=base / cp.get(p, "logdir", fallback="logs").strip(),
        statedir=base / cp.get(p, "statedir", fallback="state").strip(),
    ) if cp.has_section(p) else Paths(logdir=base / "logs", statedir=base / "state")

    return Config(
        source=source,
        dest=dest,
        sync=_sync(cp, dest.provider),
        paths=paths,
        path=path,
    )
