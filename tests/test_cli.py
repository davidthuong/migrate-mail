# -*- coding: utf-8 -*-
"""Test tich hop: chay het luong doctor -> sync -> report voi imapsync gia.

Khong ket noi mang. Buoc do folder Gmail duoc thay bang du lieu mau.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from migrate_mail import cli
from migrate_mail.report import load_run

from test_discover import GMAIL_EN, parse

FAKE = HERE / "fake_imapsync.py"

CONFIG = """[source]
host = imap.gmail.com
port = 993
ssl = true

[dest]
host = mail.congty.vn
port = 993
ssl = true

[sync]
workers = 2
maxsize = 52428800

[paths]
imapsync = {imapsync}
logdir = logs
statedir = state
"""

USERS = """src_user,src_password,dst_user,dst_password
an@cu.com,aaaa bbbb cccc dddd,an@moi.vn,MatKhau1
# dong ghi chu se bi bo qua
binh@cu.com,eeeeffffgggghhhh,binh@moi.vn,MatKhau2

fail.chi@cu.com,iiiijjjjkkkkllll,chi@moi.vn,MatKhau3
"""


def quote(p):
    return '"%s"' % p if " " in str(p) else str(p)


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmtest-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        imapsync = "%s %s" % (quote(sys.executable), quote(FAKE))
        (self.tmp / "config.ini").write_text(
            CONFIG.format(imapsync=imapsync), encoding="utf-8")
        (self.tmp / "users.csv").write_text(USERS, encoding="utf-8")
        self.argv_log = self.tmp / "argv.jsonl"
        os.environ["FAKE_IMAPSYNC_ARGV"] = str(self.argv_log)
        self.addCleanup(os.environ.pop, "FAKE_IMAPSYNC_ARGV", None)

    def run_cli(self, *args):
        base = ["--config", str(self.tmp / "config.ini"),
                "--users", str(self.tmp / "users.csv")]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(base + list(args))
        return code, buf.getvalue()

    def recorded_argv(self):
        if not self.argv_log.exists():
            return []
        return [json.loads(l) for l in self.argv_log.read_text(encoding="utf-8").splitlines()]


class TestDoctor(CliTestCase):
    def test_reports_ready_when_everything_present(self):
        code, out = self.run_cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("imapsync fake 9.9.9", out)
        self.assertIn("3 mailbox", out)
        self.assertIn("san sang", out)

    def test_flags_are_checked_against_installed_imapsync(self):
        _code, out = self.run_cli("doctor")
        self.assertIn("chap nhan moi flag tool dung", out)

    def test_missing_imapsync_is_an_error(self):
        (self.tmp / "config.ini").write_text(
            CONFIG.format(imapsync="imapsync-khong-ton-tai"), encoding="utf-8")
        code, out = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertIn("khong tim thay imapsync", out)


def fake_folders(cfg, user, timeout=60):
    if "loi" in user.src_user:
        from migrate_mail.discover import DiscoveryError
        raise DiscoveryError("login that bai: Invalid credentials")
    return parse(GMAIL_EN)


class TestSync(CliTestCase):
    def sync(self, *args):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            return self.run_cli("sync", *args)

    def test_full_run_reports_per_mailbox_outcome(self):
        code, out = self.sync()
        self.assertEqual(code, 1, out)          # co 1 mailbox that bai co y
        self.assertIn("an@cu.com", out)
        self.assertIn("2/3 mailbox OK", out)
        self.assertIn("EXIT_AUTHENTICATION_FAILURE", out)

    def test_writes_csv_html_and_json_reports(self):
        _code, out = self.sync()
        logs = self.tmp / "logs"
        self.assertTrue(list(logs.glob("report-*.csv")), out)
        self.assertTrue(list(logs.glob("report-*.html")))
        runs = list((self.tmp / "state" / "runs").glob("*.json"))
        self.assertEqual(len(runs), 1)
        rows = load_run(runs[0])
        self.assertEqual(len(rows), 3)
        ok = [r for r in rows if r["ket_qua"] == "OK"]
        self.assertEqual(len(ok), 2)
        self.assertEqual(ok[0]["mail_chuyen"], "421")
        self.assertEqual(ok[0]["dung_luong"], "10.0 MB")

    def test_each_mailbox_gets_its_own_log_file(self):
        self.sync()
        logs = sorted(p.name for p in (self.tmp / "logs").glob("*.sync.*.log"))
        self.assertEqual(len(logs), 3)
        self.assertTrue(any(n.startswith("an@cu.com") for n in logs))

    def test_log_records_command_without_exposing_passwords(self):
        self.sync()
        log = next((self.tmp / "logs").glob("an@cu.com.sync.*.log"))
        text = log.read_text(encoding="utf-8")
        self.assertIn("# lenh:", text)
        self.assertIn("<passfile>", text)
        self.assertNotIn("aaaabbbbccccdddd", text)
        self.assertNotIn("MatKhau1", text)

    def test_passfiles_are_deleted_after_run(self):
        self.sync()
        leftovers = list((self.tmp / "state").rglob("*.pass"))
        self.assertEqual(leftovers, [])

    def test_app_password_spaces_are_stripped_before_use(self):
        """Google hien app password co khoang trang; IMAP nhan ban lien nhau."""
        self.sync()
        # imapsync gia da xac nhan passfile ton tai; kiem tra noi dung qua User
        from migrate_mail.users import load_users
        u = load_users(self.tmp / "users.csv")[0]
        self.assertEqual(u.src_password, "aaaabbbbccccdddd")

    def test_gmail_exclusions_reach_imapsync(self):
        self.sync()
        argv = self.recorded_argv()
        self.assertTrue(argv)
        flat = argv[0]
        excludes = [flat[i + 1] for i, t in enumerate(flat) if t == "--exclude"]
        self.assertEqual(len(excludes), 4)
        self.assertTrue(any("All" in e for e in excludes))

    def test_maxsize_from_config_reaches_imapsync(self):
        self.sync()
        flat = self.recorded_argv()[0]
        self.assertIn("--maxsize", flat)
        self.assertEqual(flat[flat.index("--maxsize") + 1], "52428800")

    def test_dry_run_passes_dry_flag(self):
        self.sync("--dry")
        self.assertTrue(all("--dry" in a for a in self.recorded_argv()))

    def test_since_days_becomes_maxage(self):
        self.sync("--since-days", "3")
        flat = self.recorded_argv()[0]
        self.assertEqual(flat[flat.index("--maxage") + 1], "3")

    def test_only_filters_to_one_mailbox(self):
        code, out = self.sync("--only", "an@cu.com")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.recorded_argv()), 1)

    def test_only_rejects_unknown_address(self):
        code, out = self.sync("--only", "khongco@cu.com")
        self.assertEqual(code, 2)
        self.assertIn("khong ton tai", out)

    def test_resume_skips_completed_mailboxes(self):
        self.sync("--only", "an@cu.com")
        self.argv_log.unlink()
        code, out = self.sync("--only", "an@cu.com", "--resume")
        self.assertEqual(code, 0, out)
        self.assertIn("bo qua 1 mailbox", out)
        self.assertEqual(self.recorded_argv(), [])

    def test_mailbox_with_failed_discovery_is_not_synced(self):
        """Chay mu se rat de keo ca All Mail sang -> fail closed, bo qua han."""
        (self.tmp / "users.csv").write_text(
            "src_user,src_password,dst_user,dst_password\n"
            "loi@cu.com,aaaabbbbccccdddd,loi@moi.vn,MatKhau\n", encoding="utf-8")
        code, out = self.sync()
        self.assertEqual(code, 1)
        self.assertIn("Khong mailbox nao do duoc folder", out)
        self.assertEqual(self.recorded_argv(), [])

    def test_partial_discovery_failure_still_syncs_the_rest(self):
        (self.tmp / "users.csv").write_text(
            "src_user,src_password,dst_user,dst_password\n"
            "loi@cu.com,aaaabbbbccccdddd,loi@moi.vn,MatKhau\n"
            "an@cu.com,aaaabbbbccccdddd,an@moi.vn,MatKhau\n", encoding="utf-8")
        code, out = self.sync()
        self.assertEqual(code, 1)                      # tong the van la that bai
        self.assertIn("khong do duoc folder", out)     # ly do cua mailbox hong
        self.assertEqual(len(self.recorded_argv()), 1) # nhung mailbox kia van chay
        self.assertIn("1/2 mailbox OK", out)


class TestReport(CliTestCase):
    def test_report_replays_last_run(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync")
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertIn("2/3 mailbox OK", out)

    def test_report_list_shows_saved_runs(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync")
        code, out = self.run_cli("report", "--list")
        self.assertEqual(code, 0)
        self.assertIn(".json", out)

    def test_report_without_any_run_is_graceful(self):
        code, out = self.run_cli("report")
        self.assertEqual(code, 1)
        self.assertIn("Chua co lan chay nao", out)

    def test_report_can_export_html(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync")
        out_path = self.tmp / "bao-cao.html"
        code, _ = self.run_cli("report", "--out", str(out_path))
        self.assertEqual(code, 0)
        html = out_path.read_text(encoding="utf-8")
        self.assertIn("<table>", html)
        self.assertIn("an@moi.vn", html)
        self.assertNotIn("MatKhau", html)

    # --- Bao cao ca cuoc migrate, khong phai mot lan chay ------------------
    # Chay rai rac nhieu dem thi khong file run nao con chua du danh sach.
    # Bao cao mac dinh chi doc lan chay cuoi, rat de tuong nham la toan bo.

    def two_separate_runs(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync", "--only", "an@cu.com")
            self.run_cli("sync", "--only", "binh@cu.com")

    def test_all_merges_mailboxes_across_runs(self):
        self.two_separate_runs()
        code, out = self.run_cli("report", "--all")
        self.assertEqual(code, 0, out)
        self.assertIn("an@cu.com", out)
        self.assertIn("binh@cu.com", out)

    def test_plain_report_still_shows_only_the_last_run(self):
        self.two_separate_runs()
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertIn("binh@cu.com", out)
        self.assertNotIn("an@cu.com", out)

    def test_plain_report_points_at_all_when_it_shows_fewer(self):
        self.two_separate_runs()
        _code, out = self.run_cli("report")
        self.assertIn("Dung --all", out)

    def test_no_pointer_when_the_run_already_covers_everyone(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync")
        _code, out = self.run_cli("report")
        self.assertNotIn("--all", out)

    def test_all_sums_volume_when_a_mailbox_ran_more_than_once(self):
        """Hop bi Gmail cat giua chung roi chay lai da chuyen o ca hai lan;
        lay lan cuoi lam bao cao la ke thieu cong cua chinh minh."""
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync", "--only", "an@cu.com")
            self.run_cli("sync", "--only", "an@cu.com")
        _code, out = self.run_cli("report", "--all")
        self.assertIn("842", out)                       # 421 + 421
        self.assertIn("tong cong don", out)

    def test_all_html_says_the_columns_are_totals(self):
        self.two_separate_runs()
        out_path = self.tmp / "gop.html"
        self.run_cli("report", "--all", "--out", str(out_path))
        self.assertIn("tong cong don", out_path.read_text(encoding="utf-8"))

    def test_plain_report_html_has_no_such_note(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync")
        out_path = self.tmp / "mot-lan.html"
        self.run_cli("report", "--out", str(out_path))
        self.assertNotIn("tong cong don", out_path.read_text(encoding="utf-8"))

    def test_all_can_export_html(self):
        self.two_separate_runs()
        out_path = self.tmp / "gop.html"
        code, _ = self.run_cli("report", "--all", "--out", str(out_path))
        self.assertEqual(code, 0)
        html = out_path.read_text(encoding="utf-8")
        self.assertIn("an@cu.com", html)
        self.assertIn("binh@cu.com", html)
        self.assertNotIn("MatKhau", html)


class TestVerifyCommand(CliTestCase):
    """Buoc kiem chung cuoi cung truoc cutover."""

    def run_verify(self, fetch_index, *extra):
        conn = mock.MagicMock()
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders), \
             mock.patch("migrate_mail.cli.open_connection", return_value=conn), \
             mock.patch("migrate_mail.verify.fetch_index", side_effect=fetch_index):
            return self.run_cli("verify", "--only", "an@cu.com", *extra)

    def test_source_is_sampled_but_destination_is_read_in_full(self):
        """Lay mau ca hai dau la sai: hai mau roi vao hai tap mail khac nhau.

        Folder hai ben gan nhu khong bao gio cung so luong, va thu tu cung
        khac (IceWarp xep theo thu tu imapsync chep sang). Phan khong giao
        nhau bi tinh thanh "thieu ben dich" -- da tung bao thieu 504 mail
        tren mot hop thu ma imapsync xac nhan la day du.
        """
        caps = []

        def fake(conn, folder, cap):
            caps.append(cap)
            return {"<a@x>": 1000.0}, 1

        _code, out = self.run_verify(fake, "--sample", "50")
        self.assertTrue(caps, out)
        self.assertEqual(set(caps), {50, 0})          # nguon 50, dich lay het
        self.assertEqual(caps.count(50), caps.count(0))

    def test_writes_a_log_file(self):
        """Truoc day verify chi in ra man hinh: chay bang screen la mat ket qua."""
        _code, out = self.run_verify(lambda c, f, cap: ({"<a@x>": 1000.0}, 1))
        files = list((self.tmp / "logs").glob("verify-*.txt"))
        self.assertEqual(len(files), 1, out)
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("Doi chieu ngay thang", text)
        self.assertIn("Ket qua:", text)
        self.assertIn("Da ghi", out)

    def test_log_is_written_even_when_nothing_could_be_compared(self):
        _code, _out = self.run_verify(lambda c, f, cap: ({}, 0))
        self.assertEqual(len(list((self.tmp / "logs").glob("verify-*.txt"))), 1)


class TestConfigErrors(CliTestCase):
    def test_missing_config_is_reported_clearly(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["--config", str(self.tmp / "khongco.ini"), "doctor"])
        self.assertEqual(code, 2)
        self.assertIn("config.example.ini", buf.getvalue())

    def test_users_csv_missing_column_is_reported(self):
        (self.tmp / "users.csv").write_text("src_user,dst_user\na@b.c,d@e.f\n", encoding="utf-8")
        code, out = self.run_cli("preflight")
        self.assertEqual(code, 2)
        self.assertIn("thieu cot", out)

    def test_duplicate_source_user_is_rejected(self):
        (self.tmp / "users.csv").write_text(
            "src_user,src_password,dst_user,dst_password\n"
            "a@b.c,pw,x@y.z,pw\na@b.c,pw,q@y.z,pw\n", encoding="utf-8")
        code, out = self.run_cli("preflight")
        self.assertEqual(code, 2)
        self.assertIn("trung", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDiscoverDest(CliTestCase):
    """`discover --dest` phai canh bao khi ten folder IceWarp khac config."""

    def run_dest(self, dest_folders):
        from migrate_mail.discover import Folder

        def fake(cfg, user, side="source", timeout=60):
            if side != "dest":
                raise AssertionError("phai hoi dau dich")
            return [Folder(raw=n, display=n, flags=set(fl), delim="/")
                    for n, fl in dest_folders]

        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake):
            return self.run_cli("discover", "--dest", "--only", "an@cu.com")

    def test_warns_when_configured_name_absent(self):
        code, out = self.run_dest([
            ("INBOX", []), ("Sent", ["sent"]), ("Drafts", ["drafts"]),
            ("Trash", ["trash"]), ("Junk E-mail", ["junk"]),
        ])
        self.assertEqual(code, 0, out)
        self.assertIn("CANH BAO", out)
        self.assertIn("junk_folder", out)          # Spam khong co -> canh bao
        self.assertNotIn("sent_folder", out)       # Sent co -> khong canh bao

    def test_no_warning_when_every_name_matches(self):
        code, out = self.run_dest([
            ("INBOX", []), ("Sent", ["sent"]), ("Drafts", ["drafts"]),
            ("Trash", ["trash"]), ("Spam", ["junk"]),
        ])
        self.assertEqual(code, 0, out)
        self.assertNotIn("CANH BAO", out)

    def test_shows_special_use_of_dest_folders(self):
        _code, out = self.run_dest([("INBOX", []), ("Junk E-mail", ["junk"]),
                                    ("Sent", ["sent"]), ("Drafts", ["drafts"]),
                                    ("Trash", ["trash"]), ("Spam", ["junk"])])
        self.assertIn("special-use: Junk", out)

    def test_login_failure_is_reported(self):
        from migrate_mail.discover import DiscoveryError

        def boom(cfg, user, side="source", timeout=60):
            raise DiscoveryError("login IceWarp that bai: Authentication failed")

        with mock.patch("migrate_mail.cli.list_folders", side_effect=boom):
            code, out = self.run_cli("discover", "--dest", "--only", "an@cu.com")
        self.assertEqual(code, 1)
        self.assertIn("Authentication failed", out)


class TestFoldersOnly(CliTestCase):
    def run_it(self, *args):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            return self.run_cli("sync", "--only", "an@cu.com", *args)

    def test_folders_only_passes_justfolders_without_dry(self):
        code, out = self.run_it("--folders-only")
        self.assertEqual(code, 0, out)
        flat = self.recorded_argv()[0]
        self.assertIn("--justfolders", flat)
        self.assertNotIn("--dry", flat)

    def test_announces_what_it_will_do(self):
        _code, out = self.run_it("--folders-only")
        self.assertIn("Chi tao cay folder", out)

    def test_folders_only_does_not_mark_mailbox_done(self):
        """Tao folder xong khong phai la da migrate -- --resume khong duoc bo qua."""
        self.run_it("--folders-only")
        self.argv_log.unlink()
        code, out = self.run_it("--resume")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.recorded_argv()), 1)

    def test_log_file_is_named_by_mode(self):
        self.run_it("--folders-only")
        self.assertTrue(list((self.tmp / "logs").glob("*.folders.*.log")))


class TestSizesCommand(CliTestCase):
    def test_sizes_action_reaches_imapsync(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            code, out = self.run_cli("sync", "--sizes", "--only", "an@cu.com")
        self.assertEqual(code, 0, out)
        flat = self.recorded_argv()[0]
        self.assertIn("--justfoldersizes", flat)
        self.assertNotIn("--nofoldersizes", flat)

    def test_announces_it_will_not_move_mail(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            _code, out = self.run_cli("sync", "--sizes", "--only", "an@cu.com")
        self.assertIn("Chi dem dung luong", out)

    def test_sizes_does_not_mark_mailbox_done(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.run_cli("sync", "--sizes", "--only", "an@cu.com")
        self.assertFalse((self.tmp / "state" / "an@cu.com" / "done.marker").exists())
