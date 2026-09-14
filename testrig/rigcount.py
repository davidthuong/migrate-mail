#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dem mail tren mot dau IMAP cua testrig, va bat mail bi NHAN BAN.

`mm verify` doi chieu NGAY THANG, khong tra loi cau "co mail nao bi chep hai
lan khong". Ma nhan ban lai dung la kieu hong cua vong delta: lan chay thu hai
khong nhan ra mail da co ben dich nen chep lai tu dau. Khach mo hop thu thay
moi thu hai ban -- va `verify` van bao xanh, vi ngay thang cua ca hai ban deu
dung.

Nen cho nay dem theo Message-Id: id nao xuat hien hai lan trong cung mot folder
la mot lan chep thua.

    python3 testrig/rigcount.py --port 10993 --user an@cu.vn --password MatKhauCuaAn
    python3 testrig/rigcount.py --port 20993 --user an@moi.vn --password MatKhauDichAn

Tra ve 1 neu tim thay nhan ban, de con dung trong mot doan script.

Chi dung thu vien chuan, giong phan con lai cua repo.
"""

from __future__ import annotations

import argparse
import base64
import collections
import imaplib
import re
import sys


def utf7_decode(name):
    """&xxx- -> chu that. Du de doc bang mat, khong can hoan hao.

    Khong goi migrate_mail.imaputf7: neu ca hai ben cung sai mot kieu thi so
    dem se khop trong khi thuc te lech.
    """
    out = []
    i = 0
    while i < len(name):
        if name[i] != "&":
            out.append(name[i])
            i += 1
            continue
        j = name.find("-", i)
        if j < 0:
            out.append(name[i:])
            break
        chunk = name[i + 1:j]
        if not chunk:
            out.append("&")
        else:
            b = chunk.replace(",", "/")
            b += "=" * ((4 - len(b) % 4) % 4)
            try:
                out.append(base64.b64decode(b).decode("utf-16-be"))
            except Exception:
                out.append(name[i:j + 1])
        i = j + 1
    return "".join(out)


_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\) "(?P<sep>[^"]*)" (?P<name>.*)$')


def folders(conn):
    typ, data = conn.list()
    if typ != "OK":
        raise RuntimeError("LIST that bai: %r" % (data,))
    out = []
    for line in data:
        if isinstance(line, tuple):
            line = line[0]
        m = _LIST_RE.match(line.decode("utf-8", "replace").strip())
        if not m:
            continue
        name = m.group("name").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        if "\\Noselect" in m.group("flags"):
            continue
        out.append(name)
    return sorted(out)


def headers(conn, folder):
    """(Message-Id, Subject) cua moi mail trong folder. None neu khong mo duoc."""
    typ, _ = conn.select('"%s"' % folder, readonly=True)
    if typ != "OK":
        return None
    typ, data = conn.search(None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return []
    nums = data[0].split()
    typ, data = conn.fetch(b",".join(nums),
                           "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT)])")
    if typ != "OK":
        return []
    out = []
    for item in data:
        if not isinstance(item, tuple):
            continue
        mid = subject = None
        for line in item[1].decode("utf-8", "replace").splitlines():
            low = line.lower()
            if low.startswith("message-id:"):
                mid = line.split(":", 1)[1].strip()
            elif low.startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
        out.append((mid, subject))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True,
                    help="10993 = nguon, 20993 = dich (hoac 10143/20143)")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--quiet", action="store_true", help="chi in dong tong")
    args = ap.parse_args(argv)

    opener = imaplib.IMAP4_SSL if args.port % 1000 == 993 else imaplib.IMAP4
    conn = opener(args.host, args.port)
    conn.login(args.user, args.password)

    total = no_id = 0
    duplicates = []
    for folder in folders(conn):
        rows = headers(conn, folder)
        if rows is None:
            continue
        total += len(rows)
        counts = collections.Counter(mid for mid, _ in rows if mid)
        dups = {k: v for k, v in counts.items() if v > 1}
        blanks = sum(1 for mid, _ in rows if not mid)
        no_id += blanks
        if not args.quiet:
            note = ""
            if dups:
                note += "   <-- NHAN BAN: %d id lap" % len(dups)
            if blanks:
                note += "   [%d mail khong co Message-Id]" % blanks
            print("  %5d  %s%s" % (len(rows), utf7_decode(folder), note))
        for mid, n in sorted(dups.items()):
            duplicates.append("%s  x%d  %s" % (utf7_decode(folder), n, mid))

    print("TONG %s:%d  %s = %d mail, %d khong co Message-Id, %d id bi lap"
          % (args.host, args.port, args.user, total, no_id, len(duplicates)))
    for line in duplicates:
        print("  LAP: " + line)
    conn.logout()
    return 1 if duplicates else 0


if __name__ == "__main__":
    sys.exit(main())
