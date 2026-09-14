#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Do vao NGUON ba mail vua ve, de thu vong delta luc cutover.

Chay SAU lan sync day du, roi chay `mm sync --since-days 2`. Ca ba mail deu co
INTERNALDATE la hom nay -- tuc deu VUA VE -- nhung header Date: khac nhau:

    MOI-CA-HAI        Date: hom nay        thu thuong
    VE-MUON-DATE-CU   Date: 10 ngay truoc  thu forward lai, thu ket hang doi
                                           vai ngay moi giao, thu tu he thong
                                           co dong ho sai
    KHONG-CO-DATE     khong co Date:       thu do may quet / he thong sinh ra

Ca ba phai sang dich. Neu chi mot cai sang thi tool dang loc cua so delta bang
header Date: (SEARCH SENTSINCE) thay vi bang ngay mail ve (INTERNALDATE), va
hai cai kia dang bi bo lai tren server cu -- ma server cu thi sap bi xoa.

Chay lai lenh delta them mot lan nua roi dem bang rigcount.py: 0 id bi lap.
Neu co nhan ban thi co --noabletosearch dang bi dat lech chi mot dau: dau dich
van loc bang Date: nen no khong "thay" mail da co san va chep lai lan nua.

    python3 testrig/seed_delta.py

Chi dung thu vien chuan, giong phan con lai cua repo.
"""

from __future__ import annotations

import argparse
import email.utils
import imaplib
import sys
import time
from email.message import EmailMessage

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 10143

# Mat khau khop voi testrig/src/users.
USER = "an@cu.vn"
PASSWORD = "MatKhauCuaAn"

# (nhan, so ngay cua header Date: -- None la khong co header do)
CASES = [
    ("MOI-CA-HAI", 0),
    ("VE-MUON-DATE-CU", 10),
    ("KHONG-CO-DATE", None),
]


def build(tag, date_days, now):
    msg = EmailMessage()
    msg["Subject"] = "DELTA %s" % tag
    msg["From"] = "nguoi.gui@doitac.vn"
    msg["To"] = USER
    if date_days is not None:
        msg["Date"] = email.utils.formatdate(now - date_days * 86400)
    # Message-Id co dinh: chay lai script khong sinh ra mail moi, va rigcount
    # doi chieu duoc theo id nay.
    msg["Message-Id"] = "<delta-%s@cu.vn>" % tag.lower()
    msg.set_content("Mail thu vong delta luc cutover: %s\n" % tag)
    return msg


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--folder", default="INBOX")
    args = ap.parse_args(argv)

    now = time.time()
    try:
        conn = imaplib.IMAP4(args.host, args.port)
        conn.login(USER, PASSWORD)
    except Exception as exc:
        print("LOI: khong dang nhap duoc %s: %s" % (USER, exc))
        print("     Container da chay chua? docker compose ps")
        return 1

    for tag, date_days in CASES:
        msg = build(tag, date_days, now)
        typ, data = conn.append('"%s"' % args.folder, None,
                                imaplib.Time2Internaldate(now), msg.as_bytes())
        print("  %-17s Date=%-13s INTERNALDATE=hom nay  %s"
              % (tag,
                 "khong co" if date_days is None else "-%d ngay" % date_days,
                 typ))
        if typ != "OK":
            print("     APPEND hong: %s" % (data,))
            return 1

    conn.logout()
    print("\nGio chay: mm sync --since-days 2   -> phai chuyen CA BA mail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
