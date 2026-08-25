# -*- coding: utf-8 -*-
"""Doc log imapsync roi dich cac loi hay gap thanh viec can lam.

imapsync bao loi bang ngon ngu cua giao thuc IMAP ("NO [OVERQUOTA]",
"AUTHENTICATIONFAILED"...). Module nay chi lam mot viec: nhan dang cac mau
loi thuong gap khi di tu Gmail sang IceWarp va noi ro phai xu ly the nao.

Cac mau duoi day co tinh de rong. Neu mot mau khong khop, tool van chay
binh thuong -- chi la khong co goi y kem theo.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# (do uu tien, mau, goi y). Do uu tien nho hon = quan trong hon, hien truoc.
_RULES: List[Tuple[int, "re.Pattern", str]] = [
    (10, re.compile(r"bandwidth|\[LIMIT\]", re.I),
     "Gmail da chan vi vuot gioi han bang thong IMAP (2500 MB/ngay cho moi "
     "account). Khoa thuong keo dai 1-24 gio. Cho reset roi chay lai lenh sync "
     "-- mail da chuyen se khong bi chep lai. Voi hop thu lon hon 2.5 GB, phai "
     "chia lam nhieu ngay."),

    (10, re.compile(r"too many simultaneous connections|\[ALERT\].*too many", re.I),
     "Gmail chi cho mot account mo toi da 15 ket noi IMAP cung luc. Giam "
     "workers trong config.ini, hoac dung sync bot dang chay song song."),

    (15, re.compile(r"application-specific password required", re.I),
     "Account nay dang bat xac thuc 2 buoc nen phai dung App Password 16 ky tu, "
     "khong dung duoc mat khau dang nhap. Tao tai myaccount.google.com/apppasswords"),

    (15, re.compile(r"web login required|please log in via your web browser", re.I),
     "Google chan dang nhap tu ung dung. Dung App Password thay cho mat khau "
     "thuong; neu van bi, dang nhap Gmail bang trinh duyet mot lan roi thu lai."),

    (15, re.compile(r"authenticationfailed|invalid credentials|login failed|"
                    r"authentication fail", re.I),
     "Sai thong tin dang nhap. Kiem tra lai cot mat khau trong users.csv: phia "
     "Gmail phai la App Password, phia IceWarp phai la dia chi day du user@domain."),

    (20, re.compile(r"overquota|quota exceeded|\[OVERQUOTA\]", re.I),
     "Hop thu dich tren IceWarp da day. Tang quota cho user do trong IceWarp "
     "Admin roi chay lai sync."),

    (20, re.compile(r"message (is )?too (big|large)|size exceeds|exceeded the size", re.I),
     "Co mail lon hon gioi han cua IceWarp. Hoac tang gioi han kich thuoc mail "
     "tren IceWarp, hoac dat maxsize trong config.ini de bo qua nhung mail do "
     "(chung se KHONG duoc chuyen)."),

    (25, re.compile(r"trycreate|can't create folder|create failed", re.I),
     "Khong tao duoc folder ben IceWarp. Thuong do ten folder chua ky tu ma "
     "IceWarp khong nhan, hoac trung ten voi folder PIM (Contacts, Calendar, "
     "Tasks, Notes). Xem ./mm.py discover de biet folder nao, roi dat ten khac "
     "qua extra_args voi --regextrans2."),

    (30, re.compile(r"connection refused|no route to host|network is unreachable", re.I),
     "Khong ket noi duoc toi server. Kiem tra firewall cua VPS va cong 993 cua "
     "IceWarp co mo ra ngoai khong."),

    (30, re.compile(r"certificate verify failed|ssl.*handshake|hostname.*doesn't match", re.I),
     "Chung chi TLS cua IceWarp khong hop le hoac khong khop ten mien. Sua cho "
     "dung ten mien trong config.ini, hoac gia han chung chi tren IceWarp."),

    (35, re.compile(r"timeout|timed out", re.I),
     "Het thoi gian cho. Tang timeout trong config.ini, va giam workers neu "
     "duong truyen toi IceWarp dang qua tai."),

    (40, re.compile(r"can't locate .*\.pm in \@inc", re.I),
     "Thieu module Perl cho imapsync. Chay lai ./install.sh, hoac cai thu cong "
     "module duoc nhac ten trong dong loi bang: cpanm <Ten::Module>"),
]


def diagnose(text: str, limit: int = 3) -> List[str]:
    """Tra ve toi da `limit` goi y, sap theo do quan trong."""
    if not text:
        return []
    hits = [(prio, tip) for prio, pattern, tip in _RULES if pattern.search(text)]
    hits.sort(key=lambda x: x[0])
    out: List[str] = []
    for _prio, tip in hits:
        if tip not in out:
            out.append(tip)
        if len(out) >= limit:
            break
    return out
