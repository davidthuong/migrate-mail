# -*- coding: utf-8 -*-
"""Ho so cua tung nha cung cap mail.

Vi sao can lop nay: cung la "keo mail tu server kia ve day", nhung moi nguon
khac nhau o bon diem, va ca bon deu lam hong ket qua neu doan sai:

1. Cach nhan ra folder dac biet. Gmail LUON gan co SPECIAL-USE nen doc duoc
   bang co, khong phu thuoc ngon ngu. Nhung Exchange cu, Courier, va kha nhieu
   ban Dovecot khong quang ba co nao -- o do chi con ten folder de nhin:
   "Sent Items", "Deleted Items", "INBOX.Sent"...
2. Folder khong phai mail. Gmail co All Mail (ban sao cua moi thu), Exchange co
   Outbox va Sync Issues, Zimbra bay ca Contacts/Calendar/Chats ra duong IMAP.
   Chep chung sang la phinh dung luong hoac do rac vao hop thu moi.
3. Cach dang nhap. Microsoft 365 da tat basic auth tren phan lon tenant, phai
   di bang OAuth2; Gmail/Yahoo/Zoho/iCloud bat buoc app password.
4. Han muc. Gmail cat o 2500 MB/ngay/account. Cho khac khong gioi han dung
   luong ma gioi han so ket noi dong thoi -- hai chuyen hoan toan khac nhau,
   va cach xu ly cung khac nhau.

Them mot nguon moi = them mot Provider vao _ALL, khong sua logic o cho khac.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --- vai tro cua folder ---------------------------------------------------- #
ROLE_SENT = "sent"
ROLE_DRAFTS = "drafts"
ROLE_TRASH = "trash"
ROLE_JUNK = "junk"
ROLE_ARCHIVE = "archive"
ROLES = (ROLE_SENT, ROLE_DRAFTS, ROLE_TRASH, ROLE_JUNK, ROLE_ARCHIVE)

# --- cach xac thuc --------------------------------------------------------- #
AUTH_PASSWORD = "password"
AUTH_OAUTH2 = "oauth2"
AUTH_MASTER = "master"

# --- co SPECIAL-USE (da bo backslash dan dau, xem discover._parse_list_line) - #
SPECIAL_ALL = "all"
SPECIAL_IMPORTANT = "important"
SPECIAL_FLAGGED = "flagged"
SPECIAL_SENT = "sent"
SPECIAL_DRAFTS = "drafts"
SPECIAL_TRASH = "trash"
SPECIAL_JUNK = "junk"
SPECIAL_ARCHIVE = "archive"

FLAG_ROLES = {
    SPECIAL_SENT: ROLE_SENT,
    SPECIAL_DRAFTS: ROLE_DRAFTS,
    SPECIAL_TRASH: ROLE_TRASH,
    SPECIAL_JUNK: ROLE_JUNK,
    SPECIAL_ARCHIVE: ROLE_ARCHIVE,
}


def fold(text: str) -> str:
    """Chuan hoa ten folder de so sanh: bo dau, bo ky tu la, ha chu thuong.

    "Sent Items" -> "sentitems", "Junk E-mail" -> "junkemail",
    "Thu da gui" -> "thudagui". Nho vay bang ten ben duoi khong phai liet ke
    tung bien the dau cach / gach ngang / co chu.
    """
    if not text:
        return ""
    # 'd' gach ngang khong tach ra duoc bang NFD nen phai doi tay truoc.
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "".join(c for c in text.lower() if c.isalnum())


def _names(**kw: str) -> Dict[str, str]:
    """{ten_da_fold: vai_tro} tu cach viet cho de doc ben duoi."""
    out: Dict[str, str] = {}
    for role, raw in kw.items():
        for name in raw.split("|"):
            name = name.strip()
            if name:
                out[fold(name)] = role
    return out


# Ten folder dac biet theo tieng Anh + tieng Viet, dung chung cho moi server
# khong quang ba SPECIAL-USE. Chi ap dung cho folder o cap cao nhat (xem
# Provider.classify) de "Luu tru/Sent 2019" khong bi coi la folder Sent.
COMMON_NAMES = _names(
    sent="Sent|Sent Items|Sent Mail|Sent Messages|Outbox Sent|"
         "Thu da gui|Da gui|Muc da gui|Hop thu di",
    drafts="Drafts|Draft|Thu nhap|Nhap|Ban nhap|Thu chua gui",
    trash="Trash|Deleted|Deleted Items|Deleted Messages|"
          "Thung rac|Da xoa|Thu da xoa|Rac",
    junk="Junk|Junk E-mail|Junk Email|Spam|Bulk Mail|Bulk|"
         "Thu rac|Quang cao",
    archive="Archive|Archives|Luu tru",
)


@dataclass(frozen=True)
class Virtual:
    """Folder ao: co that trong LIST nhung khong phai mail rieng."""
    setting: str        # khoa trong [sync] de bat/tat viec bo qua
    reason: str


@dataclass(frozen=True)
class Provider:
    key: str
    name: str                                   # ten hien thi cho nguoi doc
    aliases: Tuple[str, ...] = ()
    host: str = ""                              # de trong = server rieng, phai tu dien
    port: int = 993
    ssl: bool = True
    auth_modes: Tuple[str, ...] = (AUTH_PASSWORD,)

    # Folder ao nhan ra bang co SPECIAL-USE, bo qua theo cau hinh [sync].
    virtual_flags: Dict[str, Virtual] = field(default_factory=dict)
    # Ten folder -> vai tro, dung khi server khong quang ba SPECIAL-USE.
    extra_names: Dict[str, str] = field(default_factory=dict)
    # Bat bang ten chi khi co the tin duoc: xem ghi chu o name_roles().
    name_fallback: bool = True
    # {ten_da_fold: ly do} -- folder khong phai mail, luon bo qua.
    skip_names: Dict[str, str] = field(default_factory=dict)
    # Ten folder mac dinh khi provider nay lam DICH.
    folders: Dict[str, str] = field(default_factory=dict)

    # Han muc tai ve moi ngay cho moi account, tinh bang byte. 0 = khong cong bo.
    daily_limit: int = 0
    daily_limit_note: str = ""
    # So ket noi IMAP dong thoi toi da cho mot account. 0 = khong ro.
    max_connections: int = 0

    # Viec phai lam truoc khi migrate duoc, in ra boi `mm.py providers`.
    prep: Tuple[str, ...] = ()

    def name_roles(self) -> Dict[str, str]:
        out = dict(COMMON_NAMES)
        out.update(self.extra_names)
        return out

    def supports(self, auth: str) -> bool:
        return auth in self.auth_modes

    def folder_default(self, role: str, fallback: str) -> str:
        return self.folders.get(role, fallback)

    def classify(self, rel: str, flags: set, delim: str) -> Tuple[str, str]:
        """Xep mot folder vao mot trong ba nhom.

        `rel` la ten hien thi da cat tien to namespace ("Cong viec/Du an A").
        Tra ve (kind, value):
          ("skip", ly_do)   khong chuyen
          ("role", vai_tro) folder dac biet, ten dich lay tu [sync]
          ("keep", "")      folder thuong, giu ten
        """
        # Bo theo folder cha: "Sync Issues/Conflicts" di theo "Sync Issues".
        head = rel.split(delim)[0] if delim else rel
        reason = self.skip_names.get(fold(head))
        if reason:
            return "skip", reason

        for flag, role in FLAG_ROLES.items():
            if flag in flags:
                return "role", role

        # Chi folder o cap cao nhat moi duoc bat theo ten, neu khong thi
        # "Luu tru/Sent 2019" se bi doi thanh folder Sent.
        if self.name_fallback and (not delim or delim not in rel):
            role = self.name_roles().get(fold(rel))
            if role:
                return "role", role

        return "keep", ""


def strip_namespace(name: str, prefix: str) -> str:
    """Bo tien to namespace: "INBOX.Cong viec" -> "Cong viec".

    Ban than INBOX khong bao gio bi dung toi: no khong bat dau bang "INBOX."
    """
    if prefix and name.startswith(prefix) and len(name) > len(prefix):
        return name[len(prefix):]
    return name


# --------------------------------------------------------------------------- #
# Danh sach nha cung cap
# --------------------------------------------------------------------------- #

GMAIL = Provider(
    key="gmail",
    name="Gmail / Google Workspace",
    aliases=("google", "gsuite", "workspace", "googlemail"),
    host="imap.gmail.com",
    virtual_flags={
        SPECIAL_ALL: Virtual(
            "exclude_all_mail",
            "All Mail - ban sao cua moi mail, copy se nhan doi dung luong"),
        SPECIAL_IMPORTANT: Virtual(
            "exclude_important", "Important - folder ao cua Gmail"),
        SPECIAL_FLAGGED: Virtual(
            "exclude_starred", "Starred - folder ao cua Gmail"),
    },
    # Gmail gan co SPECIAL-USE cho DU cac folder cua no, nen bat theo ten chi
    # tao ra nham lan: mot label ten "Sent Items" con sot lai tu lan import
    # Outlook truoc day khong phai folder Sent, no la label thuong va phai giu
    # nguyen ten. Co la nguon duy nhat dang tin o day.
    name_fallback=False,
    daily_limit=2500 * 1024 * 1024,
    daily_limit_note=(
        "Google cong bo 2500 MB tai ve moi ngay cho MOI account. Gioi han tinh "
        "rieng tung account nen chay nhieu mailbox song song KHONG bi cong don."),
    max_connections=15,
    prep=(
        "Bat xac thuc 2 buoc cho tung account.",
        "Tao App Password 16 ky tu tai myaccount.google.com/apppasswords "
        "va dien vao cot src_password.",
        "Voi Workspace: Admin console > Apps > Gmail > End user access, "
        "bat IMAP cho toan to chuc.",
    ),
)

M365 = Provider(
    key="m365",
    name="Microsoft 365 / Exchange Online",
    aliases=("office365", "o365", "outlook", "exchangeonline", "microsoft365"),
    host="outlook.office365.com",
    auth_modes=(AUTH_OAUTH2, AUTH_PASSWORD),
    extra_names=_names(
        sent="Sent Items", trash="Deleted Items", junk="Junk Email",
        archive="Archive",
    ),
    # Chi liet ke nhung folder Exchange THAT SU bay ra duong IMAP ma khong
    # phai mail. Calendar/Contacts/Tasks/Notes khong hien qua IMAP nen cho
    # chung vao day chang duoc gi, ma lai bo nham mot folder mail that ten
    # "Notes" cua nguoi dung.
    skip_names={
        fold("Outbox"): "Outbox - hang doi gui di, khong phai mail da luu",
        fold("Sync Issues"): "Sync Issues - nhat ky loi dong bo cua Outlook",
        fold("Conversation History"): "Conversation History - lich su chat Teams/Skype",
        fold("RSS Feeds"): "RSS Feeds - noi dung tu website, khong phai mail",
        fold("RSS Subscriptions"): "RSS Subscriptions - noi dung tu website",
    },
    folders={ROLE_JUNK: "Junk Email", ROLE_TRASH: "Deleted Items",
             ROLE_SENT: "Sent Items"},
    daily_limit_note=(
        "Microsoft khong cong bo han muc dung luong theo ngay. Cai chan ban la "
        "so ket noi dong thoi va co che throttling: chay qua nhieu worker se bi "
        "tra ve 'Server Unavailable' chu khong phai bi khoa ca ngay."),
    max_connections=16,
    prep=(
        "Bat IMAP cho tung mailbox: Set-CASMailbox -Identity <user> -ImapEnabled $true",
        "Hau het tenant da tat basic auth -> dat auth = oauth2 trong config.ini.",
        "Voi oauth2: dang ky app tren Entra ID (Azure AD), cap quyen ung dung "
        "IMAP.AccessAsApp cho Office 365 Exchange Online, roi admin consent.",
        "Chay lenh nay mot lan de cho app quyen doc mailbox (thay <appid>):"
        " New-ServicePrincipal -AppId <appid> -ServiceId <objectid>",
    ),
)

EXCHANGE = Provider(
    key="exchange",
    name="Exchange Server (tu dung)",
    aliases=("exchange2016", "exchange2019", "onpremise"),
    extra_names=_names(
        sent="Sent Items", trash="Deleted Items", junk="Junk Email",
        archive="Archive",
    ),
    skip_names=dict(M365.skip_names),
    folders={ROLE_JUNK: "Junk Email", ROLE_TRASH: "Deleted Items",
             ROLE_SENT: "Sent Items"},
    daily_limit_note=(
        "Exchange tu dung khong co han muc dung luong theo ngay. Cai can de y "
        "la throttling policy va so ket noi IMAP dong thoi cua tung mailbox."),
    max_connections=16,
    prep=(
        "Bat dich vu 'Microsoft Exchange IMAP4' va 'IMAP4 Backend' tren server.",
        "Kiem tra throttling policy khong chan IMAP: Get-ThrottlingPolicy.",
        "Neu chung chi TLS la self-signed, dat ssl = false + port 143 trong "
        "mang noi bo, hoac cai chung chi hop le.",
    ),
)

DOVECOT = Provider(
    key="dovecot",
    name="cPanel / DirectAdmin / Plesk (Dovecot)",
    aliases=("cpanel", "directadmin", "plesk", "maildir"),
    auth_modes=(AUTH_PASSWORD, AUTH_MASTER),
    extra_names=_names(junk="spam|Junk"),
    daily_limit_note=(
        "Khong co han muc dung luong theo ngay. Cai chan la "
        "mail_max_userip_connections cua Dovecot (mac dinh 10): vuot qua thi "
        "server tu choi ket noi moi."),
    max_connections=10,
    prep=(
        "Kiem tra Dovecot cho phep du ket noi dong thoi: "
        "mail_max_userip_connections trong /etc/dovecot/conf.d/20-imap.conf.",
        "Neu hosting chan IP la, mo firewall cho IP cua VPS chay tool nay.",
        "Ten dang nhap thuong la dia chi day du user@domain, nhung mot so "
        "hosting dung dang user_domain -- thu bang preflight truoc.",
    ),
)

COURIER = Provider(
    key="courier",
    name="Courier IMAP (hosting doi cu)",
    aliases=("courierimap",),
    extra_names=_names(junk="spam|Junk"),
    daily_limit_note="Khong co han muc theo ngay; gioi han nam o cau hinh server.",
    prep=(
        "Courier de folder duoi tien to INBOX. voi dau phan cach la '.' -- "
        "tool tu cat tien to nay khi dat ten ben dich.",
        "Courier khong quang ba SPECIAL-USE: folder dac biet duoc nhan ra "
        "theo ten, nen chay discover kiem lai truoc khi sync that.",
    ),
)

ZIMBRA = Provider(
    key="zimbra",
    name="Zimbra",
    auth_modes=(AUTH_PASSWORD, AUTH_MASTER),
    extra_names=_names(junk="Junk"),
    skip_names={
        fold("Contacts"): "Contacts - danh ba Zimbra, khong phai mail",
        fold("Emailed Contacts"): "Emailed Contacts - danh ba tu dong cua Zimbra",
        fold("Calendar"): "Calendar - lich Zimbra, khong phai mail",
        fold("Tasks"): "Tasks - cong viec Zimbra, khong phai mail",
        fold("Chats"): "Chats - lich su chat Zimbra, khong phai mail",
        fold("Briefcase"): "Briefcase - file dinh kem Zimbra, khong phai mail",
        fold("Notebook"): "Notebook - wiki Zimbra, khong phai mail",
    },
    folders={ROLE_JUNK: "Junk"},
    daily_limit_note=(
        "Khong co han muc theo ngay. Gioi han nam o zimbraImapMaxConnections "
        "va throttling cua tung COS."),
    prep=(
        "Bat IMAP trong COS: zimbraImapEnabled = TRUE.",
        "Zimbra bay ca Contacts/Calendar/Chats ra duong IMAP -- tool tu bo qua "
        "chung, kiem lai bang discover neu hop thu co folder ten la.",
    ),
)

YAHOO = Provider(
    key="yahoo",
    name="Yahoo Mail",
    host="imap.mail.yahoo.com",
    extra_names=_names(junk="Bulk Mail", drafts="Draft"),
    daily_limit_note="Yahoo khong cong bo han muc; bi bop thi cho roi chay lai.",
    prep=(
        "Bat 'Allow apps that use less secure sign in' hoac tao app password "
        "tai login.yahoo.com/account/security.",
    ),
)

ZOHO = Provider(
    key="zoho",
    name="Zoho Mail",
    host="imap.zoho.com",
    daily_limit_note="Zoho khong cong bo han muc dung luong theo ngay.",
    prep=(
        "Bat IMAP: Zoho Mail > Settings > Mail Accounts > IMAP Access.",
        "Tao app-specific password tai accounts.zoho.com > Security > "
        "App Passwords (bat buoc neu account bat 2FA).",
        "Account o chau Au dung imap.zoho.eu, khong phai imap.zoho.com.",
    ),
)

ICLOUD = Provider(
    key="icloud",
    name="iCloud Mail",
    aliases=("apple", "me"),
    host="imap.mail.me.com",
    extra_names=_names(sent="Sent Messages", trash="Deleted Messages"),
    daily_limit_note="Apple khong cong bo han muc dung luong theo ngay.",
    prep=(
        "Bat xac thuc 2 buoc roi tao app-specific password tai "
        "appleid.apple.com > Sign-In and Security.",
        "Dung dia chi @icloud.com day du lam ten dang nhap.",
    ),
)

ICEWARP = Provider(
    key="icewarp",
    name="IceWarp",
    folders={ROLE_JUNK: "Spam"},
    skip_names={
        fold("Contacts"): "Contacts - folder PIM cua IceWarp, khong phai mail",
        fold("Calendar"): "Calendar - folder PIM cua IceWarp, khong phai mail",
        fold("Tasks"): "Tasks - folder PIM cua IceWarp, khong phai mail",
        fold("Notes"): "Notes - folder PIM cua IceWarp, khong phai mail",
    },
    prep=(
        "Tao san mailbox cho tung user va dat quota du lon.",
        "Kiem tra gioi han kich thuoc mail cua server; neu nguon co mail lon "
        "hon, dat maxsize trong config.ini cho khop.",
        "Ten folder rac cua IceWarp la Spam -- doi junk_folder trong config.ini "
        "neu he thong cua ban dat ten khac.",
    ),
)

IMAP = Provider(
    key="imap",
    name="IMAP chung",
    aliases=("generic", "other", "khac"),
    daily_limit_note="Khong biet han muc cua server nay; theo doi log khi chay.",
    prep=(
        "Chay preflight de chac chan dang nhap duoc, roi discover de nhin ke "
        "hoach folder truoc khi sync that.",
    ),
)

_ALL: Tuple[Provider, ...] = (
    GMAIL, M365, EXCHANGE, DOVECOT, COURIER, ZIMBRA, YAHOO, ZOHO, ICLOUD,
    ICEWARP, IMAP,
)

DEFAULT_SOURCE = GMAIL
DEFAULT_DEST = ICEWARP

_INDEX: Dict[str, Provider] = {}
for _p in _ALL:
    _INDEX[_p.key] = _p
    for _a in _p.aliases:
        _INDEX[_a] = _p


def all_providers() -> List[Provider]:
    return list(_ALL)


def get(key: str, default: Optional[Provider] = None) -> Provider:
    """Tim provider theo ten hoac bi danh. Nem ValueError neu khong co."""
    k = fold(key or "")
    if not k:
        if default is not None:
            return default
        raise ValueError("chua chon provider")
    found = _INDEX.get(k)
    if found is None:
        raise ValueError(
            "khong biet provider %r. Cac gia tri hop le: %s"
            % (key, ", ".join(p.key for p in _ALL)))
    return found
