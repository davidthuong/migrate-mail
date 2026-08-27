# -*- coding: utf-8 -*-
"""imapsync gia, dung cho test tich hop. Khong lien quan gi den ban chay that.

Hanh vi:
  --version  -> in mot dong version
  --help     -> in danh sach flag ma tool that co
  con lai    -> ghi lai argv ra $FAKE_IMAPSYNC_ARGV, roi in ket qua gia lap.
                Neu --user1 chua chu "fail" thi gia vo dang nhap that bai.
"""

import json
import os
import sys

OK_TAIL = """Folders synced                    : 9/9 synced
++++ Statistics ++++
Transfer time                     : 12.5 sec
Messages transferred              : 421
Messages skipped                  : 7
Total bytes transferred           : 10485760
Total bytes skipped               : 1024
Biggest message                   : 524288 bytes
Detected 0 errors
Exiting with return value 0 (EX_OK: successful termination, 0 error)
"""

FAIL_TAIL = """Host1 failure: Error login on [imap.gmail.com]:
AUTHENTICATIONFAILED Invalid credentials (Failure)
Detected 1 errors
Exiting with return value 16 (EXIT_AUTHENTICATION_FAILURE: error after authentication)
"""

FLAGS = [
    "--host1", "--port1", "--ssl1", "--notls1", "--user1", "--passfile1",
    "--host2", "--port2", "--ssl2", "--notls2", "--user2", "--passfile2",
    "--exclude", "--f1f2", "--useheader", "--addheader", "--filterflags",
    "--skipcrossduplicates", "--nousecache", "--maxsize", "--maxbytespersecond",
    "--maxage", "--timeout", "--errorsmax", "--nofoldersizes", "--noreleasecheck",
    "--nolog", "--tmpdir", "--pidfile", "--dry", "--justfolders",
    "--justfoldersizes",
    "--syncinternaldates", "--idatefromheader", "--version", "--help",
]


def main(argv):
    if "--version" in argv:
        print("imapsync fake 9.9.9")
        return 0
    if "--help" in argv:
        print("Cac tuy chon:")
        for f in FLAGS:
            print("  %s" % f)
        return 0

    record = os.environ.get("FAKE_IMAPSYNC_ARGV")
    if record:
        with open(record, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\n")

    user1 = ""
    if "--user1" in argv:
        user1 = argv[argv.index("--user1") + 1]

    # Kiem tra passfile that su ton tai va doc duoc, giong imapsync that
    for flag in ("--passfile1", "--passfile2"):
        if flag in argv:
            path = argv[argv.index(flag) + 1]
            if not os.path.exists(path):
                print("Failure: cannot read %s %s" % (flag, path))
                print("Exiting with return value 12 (EXIT_BY_FILE: passfile missing)")
                return 12

    print("Host1: imap.gmail.com Host2: mail.congty.vn")
    if "fail" in user1:
        sys.stdout.write(FAIL_TAIL)
        return 16
    sys.stdout.write(OK_TAIL)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
