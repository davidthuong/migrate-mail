# -*- coding: utf-8 -*-
"""Doc log imapsync roi dich cac loi hay gap thanh viec can lam.

imapsync bao loi bang ngon ngu cua giao thuc IMAP ("NO [OVERQUOTA]",
"AUTHENTICATIONFAILED"...). Module nay chi lam mot viec: nhan dang cac mau loi
thuong gap roi noi ro phai xu ly the nao.

Moi luat co pham vi (`scope`): luat khong ghi pham vi thi dung cho moi nguon,
con luat ghi pham vi chi bat khi dung provider do. Ly do phai chia: cau
"dung App Password 16 ky tu cua Google" la loi khuyen dung khi nguon la Gmail
va la loi khuyen sai -- lam mat thoi gian cua nguoi dang xu ly su co -- khi
nguon la Zimbra hay cPanel. Khi khong biet provider (vd doc lai log cu), tat
ca luat deu duoc xet.

Hai cai bay khi doc log imapsync, ca hai deu tung lam module nay bao sai:

1. imapsync in ra thong so cua chinh no o dau log ("imap connection timeout
   is 300 seconds") va echo lai ca dong lenh (co --timeout 300). Bat chu
   "timeout" tren toan bo log se dinh may dong nay o MOI lan chay.
2. Khoi thong ke cuoi log luon co dong "Average bandwidth rate". Bat chu
   "bandwidth" se bao "bi chan vi bang thong" cho ca nhung lan that bai vi ly
   do hoan toan khac.

Nen: khop theo TUNG DONG (khong phai toan bo log), va nhung luat de dinh nham
thi khai bao them `unless` -- mau lam cho dong do khong duoc tinh.

Cac mau duoi day co tinh de rong. Neu mot mau khong khop, tool van chay binh
thuong -- chi la khong co goi y kem theo.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Optional, Tuple

from . import providers

SOURCE = "source"
DEST = "dest"


class _Rule(NamedTuple):
    prio: int                        # nho hon = quan trong hon, hien truoc
    pattern: "re.Pattern"            # dong nao khop mau nay thi tinh la trung
    unless: Optional["re.Pattern"]   # ... tru khi dong do khop them mau nay
    tip: str                         # co the chua %(nguon)s / %(dich)s
    scope: Tuple[str, ...]           # rong = moi provider
    side: str                        # doi chieu scope voi dau nao
    # Cac luat cung "ho" noi ve cung mot van de, chi ban ban nhat duoc hien.
    # Nho vay luat rieng cua provider thay the duoc luat chung thay vi hien ca
    # hai, va khi khong biet provider thi khong bi ngap goi y trung y.
    family: str


def _rule(prio: int, pattern: str, tip: str, unless: str = "",
          scope: Tuple[str, ...] = (), side: str = SOURCE,
          family: str = "") -> _Rule:
    return _Rule(prio, re.compile(pattern, re.I),
                 re.compile(unless, re.I) if unless else None, tip, scope, side,
                 family)


# --------------------------------------------------------------------------- #
# Han muc va throttling -- rieng cho tung nha cung cap
# --------------------------------------------------------------------------- #
_LIMIT_RULES = [
    # "Account exceeded command or bandwidth limits" -- day la nguon chan,
    # khong phai loi cua server dich. Chu "bandwidth" tran khong dung duoc vi
    # dong thong ke "Average bandwidth rate" co trong moi log.
    _rule(10, r"bandwidth limit|\[LIMIT\]|exceeded command or bandwidth",
          "Gmail da chan account nay vi vuot han muc IMAP. Google cong bo "
          "2500 MB/ngay, nhung thuc te account Workspace thuong duoc qua "
          "nhieu hon han -- dung lay con so do ra tinh lich chay. Khoa "
          "thuong keo dai 1-24 gio. Cho reset roi chay lai cung lenh sync, "
          "mail da chuyen se khong bi chep lai; hop thu lon thi lap lai vai "
          "ngay cho den khi het.",
          unless=r"average bandwidth rate", scope=("gmail",), family="limit"),

    _rule(10, r"too many simultaneous connections|\[ALERT\].*too many",
          "Gmail chi cho mot account mo toi da 15 ket noi IMAP cung luc. Giam "
          "workers trong config.ini, hoac dung sync bot dang chay song song.",
          scope=("gmail",), family="limit"),

    _rule(10, r"server unavailable|\[SERVERBUG\]|request is throttled|"
              r"resource temporarily unavailable",
          "Microsoft 365 dang throttle account nay. Day khong phai han muc "
          "theo ngay nhu Gmail: giam workers trong config.ini xuong 2-3 roi "
          "chay lai la duoc, khong phai cho qua ngay.",
          scope=("m365", "exchange"), family="limit"),

    _rule(10, r"maximum number of connections|too many connections|"
              r"connection limit",
          "Server nguon tu choi vi qua nhieu ket noi cung luc tu mot IP "
          "(Dovecot: mail_max_userip_connections, mac dinh 10). Giam workers "
          "trong config.ini, hoac nang gioi han do tren server nguon.",
          scope=("dovecot", "courier", "zimbra", "imap"), family="limit"),
]

# --------------------------------------------------------------------------- #
# Xac thuc
# --------------------------------------------------------------------------- #
_AUTH_RULES = [
    _rule(13, r"application-specific password required",
          "Account nay dang bat xac thuc 2 buoc nen phai dung App Password 16 "
          "ky tu, khong dung duoc mat khau dang nhap. Tao tai "
          "myaccount.google.com/apppasswords",
          scope=("gmail",), family="auth"),

    _rule(13, r"web login required|please log in via your web browser",
          "Google chan dang nhap tu ung dung. Dung App Password thay cho mat "
          "khau thuong; neu van bi, dang nhap Gmail bang trinh duyet mot lan "
          "roi thu lai.",
          scope=("gmail",), family="auth"),

    _rule(13, r"basic auth(entication)?( is)? (disabled|blocked|not supported)|"
              r"authentication failed.*basic|\bAADSTS50126\b",
          "Tenant Microsoft 365 nay da tat basic auth, khong dang nhap bang "
          "mat khau duoc nua. Dat auth = oauth2 trong [source] cua config.ini "
          "va khai bao oauth_tenant / oauth_client_id / oauth_client_secret.",
          scope=("m365",), family="auth"),

    _rule(13, r"\bAADSTS\d+\b",
          "Microsoft tu choi cap token. Doc ma AADSTS trong dong loi: "
          "AADSTS7000215 = client_secret sai hoac da het han; AADSTS700016 = "
          "client_id khong ton tai trong tenant do; AADSTS900023 = sai "
          "oauth_tenant. Sua trong config.ini roi chay lai doctor.",
          scope=("m365",), family="auth"),

    _rule(13, r"authenticate failed|xoauth2|invalid_token|invalid_grant",
          "Token lay duoc nhung Exchange tu choi. Hai nguyen nhan hay gap: "
          "(a) chua chay New-ServicePrincipal cho app tren Exchange Online "
          "PowerShell, (b) chua cap quyen ung dung IMAP.AccessAsApp va admin "
          "consent cho app do trong Entra ID.",
          scope=("m365",), family="auth"),

    _rule(13, r"imap.*(is )?(disabled|not enabled)|"
              r"(disabled|not enabled).*imap",
          "IMAP dang tat cho mailbox nay. Microsoft 365: "
          "Set-CASMailbox -Identity <user> -ImapEnabled $true. "
          "Zimbra: bat zimbraImapEnabled trong COS.",
          scope=("m365", "exchange", "zimbra"), family="auth"),

    _rule(13, r"authenticationfailed|invalid credentials|login failed",
          "Sai thong tin dang nhap. Nhung nha cung cap nay bat buoc dung "
          "app-specific password chu khong phai mat khau dang nhap thuong -- "
          "tao trong phan bao mat cua account roi dan vao cot src_password.",
          scope=("yahoo", "zoho", "icloud"), family="auth"),

    _rule(15, r"authenticationfailed|invalid credentials|login failed|"
              r"authentication fail",
          "Sai thong tin dang nhap. Kiem tra lai users.csv: phia nguon (%(nguon)s) "
          "va phia dich (%(dich)s) deu phai la dia chi day du user@domain, tru "
          "khi nha cung cap quy dinh khac. Chay preflight de biet dau nao hong.",
          family="auth"),
]

# --------------------------------------------------------------------------- #
# Ghi vao dich, doc tu nguon, ha tang
# --------------------------------------------------------------------------- #
_COMMON_RULES = [
    # OVERQUOTA co the den tu ca hai dau. Ben dich day thi loi nam o buoc ghi
    # (append); con "could not be fetched" la doc tu nguon, tuc han muc cua
    # nguon -- viec do da co cac luat uu tien 10 o tren lo.
    _rule(20, r"overquota|quota exceeded",
          "Hop thu dich tren %(dich)s da day. Tang quota cho user do roi chay "
          "lai sync.",
          unless=r"could not be fetched|bandwidth|host1"),

    _rule(20, r"message (is )?too (big|large)|size exceeds|exceeded the size",
          "Co mail lon hon gioi han cua %(dich)s. Hoac tang gioi han kich thuoc "
          "mail tren server dich, hoac dat maxsize trong config.ini de bo qua "
          "nhung mail do (chung se KHONG duoc chuyen)."),

    # imapsync tra ma 115 (EXIT_ERR_FETCH) khi co BAT KY mail nao doc khong
    # duoc, ke ca 1 mail tren 16.000 -- nen ma thoat khong noi len muc do. Con
    # so quyet dinh nam o dong "there are N among M identified messages".
    #
    # Chi bat dong "could not be fetched" cua tung mail, KHONG bat dong tom tat
    # "The most frequent error is ERR_Host1_FETCH": dong tom tat do xuat hien
    # ca khi loi fetch chi la hau qua cua viec bi bop bang thong, va khi do
    # luat uu tien 10 moi la cau tra loi dung.
    _rule(22, r"could not be fetched",
          "%(nguon)s tra ve rong (literal {0}) khi doc mot so mail. Day thuong "
          "la mail da hong san ben nguon, chay lai bao nhieu lan cung khong lay "
          "duoc. imapsync bao that bai ke ca khi chi hong dung 1 mail, nen dung "
          "nhin ma loi ma nhin dong 'there are N among M identified messages' o "
          "cuoi log: N nho thi hop thu coi nhu da xong. Tim tung mail do theo "
          "ngay o dong 'Err ...' roi xu ly tay, sau do danh dau hop thu la xong "
          "bang: touch state/<mailbox>/done.marker",
          unless=r"exceeded command or bandwidth"),

    _rule(24, r"trycreate|can't create folder|create failed",
          "Khong tao duoc folder ben IceWarp. Thuong do ten folder trung voi "
          "folder PIM co san (Contacts, Calendar, Tasks, Notes) hoac chua ky tu "
          "IceWarp khong nhan. Xem ./mm.py discover de biet folder nao, roi dat "
          "ten khac qua extra_args voi --regextrans2.",
          scope=("icewarp",), side=DEST, family="create"),

    _rule(25, r"trycreate|can't create folder|create failed",
          "Khong tao duoc folder ben %(dich)s. Thuong do ten folder chua ky tu "
          "server dich khong nhan, hoac trung ten voi folder he thong. Xem "
          "./mm.py discover --dest de doi chieu, roi dat ten khac qua extra_args "
          "voi --regextrans2.", family="create"),

    _rule(30, r"connection refused|no route to host|network is unreachable",
          "Khong ket noi duoc toi server. Kiem tra firewall cua VPS, va cong "
          "IMAP cua ca hai dau co mo cho IP nay khong."),

    _rule(30, r"certificate verify failed|ssl.*handshake|hostname.*doesn't match",
          "Chung chi TLS khong hop le hoac khong khop ten mien. Sua cho dung "
          "ten mien trong config.ini, gia han chung chi, hoac -- neu la server "
          "noi bo -- dat ssl = false va port 143 trong mang kin."),

    # Bo qua banner dau log ("imap connection timeout is 300 seconds") va dong
    # imapsync tu echo lai tham so --timeout.
    _rule(35, r"timeout|timed out",
          "Het thoi gian cho. Tang timeout trong config.ini, va giam workers neu "
          "duong truyen dang qua tai.",
          unless=r"--timeout|timeout is \d+ second"),

    _rule(40, r"can't locate .*\.pm in \@inc",
          "Thieu module Perl cho imapsync. Chay lai ./install.sh, hoac cai thu "
          "cong module duoc nhac ten trong dong loi bang: cpanm <Ten::Module>"),

    _rule(40, r"unknown option|unrecognized option",
          "Ban imapsync dang cai khong biet mot tuy chon tool nay dung. Chay "
          "./mm.py doctor de biet tuy chon nao, roi nang cap imapsync."),
]

_RULES: List[_Rule] = _LIMIT_RULES + _AUTH_RULES + _COMMON_RULES


def _label(key: Optional[str], fallback: str) -> str:
    if not key:
        return fallback
    try:
        return providers.get(key).name
    except ValueError:
        return fallback


def _fill(tip: str, names: dict) -> str:
    """Thay %(nguon)s / %(dich)s. Tip co dau % la loi viet luat, khong duoc
    phep lam hong ca phan chan doan -- nen tra ve nguyen van thay vi nem."""
    try:
        return tip % names
    except (KeyError, TypeError, ValueError):
        return tip


def _applies(rule: _Rule, source: Optional[str], dest: Optional[str]) -> bool:
    if not rule.scope:
        return True
    who = source if rule.side == SOURCE else dest
    # Khong biet provider (vd tinh lai goi y tu mot log cu) thi xet het: tha
    # thua mot goi y con hon giau mat cai duy nhat dung.
    if who is None:
        return True
    return who in rule.scope


def _demoted(rule: _Rule, source: Optional[str], dest: Optional[str]) -> int:
    """1 neu day la luat rieng cua mot provider ma ta lai khong biet provider.

    Khi do trong cung mot 'ho', loi khuyen chung phai duoc hien truoc: bao
    "dung app-specific password" cho mot log khong ro tu dau la doan mo, con
    "kiem tra lai users.csv" thi luon dung.
    """
    if not rule.scope:
        return 0
    who = source if rule.side == SOURCE else dest
    return 1 if who is None else 0


def diagnose(text: str, limit: int = 3, source: Optional[str] = None,
             dest: Optional[str] = None) -> List[str]:
    """Tra ve toi da `limit` goi y, sap theo do quan trong.

    `source` / `dest` la khoa provider (providers.Provider.key). De None khi
    khong biet -- moi luat se duoc xet.
    """
    if not text:
        return []
    names = {"nguon": _label(source, "server nguon"),
             "dich": _label(dest, "server dich")}
    lines = text.splitlines()
    hits = []
    for rule in _RULES:
        if not _applies(rule, source, dest):
            continue
        for line in lines:
            if rule.pattern.search(line):
                if rule.unless and rule.unless.search(line):
                    continue          # dong nay la nhieu, thu dong khac
                hits.append((_demoted(rule, source, dest), rule.prio,
                             _fill(rule.tip, names), rule.family))
                break

    # Trong mot 'ho' chi giu mot goi y: ban dung provider truoc, roi den ban
    # quan trong hon. Viec chon nay tach khoi thu tu hien ra ben duoi -- mot
    # goi y chung ve dang nhap khong duoc phep vi the ma nhay len tren mot
    # goi y ve han muc.
    best: dict = {}
    loose = []
    for demote, prio, tip, family in hits:
        if not family:
            loose.append((prio, tip))
            continue
        current = best.get(family)
        if current is None or (demote, prio) < (current[0], current[1]):
            best[family] = (demote, prio, tip)

    ranked = loose + [(prio, tip) for _d, prio, tip in best.values()]
    ranked.sort(key=lambda x: x[0])

    out: List[str] = []
    for _prio, tip in ranked:
        if tip not in out:
            out.append(tip)
        if len(out) >= limit:
            break
    return out
