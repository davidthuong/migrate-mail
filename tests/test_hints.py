# -*- coding: utf-8 -*-
"""Test phan dich loi imapsync thanh goi y, va phan ket xuat bao cao."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_mail import report
from migrate_mail.hints import diagnose


class TestDiagnose(unittest.TestCase):
    def assertHint(self, text, keyword):
        tips = diagnose(text)
        self.assertTrue(tips, "khong sinh goi y nao cho: %r" % text)
        self.assertTrue(any(keyword.lower() in t.lower() for t in tips),
                        "khong thay '%s' trong: %s" % (keyword, tips))

    def test_gmail_bandwidth_limit(self):
        self.assertHint("NO [LIMIT] Bandwidth limit exceeded for this account",
                        "2500 MB")

    def test_too_many_connections(self):
        self.assertHint("NO [ALERT] Too many simultaneous connections", "15 ket noi")

    def test_app_password_required(self):
        self.assertHint(
            "NO [ALERT] Application-specific password required", "App Password")

    def test_web_login_required(self):
        self.assertHint("Please log in via your web browser", "trinh duyet")

    def test_invalid_credentials(self):
        self.assertHint("AUTHENTICATIONFAILED Invalid credentials (Failure)", "users.csv")

    def test_destination_over_quota(self):
        self.assertHint("NO [OVERQUOTA] Mailbox is over quota", "quota")

    def test_message_too_large(self):
        self.assertHint("NO Message too big for this mailbox", "maxsize")

    def test_folder_create_failure(self):
        self.assertHint("NO [TRYCREATE] Mailbox doesn't exist", "discover")

    def test_tls_problem(self):
        self.assertHint("SSL connect attempt failed: certificate verify failed",
                        "chung chi")

    def test_missing_perl_module(self):
        self.assertHint("Can't locate Mail/IMAPClient.pm in @INC (you may need...)",
                        "cpanm")

    def test_clean_log_produces_nothing(self):
        self.assertEqual(diagnose("Transfer ended. Detected 0 errors"), [])
        self.assertEqual(diagnose(""), [])

    # --- Nhung dong vo hai co san trong MOI log imapsync -------------------
    # Ba luat duoi day tung bat trung chung, lam bao cao bao viec can lam
    # hoan toan sai (di tang quota IceWarp, di tang timeout) cho mailbox
    # that bai vi ly do khac han.

    def test_stats_block_is_not_a_bandwidth_limit(self):
        """'Average bandwidth rate' nam trong khoi thong ke cua moi log."""
        self.assertEqual(
            diagnose("Average bandwidth rate                  : 328.8 KiB/s"), [])

    def test_imapsync_banner_is_not_a_timeout(self):
        """imapsync in thong so cua chinh no, va echo lai ca dong lenh."""
        text = ("/usr/local/bin/imapsync --host1 imap.gmail.com --timeout 300\n"
                "Host1: imap connection timeout is 300 seconds\n"
                "Host2: imap connection timeout is 300 seconds\n")
        self.assertEqual(diagnose(text), [])

    def test_gmail_overquota_is_not_blamed_on_icewarp(self):
        """[OVERQUOTA] luc FETCH la han muc Gmail, khong phai hop dich day."""
        text = ("Err 2/2: - msg [Gmail]/Sent/17821 could not be fetched: "
                "* BYE [OVERQUOTA] Account exceeded command or bandwidth limits.\n")
        tips = diagnose(text)
        self.assertTrue(any("2500 MB" in t for t in tips), tips)
        self.assertFalse(any("IceWarp da day" in t for t in tips),
                         "do loi cho IceWarp trong khi Gmail moi la ben chan: %s" % tips)

    def test_unfetchable_message_is_not_reported_as_throttling(self):
        """Log that cua mot hop DA XONG, chi thieu 1 mail Gmail khong tra ra.

        Khong bi chan, khong reconnect -- nhung imapsync van thoat 115. Bao cao
        phai noi ve mail hong, khong duoc do cho han muc bang thong.
        """
        text = (
            "Average bandwidth rate                  : 202.2 KiB/s\n"
            "Reconnections to host1                  : 0\n"
            "The sync is not finished, there are 1 among 16749 identified "
            "messages in host1 that are not on host2.\n"
            "Detected 1 errors\n"
            "Err 1/1: - msg INBOX/16947 {0} S[22184] F[\\Seen] "
            "I[30-Dec-2025 01:56:35 +0000] could not be fetched:\n"
            "The most frequent error is ERR_Host1_FETCH.\n"
            "Exiting with return value 115 (EXIT_ERR_FETCH) 1/50 nb_errors/max_errors\n")
        tips = diagnose(text)
        self.assertEqual(len(tips), 1, tips)
        self.assertIn("there are N among M", tips[0])
        self.assertNotIn("2500 MB", tips[0])

    def test_throttled_fetch_errors_do_not_claim_broken_messages(self):
        """Fetch loi vi bi Gmail bop thi cau tra loi la han muc, khong phai mail hong."""
        text = ("Err 1/1: - msg [Gmail]/Sent/17821 could not be fetched: * BYE "
                "[OVERQUOTA] Account exceeded command or bandwidth limits. (5x)\n"
                "The most frequent error is ERR_Host1_FETCH.\n")
        tips = diagnose(text)
        self.assertEqual(len(tips), 1, tips)
        self.assertIn("2500 MB", tips[0])

    def test_real_gmail_throttle_log_gives_only_true_hints(self):
        """Cac dong quyet dinh cua mot log that bi Gmail chan (27/08/2026).

        Hop nay dinh ca hai chuyen thuc: bi bop bang thong, VA co mot mail
        Gmail khong tra ra. Truoc day log nay sinh 3 goi y, 2 trong so do sai
        (do hop dich IceWarp day, va doi tang timeout).
        """
        text = (
            "Host1: imap connection timeout is 300 seconds\n"
            "Host2: imap connection timeout is 300 seconds\n"
            "Average bandwidth rate                  : 328.8 KiB/s\n"
            "Detected 2 errors\n"
            "Err 1/2: - msg INBOX/73359 {0} S[478533] could not be fetched:\n"
            "Err 2/2: - msg [Gmail]/Sent/17821 could not be fetched: * BYE "
            "[OVERQUOTA] Account exceeded command or bandwidth limits. (5x)\n"
            "The most frequent error is ERR_Host1_FETCH.\n"
            "Failure: lost connection for host1 [imap.gmail.com]\n"
            "Exiting with return value 115 (EXIT_ERR_FETCH) 3/50 nb_errors/max_errors\n")
        tips = diagnose(text)
        self.assertEqual(len(tips), 2, "van con goi y thua: %s" % tips)
        self.assertIn("2500 MB", tips[0])                 # nguyen nhan dung sync
        self.assertIn("there are N among M", tips[1])     # Err 1/2, mail hong that
        self.assertFalse(any("IceWarp da day" in t for t in tips), tips)
        self.assertFalse(any("Tang timeout" in t for t in tips), tips)

    def test_most_important_hint_comes_first(self):
        text = ("connection timed out later on\n"
                "NO [LIMIT] Bandwidth limit exceeded\n")
        self.assertIn("2500 MB", diagnose(text)[0])

    def test_result_limit_is_respected(self):
        text = "bandwidth ... AUTHENTICATIONFAILED ... OVERQUOTA ... timeout ... TRYCREATE"
        self.assertLessEqual(len(diagnose(text, limit=2)), 2)


def row(**kw):
    base = {"src_user": "a@cu.com", "dst_user": "a@moi.vn", "ket_qua": "OK",
            "folder": "9/9", "mail_chuyen": "10", "mail_bo_qua": "0",
            "bytes": "1024", "dung_luong": "1.0 KB", "loi": "0",
            "thoi_gian": "5s", "duration_sec": "5.0", "exit": "0",
            "ghi_chu": "", "goi_y": "", "log": "", "mode": "sync"}
    base.update(kw)
    return base


class TestHtmlReport(unittest.TestCase):
    def render(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            p = report.write_html(rows, Path(tmp) / "r.html")
            return p.read_text(encoding="utf-8")

    def test_escapes_untrusted_text_from_logs(self):
        """Ghi chu lay tu output imapsync -- la du lieu ngoai, phai escape."""
        html_out = self.render([row(ket_qua="LOI", ghi_chu="<script>alert(1)</script>")])
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)

    def test_escapes_untrusted_folder_and_user_names(self):
        html_out = self.render([row(src_user="<b>x</b>@cu.com", folder="<i>9/9</i>")])
        self.assertNotIn("<b>x</b>", html_out)
        self.assertNotIn("<i>9/9</i>", html_out)

    def test_shows_hints_for_failed_mailbox(self):
        html_out = self.render([row(ket_qua="LOI", goi_y="Goi y mot | Goi y hai")])
        self.assertIn("Goi y mot", html_out)
        self.assertIn("Goi y hai", html_out)
        self.assertEqual(html_out.count('class="tip"'), 2)

    def test_successful_row_has_no_exit_noise(self):
        html_out = self.render([row(exit="EX_OK: successful termination, 0 error")])
        self.assertNotIn("EX_OK", html_out)

    def test_marks_failed_rows(self):
        html_out = self.render([row(ket_qua="LOI"), row()])
        self.assertEqual(html_out.count('class="bad"'), 1)
        self.assertIn("1/2 mailbox thanh cong", html_out)


class TestFormatting(unittest.TestCase):
    def test_human_bytes(self):
        self.assertEqual(report.human_bytes(0), "0 B")
        self.assertEqual(report.human_bytes(1024), "1.0 KB")
        self.assertEqual(report.human_bytes(10 * 1024 ** 2), "10.0 MB")
        self.assertEqual(report.human_bytes(2.5 * 1024 ** 3), "2.5 GB")
        self.assertEqual(report.human_bytes("khong-phai-so"), "-")

    def test_human_duration(self):
        self.assertEqual(report.human_duration(9), "9s")
        self.assertEqual(report.human_duration(75), "1m15s")
        self.assertEqual(report.human_duration(3725), "1h02m")
        self.assertEqual(report.human_duration(None), "0s")

    def test_csv_keeps_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = report.write_csv([row(goi_y="mot goi y")], Path(tmp) / "r.csv")
            text = p.read_text(encoding="utf-8-sig")
            self.assertIn("goi_y", text.splitlines()[0])
            self.assertIn("mot goi y", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
