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

    def test_master_auth_says_it_is_not_built_yet(self):
        self.assertBadConfig(
            "[source]\nprovider = dovecot\nhost = mail.cu.vn\nauth = master\n"
            + MINIMAL_DEST,
            "chua duoc hien thuc")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
