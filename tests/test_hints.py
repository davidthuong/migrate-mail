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
