# -*- coding: utf-8 -*-
"""Doc log imapsync roi dich cac loi hay gap thanh viec can lam.

imapsync bao loi bang ngon ngu cua giao thuc IMAP ("NO [OVERQUOTA]",
"AUTHENTICATIONFAILED"...). Module nay chi lam mot viec: nhan dang cac mau
loi thuong gap khi di tu Gmail sang IceWarp va noi ro phai xu ly the nao.

Hai cai bay khi doc log imapsync, ca hai deu tung lam module nay bao sai:

1. imapsync in ra thong so cua chinh no o dau log ("imap connection timeout
   is 300 seconds") va echo lai ca dong lenh (co --timeout 300). Bat chu
   "timeout" tren toan bo log se dinh may dong nay o MOI lan chay.
2. Khoi thong ke cuoi log luon co dong "Average bandwidth rate". Bat chu
   "bandwidth" se bao "Gmail chan vi bang thong" cho ca nhung lan that bai
   vi ly do hoan toan khac.

Nen: khop theo TUNG DONG (khong phai toan bo log), va nhung luat de dinh
nham thi khai bao them `unless` -- mau lam cho dong do khong duoc tinh.

Cac mau duoi day co tinh de rong. Neu mot mau khong khop, tool van chay
binh thuong -- chi la khong co goi y kem theo.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Optional


class _Rule(NamedTuple):
    prio: int                        # nho hon = quan trong hon, hien truoc
    pattern: "re.Pattern"            # dong nao khop mau nay thi tinh la trung
    unless: Optional["re.Pattern"]   # ... tru khi dong do khop them mau nay
    tip: str


def _rule(prio: int, pattern: str, tip: str, unless: str = "") -> _Rule:
    return _Rule(prio, re.compile(pattern, re.I),
                 re.compile(unless, re.I) if unless else None, tip)


_RULES: List[_Rule] = [
    # "Account exceeded command or bandwidth limits" -- day la Gmail (host1)
    # chan, khong phai loi cua IceWarp. Chu "bandwidth" tran khong dung duoc
    # vi dong thong ke "Average bandwidth rate" co trong moi log.
    _rule(10, r"bandwidth limit|\[LIMIT\]|exceeded command or bandwidth",
          "Gmail da chan account nay vi vuot han muc IMAP. Google cong bo "
          "2500 MB/ngay, nhung thuc te account Workspace thuong duoc qua "
          "nhieu hon han -- dung lay con so do ra tinh lich chay. Khoa "
          "thuong keo dai 1-24 gio. Cho reset roi chay lai cung lenh sync, "
          "mail da chuyen se khong bi chep lai; hop thu lon thi lap lai vai "
          "ngay cho den khi het.",
          unless=r"average bandwidth rate"),

    _rule(10, r"too many simultaneous connections|\[ALERT\].*too many",
          "Gmail chi cho mot account mo toi da 15 ket noi IMAP cung luc. Giam "
          "workers trong config.ini, hoac dung sync bot dang chay song song."),

    _rule(15, r"application-specific password required",
          "Account nay dang bat xac thuc 2 buoc nen phai dung App Password 16 ky tu, "
          "khong dung duoc mat khau dang nhap. Tao tai myaccount.google.com/apppasswords"),

    _rule(15, r"web login required|please log in via your web browser",
          "Google chan dang nhap tu ung dung. Dung App Password thay cho mat khau "
          "thuong; neu van bi, dang nhap Gmail bang trinh duyet mot lan roi thu lai."),

    _rule(15, r"authenticationfailed|invalid credentials|login failed|"
              r"authentication fail",
          "Sai thong tin dang nhap. Kiem tra lai cot mat khau trong users.csv: phia "
          "Gmail phai la App Password, phia IceWarp phai la dia chi day du user@domain."),

    # OVERQUOTA co the den tu ca hai dau. Ben dich day thi loi nam o buoc ghi
    # (append); con "could not be fetched" la doc tu Gmail, tuc han muc cua
    # Gmail -- viec do da co luat uu tien 10 o tren lo.
    _rule(20, r"overquota|quota exceeded",
          "Hop thu dich tren IceWarp da day. Tang quota cho user do trong IceWarp "
          "Admin roi chay lai sync.",
          unless=r"could not be fetched|bandwidth|host1"),

    _rule(20, r"message (is )?too (big|large)|size exceeds|exceeded the size",
          "Co mail lon hon gioi han cua IceWarp. Hoac tang gioi han kich thuoc mail "
          "tren IceWarp, hoac dat maxsize trong config.ini de bo qua nhung mail do "
          "(chung se KHONG duoc chuyen)."),

    # imapsync tra ma 115 (EXIT_ERR_FETCH) khi co BAT KY mail nao doc khong
    # duoc, ke ca 1 mail tren 16.000 -- nen ma thoat khong noi len muc do. Con
    # so quyet dinh nam o dong "there are N among M identified messages".
    #
    # Chi bat dong "could not be fetched" cua tung mail, KHONG bat dong tom tat
    # "The most frequent error is ERR_Host1_FETCH": dong tom tat do xuat hien
    # ca khi loi fetch chi la hau qua cua viec bi Gmail bop, va khi do luat uu
    # tien 10 moi la cau tra loi dung.
    _rule(22, r"could not be fetched",
          "Gmail tra ve rong (literal {0}) khi doc mot so mail. Day thuong la "
          "mail hong san ben Gmail, chay lai bao nhieu lan cung khong lay duoc. "
          "imapsync bao that bai ke ca khi chi hong dung 1 mail, nen dung nhin "
          "ma loi ma nhin dong 'there are N among M identified messages' o cuoi "
          "log: N nho thi hop thu coi nhu da xong. Tim tung mail do trong Gmail "
          "theo ngay o dong 'Err ...' roi xu ly tay, sau do danh dau hop thu la "
          "xong bang: touch state/<mailbox>/done.marker",
          unless=r"exceeded command or bandwidth"),

    _rule(25, r"trycreate|can't create folder|create failed",
          "Khong tao duoc folder ben IceWarp. Thuong do ten folder chua ky tu ma "
          "IceWarp khong nhan, hoac trung ten voi folder PIM (Contacts, Calendar, "
          "Tasks, Notes). Xem ./mm.py discover de biet folder nao, roi dat ten khac "
          "qua extra_args voi --regextrans2."),

    _rule(30, r"connection refused|no route to host|network is unreachable",
          "Khong ket noi duoc toi server. Kiem tra firewall cua VPS va cong 993 cua "
          "IceWarp co mo ra ngoai khong."),

    _rule(30, r"certificate verify failed|ssl.*handshake|hostname.*doesn't match",
          "Chung chi TLS cua IceWarp khong hop le hoac khong khop ten mien. Sua cho "
          "dung ten mien trong config.ini, hoac gia han chung chi tren IceWarp."),

    # Bo qua banner dau log ("imap connection timeout is 300 seconds") va dong
    # imapsync tu echo lai tham so --timeout.
    _rule(35, r"timeout|timed out",
          "Het thoi gian cho. Tang timeout trong config.ini, va giam workers neu "
          "duong truyen toi IceWarp dang qua tai.",
          unless=r"--timeout|timeout is \d+ second"),

    _rule(40, r"can't locate .*\.pm in \@inc",
          "Thieu module Perl cho imapsync. Chay lai ./install.sh, hoac cai thu cong "
          "module duoc nhac ten trong dong loi bang: cpanm <Ten::Module>"),
]


def diagnose(text: str, limit: int = 3) -> List[str]:
    """Tra ve toi da `limit` goi y, sap theo do quan trong."""
    if not text:
        return []
    lines = text.splitlines()
    hits = []
    for rule in _RULES:
        for line in lines:
            if rule.pattern.search(line):
                if rule.unless and rule.unless.search(line):
                    continue          # dong nay la nhieu, thu dong khac
                hits.append((rule.prio, rule.tip))
                break
    hits.sort(key=lambda x: x[0])
    out: List[str] = []
    for _prio, tip in hits:
        if tip not in out:
            out.append(tip)
        if len(out) >= limit:
            break
    return out
