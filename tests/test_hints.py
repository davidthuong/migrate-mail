# -*- coding: utf-8 -*-
"""Test phan dich loi imapsync thanh goi y, va phan ket xuat bao cao."""

import os
import shutil
import sys
import tempfile
import time
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


class TestHintsRecomputedFromLog(unittest.TestCase):
    """Goi y phai duoc tinh lai tu log, khong doc tu file run da luu.

    Day la bai hoc tu mot su co that: bao cao dem 27/08 dong bang 3 goi y vao
    state/runs/*.json, trong do 2 sai. Sau khi sua luat chan doan, bao cao cu
    van hien nguyen cai sai -- va se hien mai mai, vi mailbox do da xong nen
    khong bao gio duoc chay lai de ghi de.
    """

    OLD_WRONG = "Hop thu dich tren IceWarp da day. Tang quota..."
    LOG = ("Host1: imap connection timeout is 300 seconds\n"
           "Average bandwidth rate                  : 202.2 KiB/s\n"
           "Err 1/1: - msg INBOX/16947 {0} S[22184] could not be fetched:\n"
           "Exiting with return value 115 (EXIT_ERR_FETCH) 1/50 nb_errors\n")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmhint-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.log = self.write(self.tmp / "a.sync.log", self.LOG)
        report._hint_cache.clear()

    @staticmethod
    def write(path, text):
        """Ghi voi newline="\\n" giong het runner, khong de Windows doi ra CRLF."""
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def failed_row(self, **kw):
        return row(ket_qua="LOI", goi_y=self.OLD_WRONG, log=str(self.log), **kw)

    def test_stale_hint_in_the_saved_run_is_replaced(self):
        tips = report.hints_for_row(self.failed_row())
        self.assertTrue(any("there are N among M" in t for t in tips), tips)
        self.assertFalse(any("IceWarp da day" in t for t in tips), tips)

    def test_falls_back_to_stored_hint_when_log_is_gone(self):
        self.log.unlink()
        self.assertEqual(report.hints_for_row(self.failed_row()), [self.OLD_WRONG])

    def test_row_without_log_keeps_what_was_saved(self):
        self.assertEqual(report.hints_for_row(row(ket_qua="LOI", goi_y="cu", log="")),
                         ["cu"])

    def test_successful_row_is_left_alone(self):
        """Dong OK khong doc log: goi y chi co nghia khi that bai."""
        self.assertEqual(report.hints_for_row(row(ket_qua="OK", log=str(self.log))), [])

    def test_refresh_hints_rewrites_the_whole_run(self):
        rows = report.refresh_hints([self.failed_row(), row(ket_qua="OK")])
        self.assertIn("there are N among M", rows[0]["goi_y"])
        self.assertEqual(rows[1]["goi_y"], "")

    def test_reads_only_the_tail_of_a_huge_log(self):
        """Log 12 tieng co the rat lon; doc ca file moi 1,2 giay la khong duoc."""
        big = self.tmp / "big.log"
        with big.open("w", encoding="utf-8") as fh:
            fh.write("dong rac khong lien quan\n" * 60000)   # ~1.4 MB
            fh.write(self.LOG)
        text = report.log_tail(big)
        self.assertLessEqual(len(text), report._TAIL_BYTES)
        self.assertIn("could not be fetched", text)
        self.assertTrue(any("there are N among M" in t
                            for t in report.hints_for_row(
                                row(ket_qua="LOI", log=str(big)))))

    def test_tail_never_starts_mid_line(self):
        big = self.write(self.tmp / "cut.log",
                         "x" * (report._TAIL_BYTES + 500) + "\nnguyen ven\n")
        self.assertEqual(report.log_tail(big), "nguyen ven\n")

    def test_cache_is_refreshed_when_the_log_grows(self):
        """Log dang chay thi lon dan; goi y phai doi theo, khong ket o lan dau."""
        quiet = self.tmp / "live.log"
        quiet.write_text("Transfer started\n", encoding="utf-8")
        self.assertEqual(report.hints_for_row(row(ket_qua="LOI", log=str(quiet))), [])
        with quiet.open("a", encoding="utf-8") as fh:
            fh.write("NO [ALERT] Too many simultaneous connections\n")
        os.utime(str(quiet), (time.time() + 2, time.time() + 2))
        tips = report.hints_for_row(row(ket_qua="LOI", log=str(quiet)))
        self.assertTrue(any("15 ket noi" in t for t in tips), tips)


class TestLatestRows(unittest.TestCase):
    """Gop nhieu lan chay thanh trang thai hien tai cua tung mailbox.

    Moi file run chi chua mailbox cua lan chay do. Sau vai dem chay rai rac,
    khong file nao con chua du danh sach -- bao cao ca cuoc migrate thi phai
    gop lai. Logic nay truoc kia chi co trong dashboard, nen lenh `report`
    va dashboard bao cao lech nhau tren cung du lieu.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmruns-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    def save(self, stamp, rows):
        return report.save_run(rows, self.tmp / ("%s.json" % stamp))

    def test_newer_run_wins(self):
        self.save("20260101-000000", [row(src_user="a@x.com", ket_qua="LOI")])
        self.save("20260102-000000", [row(src_user="a@x.com", ket_qua="OK")])
        merged = report.latest_rows(self.tmp)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged["a@x.com"]["ket_qua"], "OK")

    def test_mailboxes_from_different_runs_are_all_kept(self):
        self.save("20260101-000000", [row(src_user="a@x.com")])
        self.save("20260102-000000", [row(src_user="b@x.com")])
        self.assertEqual(set(report.latest_rows(self.tmp)), {"a@x.com", "b@x.com"})

    def test_non_sync_runs_are_ignored(self):
        """Lan `--sizes` chi do dung luong, khong noi len trang thai chuyen."""
        self.save("20260101-000000", [row(src_user="a@x.com", mode="sizes")])
        self.assertEqual(report.latest_rows(self.tmp), {})

    def test_missing_directory_is_empty(self):
        self.assertEqual(report.latest_rows(self.tmp / "khong-co"), {})

    def test_two_runs_in_the_same_second_do_not_overwrite(self):
        """Dau thoi gian chi den giay, ma ten file quyet dinh lan nao moi hon."""
        p1 = self.save("20260101-000000", [row(src_user="a@x.com", ket_qua="LOI")])
        p2 = self.save("20260101-000000", [row(src_user="a@x.com", ket_qua="OK")])
        self.assertNotEqual(p1, p2)
        self.assertEqual(report.latest_rows(self.tmp)["a@x.com"]["ket_qua"], "OK")


class TestMergedRows(unittest.TestCase):
    """Bao cao ca cuoc migrate: trang thai lay lan cuoi, khoi luong cong don.

    Moi dong run chi mang thong ke cua rieng lan chay do ("Messages
    transferred" cua imapsync). Hop thu bi Gmail cat giua chung roi chay lai
    da chuyen mail o ca hai lan, nen lay lan cuoi lam bao cao la ke thieu
    cong cua chinh minh -- co lan bao 87.936 mail trong khi thuc te gan
    122.700.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmmerge-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    def save(self, stamp, rows):
        return report.save_run(rows, self.tmp / ("%s.json" % stamp))

    def test_volume_is_summed_but_status_comes_from_the_last_run(self):
        self.save("20260827-000000", [row(src_user="a@x.com", ket_qua="LOI",
                                          folder="9/11", mail_chuyen="34675",
                                          bytes="14778418601", duration_sec="43897.7")])
        self.save("20260828-000000", [row(src_user="a@x.com", ket_qua="OK",
                                          folder="11/11", mail_chuyen="14445",
                                          bytes="9556302233", duration_sec="17400.0")])
        merged = report.merged_rows(self.tmp)
        self.assertEqual(len(merged), 1)
        r = merged[0]
        self.assertEqual(r["mail_chuyen"], "49120")                  # 34675+14445
        self.assertEqual(r["bytes"], str(14778418601 + 9556302233))
        self.assertEqual(r["duration_sec"], "61297.7")               # tong thoi gian
        self.assertEqual(r["ket_qua"], "OK")                         # lan cuoi
        self.assertEqual(r["folder"], "11/11")                       # lan cuoi

    def test_human_columns_follow_the_sum(self):
        self.save("20260827-000000", [row(src_user="a@x.com", mail_chuyen="1",
                                          bytes=str(1024 ** 3), duration_sec="60")])
        self.save("20260828-000000", [row(src_user="a@x.com", mail_chuyen="1",
                                          bytes=str(1024 ** 3), duration_sec="60")])
        r = report.merged_rows(self.tmp)[0]
        self.assertEqual(r["dung_luong"], "2.0 GB")
        self.assertEqual(r["thoi_gian"], "2m00s")

    def test_dry_runs_are_not_counted(self):
        """--dry khong chep gi ca; cong vao la ra so ao."""
        self.save("20260827-000000", [row(src_user="a@x.com", mail_chuyen="100",
                                          bytes="1000")])
        self.save("20260828-000000", [row(src_user="a@x.com", mail_chuyen="99",
                                          bytes="999", mode="dry")])
        self.assertEqual(report.merged_rows(self.tmp)[0]["mail_chuyen"], "100")

    def test_a_mailbox_run_once_is_left_alone(self):
        """8/10 hop chi chay mot lan -- so phai y nguyen."""
        self.save("20260827-000000", [row(src_user="a@x.com", mail_chuyen="2365",
                                          bytes="133500000")])
        r = report.merged_rows(self.tmp)[0]
        self.assertEqual(r["mail_chuyen"], "2365")
        self.assertEqual(r["bytes"], "133500000")

    def test_each_mailbox_gets_one_row_sorted_by_address(self):
        self.save("20260827-000000", [row(src_user="b@x.com"), row(src_user="a@x.com")])
        self.save("20260828-000000", [row(src_user="a@x.com")])
        self.assertEqual([r["src_user"] for r in report.merged_rows(self.tmp)],
                         ["a@x.com", "b@x.com"])

    def test_no_runs_gives_nothing(self):
        self.assertEqual(report.merged_rows(self.tmp), [])
