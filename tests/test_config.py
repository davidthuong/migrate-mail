# -*- coding: utf-8 -*-
"""Test doc config.ini: chon provider, kieu xac thuc, ten folder mac dinh."""

import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_mail import providers
from migrate_mail.config import load_config

MINIMAL_DEST = """
[dest]
provider = icewarp
host = mail.congty.vn
"""


class ConfigCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mm-config-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, text):
        path = self.tmp / "config.ini"
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return load_config(path)

    def assertBadConfig(self, text, needle):
        with self.assertRaises(ValueError) as ctx:
            self.load(text)
        self.assertIn(needle, str(ctx.exception))


class TestProviderChoice(ConfigCase):
    def test_defaults_stay_gmail_to_icewarp(self):
        """Ban cai cu khong co dong 'provider =' phai chay y nhu truoc."""
        cfg = self.load("""
            [source]
            host = imap.gmail.com
            [dest]
            host = mail.congty.vn
            """)
        self.assertIs(cfg.source.provider, providers.GMAIL)
        self.assertIs(cfg.dest.provider, providers.ICEWARP)

    def test_host_comes_from_the_provider_when_not_written(self):
        cfg = self.load("[source]\nprovider = m365\n" + MINIMAL_DEST)
        self.assertEqual(cfg.source.host, "outlook.office365.com")
        self.assertEqual(cfg.source.port, 993)

    def test_written_host_wins_over_the_provider_default(self):
        cfg = self.load("[source]\nprovider = zoho\nhost = imap.zoho.eu\n"
                        + MINIMAL_DEST)
        self.assertEqual(cfg.source.host, "imap.zoho.eu")

    def test_self_hosted_provider_must_declare_a_host(self):
        self.assertBadConfig("[source]\nprovider = zimbra\n" + MINIMAL_DEST,
                             "chua dat host")

    def test_unknown_provider_is_rejected_with_the_list(self):
        self.assertBadConfig("[source]\nprovider = hotmail\n" + MINIMAL_DEST,
                             "khong biet provider")

    def test_plain_connection_defaults_to_port_143(self):
        cfg = self.load("[source]\nprovider = dovecot\nhost = mail.cu.vn\n"
                        "ssl = false\n" + MINIMAL_DEST)
        self.assertEqual(cfg.source.port, 143)


class TestEncoding(ConfigCase):
    def test_config_written_by_notepad_still_loads(self):
        """Notepad va PowerShell tren Windows them BOM o dau file. Doc bang
        utf-8 tran thi BOM dinh vao ten section dau tien va configparser bao
        "File contains no section headers" -- thong bao khong dan ai toi dau."""
        path = self.tmp / "config.ini"
        path.write_text("[source]\nhost = imap.gmail.com\n" + MINIMAL_DEST,
                        encoding="utf-8-sig")
        cfg = load_config(path)
        self.assertEqual(cfg.source.host, "imap.gmail.com")


class TestAuth(ConfigCase):
    def test_password_is_the_default(self):
        cfg = self.load("[source]\nhost = imap.gmail.com\n" + MINIMAL_DEST)
        self.assertEqual(cfg.source.auth, providers.AUTH_PASSWORD)
        self.assertFalse(cfg.source.uses_oauth)

    def test_oauth_needs_the_three_app_fields(self):
        self.assertBadConfig(
            "[source]\nprovider = m365\nauth = oauth2\n" + MINIMAL_DEST,
            "oauth_tenant")

    def test_oauth_is_accepted_when_fully_declared(self):
        cfg = self.load("""
            [source]
            provider = m365
            auth = oauth2
            oauth_tenant = contoso.onmicrosoft.com
            oauth_client_id = abc
            oauth_client_secret = s3cret
            [dest]
            host = mail.congty.vn
            """)
        self.assertTrue(cfg.source.uses_oauth)
        self.assertEqual(cfg.source.oauth.tenant, "contoso.onmicrosoft.com")

    def test_secret_can_live_in_a_separate_file(self):
        """De client secret ngoai config.ini de con backup/chia se config duoc."""
        (self.tmp / "secret.txt").write_text("tu-file\n", encoding="utf-8")
        cfg = self.load("""
            [source]
            provider = m365
            auth = oauth2
            oauth_tenant = contoso.onmicrosoft.com
            oauth_client_id = abc
            oauth_client_secret_file = secret.txt
            [dest]
            host = mail.congty.vn
            """)
        self.assertEqual(cfg.source.oauth.client_secret, "tu-file")

    def test_provider_without_oauth_support_is_rejected(self):
        """Gmail khong chay duoc OAuth2 kieu app-only nhu Microsoft; bao ngay
        con hon de nguoi dung ngoi doi mot lan sync that bai het."""
        self.assertBadConfig(
            "[source]\nprovider = gmail\nauth = oauth2\n" + MINIMAL_DEST,
            "khong dung duoc auth")

    def test_nonsense_auth_is_rejected(self):
        self.assertBadConfig(
            "[source]\nhost = imap.gmail.com\nauth = kerberos\n" + MINIMAL_DEST,
            "auth phai la")


class TestFolderDefaults(ConfigCase):
    def test_destination_provider_names_the_junk_folder(self):
        cfg = self.load("[source]\nhost = imap.gmail.com\n"
                        "[dest]\nprovider = icewarp\nhost = mail.congty.vn\n")
        self.assertEqual(cfg.sync.junk_folder, "Spam")

    def test_moving_into_exchange_uses_outlook_names(self):
        cfg = self.load("[source]\nhost = imap.gmail.com\n"
                        "[dest]\nprovider = m365\n")
        self.assertEqual(cfg.sync.junk_folder, "Junk Email")
        self.assertEqual(cfg.sync.trash_folder, "Deleted Items")

    def test_config_still_overrides_the_provider(self):
        cfg = self.load("[source]\nhost = imap.gmail.com\n"
                        "[dest]\nprovider = m365\n"
                        "[sync]\njunk_folder = Rac\n")
        self.assertEqual(cfg.sync.junk_folder, "Rac")

    def test_archive_is_left_alone_by_default(self):
        """De trong = giu nguyen ten folder luu tru cua nguon."""
        cfg = self.load("[source]\nhost = imap.gmail.com\n" + MINIMAL_DEST)
        self.assertEqual(cfg.sync.archive_folder, "")


class TestPrefix(ConfigCase):
    def test_auto_detect_is_the_default_on_both_sides(self):
        cfg = self.load("[source]\nprovider = courier\nhost = mail.cu.vn\n"
                        + MINIMAL_DEST)
        self.assertTrue(cfg.source.detect_prefix)
        self.assertTrue(cfg.dest.detect_prefix)
        self.assertEqual(cfg.source.fixed_prefix, "")

    def test_none_turns_detection_off(self):
        cfg = self.load("[source]\nprovider = courier\nhost = mail.cu.vn\n"
                        "prefix = none\n" + MINIMAL_DEST)
        self.assertFalse(cfg.source.detect_prefix)
        self.assertEqual(cfg.source.fixed_prefix, "")

    def test_a_written_prefix_wins_over_detection(self):
        """Escape hatch cho server tra ve NAMESPACE sai hoac khong tra ve."""
        cfg = self.load("[source]\nprovider = courier\nhost = mail.cu.vn\n"
                        "prefix = INBOX.\n" + MINIMAL_DEST)
        self.assertFalse(cfg.source.detect_prefix)
        self.assertEqual(cfg.source.fixed_prefix, "INBOX.")

    def test_destination_takes_a_prefix_too(self):
        cfg = self.load("[source]\nhost = imap.gmail.com\n"
                        "[dest]\nprovider = dovecot\nhost = moi.vn\n"
                        "prefix = INBOX.\n")
        self.assertEqual(cfg.dest.fixed_prefix, "INBOX.")


MASTER_SOURCE = """
[source]
provider = dovecot
host = mail.cu.vn
auth = master
master_user = migrate
master_password = BiMat
"""


class TestMasterAuth(ConfigCase):
    def test_master_account_is_read(self):
        cfg = self.load(MASTER_SOURCE + MINIMAL_DEST)
        self.assertTrue(cfg.source.uses_master)
        self.assertEqual(cfg.source.master.user, "migrate")
        self.assertEqual(cfg.source.master.password, "BiMat")
        # Khong khai bao thi di duong chuan, khong phai kieu rieng cua Dovecot.
        self.assertEqual(cfg.source.master.style, "authzid")

    def test_mailbox_password_is_not_required_on_a_master_side(self):
        """Day la ca ly do ton tai cua auth = master: khong phai di xin mat
        khau cua tung nguoi nua."""
        cfg = self.load(MASTER_SOURCE + MINIMAL_DEST)
        self.assertFalse(cfg.source.needs_mailbox_password)
        self.assertTrue(cfg.dest.needs_mailbox_password)

    def test_authzid_keeps_the_mailbox_and_the_admin_apart(self):
        cfg = self.load(MASTER_SOURCE + MINIMAL_DEST)
        login = cfg.source.login_for("an@cu.vn", "")
        self.assertEqual(login.user, "an@cu.vn")     # hop thu can mo
        self.assertEqual(login.authuser, "migrate")  # tai khoan dang nhap
        self.assertEqual(login.password, "BiMat")
        self.assertTrue(login.via_authzid)

    def test_separator_style_glues_the_two_names_together(self):
        cfg = self.load(MASTER_SOURCE + "master_style = separator\n" + MINIMAL_DEST)
        login = cfg.source.login_for("an@cu.vn", "")
        self.assertEqual(login.user, "an@cu.vn*migrate")
        self.assertEqual(login.password, "BiMat")
        # Kieu nay di bang LOGIN thuong, khong co danh tinh thu hai.
        self.assertFalse(login.via_authzid)

    def test_separator_can_be_changed(self):
        cfg = self.load(MASTER_SOURCE + "master_style = separator\n"
                        "master_separator = %\n" + MINIMAL_DEST)
        self.assertEqual(cfg.source.login_for("an@cu.vn", "").user, "an@cu.vn%migrate")

    def test_quoted_separator_keeps_only_the_character(self):
        """De nguoi doc config nhin ro dau phan cach la gi khi no la ky tu
        de lan voi khoang trang."""
        cfg = self.load(MASTER_SOURCE + "master_style = separator\n"
                        'master_separator = "*"\n' + MINIMAL_DEST)
        self.assertEqual(cfg.source.login_for("an@cu.vn", "").user, "an@cu.vn*migrate")

    def test_password_can_live_in_its_own_file(self):
        (self.tmp / "master-pass.txt").write_text("TuFile\n", encoding="utf-8")
        cfg = self.load("[source]\nprovider = dovecot\nhost = mail.cu.vn\n"
                        "auth = master\nmaster_user = migrate\n"
                        "master_password_file = master-pass.txt\n" + MINIMAL_DEST)
        self.assertEqual(cfg.source.master.password, "TuFile")

    def test_password_with_a_percent_sign_survives(self):
        """configparser mac dinh coi '%' la cu phap thay the va nem loi khong
        he nhac den mat khau. Mat khau that thi rat hay co ky tu nay."""
        cfg = self.load("[source]\nprovider = dovecot\nhost = mail.cu.vn\n"
                        "auth = master\nmaster_user = migrate\n"
                        "master_password = a%b100%\n" + MINIMAL_DEST)
        self.assertEqual(cfg.source.master.password, "a%b100%")

    def test_missing_password_file_names_the_key_that_is_wrong(self):
        self.assertBadConfig(
            "[source]\nprovider = dovecot\nhost = mail.cu.vn\nauth = master\n"
            "master_user = migrate\nmaster_password_file = khong-co.txt\n"
            + MINIMAL_DEST,
            "master_password_file")

    def test_master_without_an_account_is_rejected_at_load_time(self):
        """Bao ngay luc doc config chu khong de hong o mailbox dau tien."""
        self.assertBadConfig(
            "[source]\nprovider = dovecot\nhost = mail.cu.vn\nauth = master\n"
            + MINIMAL_DEST,
            "master_user, master_password")

    def test_provider_without_master_support_is_rejected(self):
        self.assertBadConfig(
            "[source]\nprovider = gmail\nauth = master\n"
            "master_user = migrate\nmaster_password = x\n" + MINIMAL_DEST,
            "khong dung duoc auth")

    def test_nonsense_style_is_rejected(self):
        self.assertBadConfig(
            MASTER_SOURCE + "master_style = magic\n" + MINIMAL_DEST,
            "master_style phai la")

    def test_empty_separator_is_rejected_when_the_style_needs_one(self):
        self.assertBadConfig(
            MASTER_SOURCE + "master_style = separator\nmaster_separator =\n"
            + MINIMAL_DEST,
            "master_separator")

    def test_destination_can_run_master_too(self):
        """Ca hay dung nhat: minh la nguoi quan tri server DICH."""
        cfg = self.load("[source]\nhost = imap.gmail.com\n"
                        "[dest]\nprovider = dovecot\nhost = moi.vn\n"
                        "auth = master\nmaster_user = migrate\n"
                        "master_password = BiMat\n")
        self.assertTrue(cfg.dest.uses_master)
        self.assertFalse(cfg.dest.needs_mailbox_password)
        self.assertTrue(cfg.source.needs_mailbox_password)

    def test_password_auth_ignores_a_leftover_master_block(self):
        """Doi auth ve password ma quen xoa may dong master_* thi van chay
        bang mat khau cua tung hop thu."""
        cfg = self.load("[source]\nprovider = dovecot\nhost = mail.cu.vn\n"
                        "auth = password\nmaster_user = migrate\n"
                        "master_password = BiMat\n" + MINIMAL_DEST)
        login = cfg.source.login_for("an@cu.vn", "MatKhauCuaAn")
        self.assertEqual(login.user, "an@cu.vn")
        self.assertEqual(login.password, "MatKhauCuaAn")
        self.assertFalse(login.via_authzid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
