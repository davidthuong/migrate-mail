# -*- coding: utf-8 -*-
"""Test cho mailboxes.py va lenh mkusers.

Du lieu mau la nhung kieu file thuc te nhan duoc tu admin ben nguon: Export-Csv
con dong #TYPE, file UTF-16 cua PowerShell, danh sach dia chi tho, va CSV dat
ten cot khong theo chuan nao.
"""

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from migrate_mail import cli, mailboxes
from migrate_mail.users import load_users

# Export-Csv cua PowerShell 5.1 khi quen -NoTypeInformation.
EXPORT_CSV = (
    '#TYPE Selected.Microsoft.Exchange.Data.Directory.Management.Mailbox\r\n'
    '"PrimarySmtpAddress","DisplayName","RecipientTypeDetails","ArchiveStatus"\r\n'
    '"an.nguyen@cu.com","An Nguyen","UserMailbox","Active"\r\n'
    '"binh.tran@cu.com","Binh Tran","UserMailbox","None"\r\n'
    '"ketoan@cu.com","Ke toan","SharedMailbox","None"\r\n'
    '"phonghop1@cu.com","Phong hop 1","RoomMailbox","None"\r\n'
    '"may.chieu@cu.com","May chieu","EquipmentMailbox","None"\r\n'
    '"DiscoverySearch@cu.onmicrosoft.com","Discovery","DiscoveryMailbox","None"\r\n'
)


class TestParse(unittest.TestCase):
    def test_reads_export_csv_with_type_line(self):
        p = mailboxes.parse(EXPORT_CSV)
        self.assertEqual([m.address for m in p.mailboxes],
                         ["an.nguyen@cu.com", "binh.tran@cu.com", "ketoan@cu.com"])
        self.assertEqual(p.address_column, "PrimarySmtpAddress")
        self.assertEqual(p.rows_read, 6)

    def test_keeps_shared_mailbox(self):
        # Hop thu dung chung co mail that va thuong la thu khach hang quen
        # nhat khi liet ke tay.
        p = mailboxes.parse(EXPORT_CSV)
        self.assertIn("ketoan@cu.com", [m.address for m in p.mailboxes])

    def test_skips_types_without_mail_and_says_why(self):
        p = mailboxes.parse(EXPORT_CSV)
        skipped = dict(p.skipped)
        self.assertIn("phonghop1@cu.com", skipped)
        self.assertIn("phong hop", skipped["phonghop1@cu.com"])
        self.assertIn("may.chieu@cu.com", skipped)
        self.assertIn("DiscoverySearch@cu.onmicrosoft.com", skipped)

    def test_keep_all_types_keeps_them(self):
        p = mailboxes.parse(EXPORT_CSV, keep_all_types=True)
        self.assertEqual(len(p.mailboxes), 6)
        self.assertEqual(p.skipped, [])

    def test_unknown_type_is_kept_not_dropped(self):
        # Bo nham mot mailbox that thi khong ai thay; giu nham mot mailbox rong
        # thi preflight bao ngay. Nen loai la phai duoc giu.
        text = ("PrimarySmtpAddress,RecipientTypeDetails\n"
                "la@cu.com,MotLoaiMoiCuaMicrosoft\n")
        p = mailboxes.parse(text)
        self.assertEqual([m.address for m in p.mailboxes], ["la@cu.com"])
        self.assertEqual(p.mailboxes[0].kind, "MotLoaiMoiCuaMicrosoft")

    def test_duplicate_address_taken_once(self):
        text = ("PrimarySmtpAddress\nan@cu.com\nAN@CU.COM\n")
        p = mailboxes.parse(text)
        self.assertEqual(len(p.mailboxes), 1)
        self.assertIn("trung voi dong 1", dict(p.skipped)["AN@CU.COM"])

    def test_domain_filter(self):
        p = mailboxes.parse(EXPORT_CSV, keep_all_types=True, domains=["cu.com"])
        self.assertEqual(len(p.mailboxes), 5)
        self.assertIn("khong thuoc domain",
                      dict(p.skipped)["DiscoverySearch@cu.onmicrosoft.com"])

    def test_domain_filter_accepts_at_prefix(self):
        p = mailboxes.parse(EXPORT_CSV, domains=["@CU.COM"])
        self.assertEqual(len(p.mailboxes), 3)

    def test_plain_address_list(self):
        p = mailboxes.parse("an@cu.com\nbinh@cu.com\n\n  chi@cu.com  \n")
        self.assertEqual([m.address for m in p.mailboxes],
                         ["an@cu.com", "binh@cu.com", "chi@cu.com"])

    def test_semicolon_delimiter(self):
        p = mailboxes.parse("PrimarySmtpAddress;RecipientTypeDetails\n"
                            "an@cu.com;UserMailbox\n")
        self.assertEqual([m.address for m in p.mailboxes], ["an@cu.com"])

    def test_unknown_column_names_are_guessed_and_announced(self):
        p = mailboxes.parse("Ten;Hop thu;Ghi chu\n"
                            "An;an@cu.com;abc\nBinh;binh@cu.com;xyz\n")
        self.assertEqual([m.address for m in p.mailboxes],
                         ["an@cu.com", "binh@cu.com"])
        self.assertTrue(any("cot thu 2" in w for w in p.warnings))

    def test_address_extracted_from_display_name_and_smtp_prefix(self):
        p = mailboxes.parse('EmailAddresses\n'
                            '"SMTP:an@cu.com,smtp:an.cu@cu.com"\n'
                            'Binh Tran <binh@cu.com>\n')
        self.assertEqual([m.address for m in p.mailboxes],
                         ["an@cu.com", "binh@cu.com"])

    def test_row_without_address_is_reported_not_silently_dropped(self):
        p = mailboxes.parse("PrimarySmtpAddress,DisplayName\n"
                            "an@cu.com,An\n,Khong co dia chi\n")
        self.assertEqual(len(p.mailboxes), 1)
        self.assertEqual(len(p.skipped), 1)
        self.assertIn("khong tim thay dia chi", p.skipped[0][1])

    def test_file_without_any_address_explains_the_command(self):
        with self.assertRaises(mailboxes.MailboxListError) as ctx:
            mailboxes.parse("Name Alias Database\nAn an EX01\n")
        self.assertIn("Get-Mailbox", str(ctx.exception))

    def test_empty_file(self):
        with self.assertRaises(mailboxes.MailboxListError):
            mailboxes.parse("\n\n")

    def test_header_only(self):
        with self.assertRaises(mailboxes.MailboxListError):
            mailboxes.parse("PrimarySmtpAddress,DisplayName\n")


class TestArchive(unittest.TestCase):
    def test_archive_status_active(self):
        p = mailboxes.parse(EXPORT_CSV)
        self.assertEqual([m.address for m in p.archived], ["an.nguyen@cu.com"])
        self.assertTrue(any("Online Archive" in w for w in p.warnings))

    def test_empty_archive_guid_is_not_an_archive(self):
        p = mailboxes.parse("PrimarySmtpAddress,ArchiveGuid\n"
                            "an@cu.com,00000000-0000-0000-0000-000000000000\n"
                            "binh@cu.com,3f2504e0-4f89-11d3-9a0c-0305e82c3301\n")
        self.assertEqual([m.address for m in p.archived], ["binh@cu.com"])

    def test_missing_archive_column_is_warned_about(self):
        # Khong co cot do nghia la khong biet, va "khong biet" phai noi ra:
        # Archive khong di qua IMAP nen day la thu phai bao khach truoc.
        p = mailboxes.parse("PrimarySmtpAddress\nan@cu.com\n")
        self.assertTrue(any("ArchiveStatus" in w for w in p.warnings))

    def test_onmicrosoft_addresses_are_flagged(self):
        p = mailboxes.parse("PrimarySmtpAddress\nan@cu.onmicrosoft.com\n")
        self.assertTrue(any("onmicrosoft.com" in w for w in p.warnings))


class TestDecode(unittest.TestCase):
    def test_utf8_with_bom(self):
        raw = "PrimarySmtpAddress\nan@cu.com\n".encode("utf-8-sig")
        self.assertEqual(mailboxes.decode(raw).splitlines()[0],
                         "PrimarySmtpAddress")

    def test_utf16_with_bom(self):
        raw = "PrimarySmtpAddress\r\nan@cu.com\r\n".encode("utf-16")
        p = mailboxes.parse(mailboxes.decode(raw))
        self.assertEqual([m.address for m in p.mailboxes], ["an@cu.com"])

    def test_utf16le_without_bom(self):
        # `>` cua PowerShell 5.1: doc bang utf-8 khong bao loi ma ra rac.
        raw = "PrimarySmtpAddress\r\nan@cu.com\r\n".encode("utf-16-le")
        p = mailboxes.parse(mailboxes.decode(raw))
        self.assertEqual([m.address for m in p.mailboxes], ["an@cu.com"])

    def test_cp1252_fallback_does_not_raise(self):
        raw = b"PrimarySmtpAddress,DisplayName\nan@cu.com,Nguy\xean\n"
        self.assertIn("an@cu.com", mailboxes.decode(raw))


class TestPasswords(unittest.TestCase):
    def test_length_and_character_classes(self):
        pw = mailboxes.gen_password()
        self.assertEqual(len(pw), 16)
        for pool in mailboxes._PW_POOLS:
            self.assertTrue(any(c in pool for c in pw), pw)

    def test_no_characters_that_break_csv_or_reading(self):
        for _ in range(200):
            pw = mailboxes.gen_password()
            for bad in ',"\' \t01OIl':
                self.assertNotIn(bad, pw)

    def test_passwords_differ(self):
        self.assertEqual(len({mailboxes.gen_password() for _ in range(50)}), 50)

    def test_short_length_still_has_every_class(self):
        pw = mailboxes.gen_password(2)
        self.assertEqual(len(pw), len(mailboxes._PW_POOLS))


class TestRows(unittest.TestCase):
    def setUp(self):
        self.boxes = mailboxes.parse(EXPORT_CSV).mailboxes

    def test_dest_domain_replaces_only_the_domain(self):
        self.assertEqual(mailboxes.dest_address("an.nguyen@cu.com", "moi.vn"),
                         "an.nguyen@moi.vn")
        self.assertEqual(mailboxes.dest_address("an@cu.com", "@MOI.VN"),
                         "an@moi.vn")

    def test_no_domain_keeps_address(self):
        self.assertEqual(mailboxes.dest_address("an@cu.com"), "an@cu.com")

    def test_rows_generate_one_password_each(self):
        rows = mailboxes.build_rows(self.boxes)
        self.assertEqual(len({r[3] for r in rows}), len(rows))

    def test_fixed_password(self):
        rows = mailboxes.build_rows(self.boxes, dst_password="Chung1")
        self.assertEqual({r[3] for r in rows}, {"Chung1"})

    def test_blank_passwords(self):
        rows = mailboxes.build_rows(self.boxes, blank_passwords=True)
        self.assertEqual({r[3] for r in rows}, {""})


class TestWriteUsers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmtest-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_written_file_is_readable_by_load_users(self):
        boxes = mailboxes.parse(EXPORT_CSV).mailboxes
        rows = mailboxes.build_rows(boxes, dst_domain="moi.vn")
        path = mailboxes.write_users(self.tmp / "users.csv", rows,
                                     ["ghi chu mot dong"])
        users = load_users(path, need_src_password=False)
        self.assertEqual([u.dst_user for u in users],
                         ["an.nguyen@moi.vn", "binh.tran@moi.vn", "ketoan@moi.vn"])

    def test_note_lines_are_comments(self):
        path = mailboxes.write_users(self.tmp / "users.csv",
                                     [["a@cu.com", "", "a@moi.vn", "x"]],
                                     ["sinh luc hom nay", ""])
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# sinh luc hom nay\n#\n"))
        self.assertIn("src_user,src_password,dst_user,dst_password", text)


CONFIG = """[source]
provider = m365
auth = oauth2
oauth_tenant = contoso.onmicrosoft.com
oauth_client_id = 1111-2222
oauth_client_secret = bimat

[dest]
provider = icewarp
host = mail.congty.vn
"""

CONFIG_PASSWORD = """[source]
provider = dovecot
host = mail.cu.com

[dest]
provider = icewarp
host = mail.congty.vn
"""


class TestMkusersCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmtest-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = self.tmp / "config.ini"
        self.config.write_text(CONFIG, encoding="utf-8")
        self.source = self.tmp / "mailboxes.csv"
        self.source.write_text(EXPORT_CSV, encoding="utf-8")
        self.out = self.tmp / "users.csv"

    def run_cli(self, *args):
        base = ["--config", str(self.config), "--users", str(self.out)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(base + ["mkusers", str(self.source)] + list(args))
        return code, buf.getvalue()

    def test_writes_users_csv_to_the_default_path(self):
        code, out = self.run_cli("--dst-domain", "congty.vn")
        self.assertEqual(code, 0, out)
        users = load_users(self.out, need_src_password=False)
        self.assertEqual([u.src_user for u in users],
                         ["an.nguyen@cu.com", "binh.tran@cu.com", "ketoan@cu.com"])
        self.assertEqual(users[0].dst_user, "an.nguyen@congty.vn")

    def test_output_names_what_was_skipped(self):
        _code, out = self.run_cli()
        self.assertIn("phonghop1@cu.com", out)
        self.assertIn("phong hop", out)
        self.assertIn("LAY 3 mailbox", out)

    def test_output_warns_about_online_archive(self):
        _code, out = self.run_cli()
        self.assertIn("Online Archive", out)

    def test_existing_file_is_not_overwritten_without_force(self):
        self.out.write_text("dung dung vao\n", encoding="utf-8")
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("da ton tai", out)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "dung dung vao\n")

    def test_force_overwrites(self):
        self.out.write_text("cu\n", encoding="utf-8")
        code, out = self.run_cli("--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(load_users(self.out, need_src_password=False)), 3)

    def test_oauth_source_leaves_src_password_empty(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertIn("cot src_password de trong la dung", out)
        self.assertIn(",,", self.out.read_text(encoding="utf-8"))

    def test_password_source_says_the_column_must_be_filled(self):
        self.config.write_text(CONFIG_PASSWORD, encoding="utf-8")
        _code, out = self.run_cli()
        self.assertIn("phai dien cot src_password tay", out)

    def test_blank_and_fixed_password_together_is_refused(self):
        code, out = self.run_cli("--blank-passwords", "--dst-password", "x")
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())
        self.assertIn("chon mot cai", out)

    def test_unreadable_input_is_an_error_not_a_traceback(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["--config", str(self.config),
                             "--users", str(self.out),
                             "mkusers", str(self.tmp / "khong-co.csv")])
        self.assertEqual(code, 2)
        self.assertIn("khong doc duoc", buf.getvalue())

    def test_bad_input_reports_the_command_to_run(self):
        self.source.write_text("Name Alias Database\nAn an EX01\n",
                               encoding="utf-8")
        code, out = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("Get-Mailbox", out)

    def test_no_mailbox_left_after_filtering_writes_nothing(self):
        code, out = self.run_cli("--domain", "khong-ton-tai.com")
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())
        self.assertIn("khong ghi file", out)


if __name__ == "__main__":
    unittest.main()
