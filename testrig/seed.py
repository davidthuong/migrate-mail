#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Do du lieu mau vao Dovecot NGUON cua testrig.

Dang nhap bang mat khau that cua tung hop thu (khong dung master): buoc seed
la de DUNG SAN dau bai, khong phai de test. Phan test bat dau tu luc chay
mm.py.

    python3 testrig/seed.py                 # mac dinh, nhanh
    python3 testrig/seed.py --big 2000      # them mail cho binh@cu.vn
    python3 testrig/seed.py --host 10.0.0.5 # Docker chay tren may khac

Chi dung thu vien chuan, giong phan con lai cua repo.
"""

from __future__ import annotations

import argparse
import base64
import email.utils
import imaplib
import random
import sys
import time
from email.message import EmailMessage

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 10143

# Mat khau khop voi testrig/src/users.
ACCOUNTS = {
    "an@cu.vn": "MatKhauCuaAn",
    "binh@cu.vn": "MatKhauCuaBinh",
    "ketoan@cu.vn": "MatKhauKeToan",
}

# Ten folder co dau va co folder long nhau: hai thu de vo nhat khi doi ten
# giua hai server co dau phan cach khac nhau.
AN_FOLDERS = [
    "INBOX.Cong viec",
    "INBOX.Cong viec.Bao gia",
    u"INBOX.Kh\xe1ch h\xe0ng",
    u"INBOX.Kh\xe1ch h\xe0ng.Dự \xe1n A",
    u"INBOX.Lưu trữ 2019",
]

SUBJECTS = [
    u"Bao gia thang 3",
    u"Hợp đồng dịch vụ email",
    u"Re: Lịch họp tuần sau",
    u"Nhắc thanh to\xe1n ho\xe1 đơn",
    u"Fwd: T\xe0i liệu b\xe0n giao",
]


def utf7_encode(name):
    """Ten folder -> modified UTF-7 (RFC 3501). imaplib khong tu lam viec nay.

    Khong dung ma nguon cua tool de encode: neu ca hai ben cung sai mot kieu
    thi test se xanh trong khi thuc te hong.
    """
    out = []
    buf = []

    def flush():
        if not buf:
            return
        raw = u"".join(buf).encode("utf-16-be")
        b64 = base64.b64encode(raw).decode("ascii").rstrip("=")
        out.append("&" + b64.replace("/", ",") + "-")
        del buf[:]

    for ch in name:
        if ch == "&":
            flush()
            out.append("&-")
        elif 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append(ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def make_message(subject, days_ago, filler_bytes=0):
    msg = EmailMessage()
    when = time.time() - days_ago * 86400
    msg["Subject"] = subject
    msg["From"] = "nguoi.gui@doitac.vn"
    msg["To"] = "hop.thu@cu.vn"
    msg["Date"] = email.utils.formatdate(when)
    # Message-Id on dinh: tool dinh danh mail bang header nay, nen mail thieu
    # no se bi nhan ban o vong delta. Co mot mail thieu Message-Id o duoi de
    # test duong --addheader.
    msg["Message-Id"] = email.utils.make_msgid(domain="cu.vn")
    body = u"Nội dung thử cho testrig.\n" + ("x" * 200)
    msg.set_content(body)
    if filler_bytes:
        msg.add_attachment(b"\0" * filler_bytes, maintype="application",
                           subtype="octet-stream", filename="lon.bin")
    return msg, when


def append(conn, folder, msg, when, seen=True):
    flags = "(" + chr(92) + "Seen)" if seen else None
    conn.append(utf7_encode(folder), flags,
                imaplib.Time2Internaldate(when), msg.as_bytes())


def ensure(conn, folder):
    typ, data = conn.create(utf7_encode(folder))
    if typ != "OK" and b"exist" not in b" ".join(data or []).lower():
        print("  canh bao: khong tao duoc %s: %s" % (folder, data))
    conn.subscribe(utf7_encode(folder))


def connect(host, port, user, password):
    conn = imaplib.IMAP4(host, port)
    conn.login(user, password)
    return conn


def seed_an(conn):
    print("an@cu.vn: folder co dau + folder long nhau")
    for folder in AN_FOLDERS:
        ensure(conn, folder)
    targets = ["INBOX"] + AN_FOLDERS + ["INBOX.Sent", "INBOX.Drafts",
                                        "INBOX.Trash", "INBOX.Junk"]
    for i, folder in enumerate(targets):
        for j in range(3):
            msg, when = make_message(
                u"%s [%s]" % (SUBJECTS[(i + j) % len(SUBJECTS)], folder),
                days_ago=30 + i * 7 + j)
            append(conn, folder, msg, when)
    print("  %d folder, %d mail" % (len(targets), len(targets) * 3))


def seed_binh(conn, count, big_mb):
    print("binh@cu.vn: %d mail + 1 mail %d MB" % (count, big_mb))
    ensure(conn, "INBOX.Cong viec")
    for i in range(count):
        msg, when = make_message(u"%s #%d" % (SUBJECTS[i % len(SUBJECTS)], i),
                                 days_ago=random.randint(1, 900))
        append(conn, "INBOX" if i % 2 else "INBOX.Cong viec", msg, when)
        if count > 200 and i and i % 200 == 0:
            print("  ... %d/%d" % (i, count))
    if big_mb:
        msg, when = make_message(u"Mail lon %d MB" % big_mb, days_ago=5,
                                 filler_bytes=big_mb * 1024 * 1024)
        append(conn, "INBOX", msg, when)


def seed_ketoan(conn):
    print("ketoan@cu.vn: hop thu gan nhu rong (truong hop bien)")
    msg, when = make_message(u"Ch\xe0o mừng", days_ago=2)
    append(conn, "INBOX", msg, when, seen=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--big", type=int, default=300,
                    help="so mail cho binh@cu.vn (mac dinh 300)")
    ap.add_argument("--big-mb", type=int, default=12,
                    help="kich thuoc mail lon nhat, MB (0 = bo qua)")
    args = ap.parse_args(argv)

    random.seed(20260907)     # seed co dinh -> chay lai ra cung du lieu
    print("Do du lieu vao %s:%d\n" % (args.host, args.port))

    for user, password in ACCOUNTS.items():
        try:
            conn = connect(args.host, args.port, user, password)
        except Exception as exc:
            print("LOI: khong dang nhap duoc %s: %s" % (user, exc))
            print("     Container da chay chua? docker compose ps")
            return 1
        try:
            if user.startswith("an@"):
                seed_an(conn)
            elif user.startswith("binh@"):
                seed_binh(conn, args.big, args.big_mb)
            else:
                seed_ketoan(conn)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    print("\nXong. Buoc tiep: xem README.md trong thu muc nay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
