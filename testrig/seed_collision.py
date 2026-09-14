#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Do vao NGUON ba folder gay ra hai kieu ten khong chuyen thang duoc.

Dau nguon cua rig co tien to "INBOX." va dau phan cach ".", dau dich thi khong
tien to va dau phan cach "/". Doi ten giua hai kieu do sinh ra hai cho vap ma
khong ca hai deu im lang neu khong ai dem:

  INBOX.Du an.2024    -> cat tien to, doi dau phan cach -> "Du an/2024"
  INBOX.Du an/2024    -> cat tien to, trong ten da co san "/" -> "Du an/2024"

Hai folder NGUON khac nhau do chung vao MOT folder DICH. Mail khong mat, nhung
no tron vao nhau, va sau cutover thi khong con cach nao tach ra: khach mo hop
thu thay thu cua hai du an nam lan trong mot cho.

  INBOX.Bao gia = 2024  -> ten co dau '='

imapsync tach --f1f2 bang dau '=' nen khong dien ta duoc ten nguon chua no. Tool
giu nguyen ten thay vi sinh mot mapping hong, tuc folder nay sang dich van mang
ca tien to "INBOX.".

Chay SAU seed.py, roi xem `mm discover` co bao ca hai chuyen do khong.

    python3 testrig/seed_collision.py

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

USER = "an@cu.vn"
PASSWORD = "MatKhauCuaAn"

# (ten folder, nhan de nhan ra mail trong do, co duoc phep hong khong)
#
# Dovecot TU CHOI ten co '/' khi dau phan cach la '.': "[CANNOT] Invalid
# mailbox name: Name must not have '/' characters". Nghia la ca va cham do
# khong dung duoc tren Dovecot -- giu dong nay lai de lan sau khoi thu lai, va
# de biet neu mot ban Dovecot nao do doi y.
FOLDERS = [
    ("INBOX.Du an.2024", "LONG NHAU", False),
    ("INBOX.Du an/2024", "GACH CHEO TRONG TEN", True),
    ("INBOX.Bao gia = 2024", "CO DAU BANG", False),
]


def imap_name(name):
    """Boc nhay. Ten o day toan ASCII nen khong can UTF-7."""
    escaped = name.replace(chr(92), chr(92) * 2).replace('"', chr(92) + '"')
    return '"' + escaped + '"'


def make(subject, days_ago):
    msg = EmailMessage()
    when = time.time() - days_ago * 86400
    msg["Subject"] = subject
    msg["From"] = "nguoi.gui@doitac.vn"
    msg["To"] = USER
    msg["Date"] = email.utils.formatdate(when)
    msg["Message-Id"] = email.utils.make_msgid(domain="cu.vn")
    msg.set_content("Mail thu cho ten folder kho: %s\n" % subject)
    return msg, when


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--count", type=int, default=2, help="so mail moi folder")
    args = ap.parse_args(argv)

    try:
        conn = imaplib.IMAP4(args.host, args.port)
        conn.login(USER, PASSWORD)
    except Exception as exc:
        print("LOI: khong dang nhap duoc %s: %s" % (USER, exc))
        print("     Container da chay chua? docker compose ps")
        return 1

    bad = 0
    for folder, tag, duoc_phep_hong in FOLDERS:
        typ, data = conn.create(imap_name(folder))
        if typ != "OK" and b"exist" not in b" ".join(data or []).lower():
            loi = b" ".join(data or []).decode("utf-8", "replace")
            if duoc_phep_hong:
                print("  %-22s server tu choi (biet truoc): %s" % (folder, loi))
            else:
                print("  %-22s server TU CHOI: %s" % (folder, loi))
                bad += 1
            continue
        conn.subscribe(imap_name(folder))
        for i in range(args.count):
            msg, when = make("%s #%d" % (tag, i), days_ago=20 + i)
            typ, data = conn.append(imap_name(folder), None,
                                    imaplib.Time2Internaldate(when),
                                    msg.as_bytes())
            if typ != "OK":
                print("     APPEND hong: %s" % (data,))
                bad += 1
        print("  %-22s OK, %d mail" % (folder, args.count))

    conn.logout()
    print("\nGio chay: mm discover --only %s" % USER)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
