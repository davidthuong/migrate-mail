# -*- coding: utf-8 -*-
"""Test phan lay OAuth2 token cua Microsoft va cach no di vao lenh imapsync."""

import io
import json
import os
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_mail import oauth, providers
from migrate_mail.config import Config, Paths, ServerConf, SyncConf
from migrate_mail.oauth import OAuthConf, OAuthError, TokenSource
from migrate_mail.runner import MODE_SYNC, _redact, build_command
from migrate_mail.users import User

CONF = OAuthConf(tenant="contoso.onmicrosoft.com", client_id="abc",
                 client_secret="s3cret")
USER = User("an@contoso.com", "", "an@moi.vn", "MatKhauDich", row=2)


def _response(payload):
    body = json.dumps(payload).encode("utf-8")
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestConf(unittest.TestCase):
    def test_reports_every_missing_field_at_once(self):
        missing = OAuthConf().missing()
        self.assertEqual(set(missing), {"tenant", "client_id", "client_secret"})

    def test_token_url_uses_the_v2_endpoint(self):
        self.assertEqual(
            CONF.token_url,
            "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token")

    def test_default_scope_is_the_imap_resource(self):
        self.assertIn("outlook.office365.com", CONF.scope)


class TestRequestToken(unittest.TestCase):
    def test_returns_token_and_lifetime(self):
        with mock.patch("migrate_mail.oauth.urllib.request.urlopen",
                        return_value=_response({"access_token": "T", "expires_in": 3599})):
            token, expires = oauth.request_token(CONF)
        self.assertEqual(token, "T")
        self.assertEqual(expires, 3599)

    def test_sends_client_credentials_grant(self):
        with mock.patch("migrate_mail.oauth.urllib.request.urlopen",
                        return_value=_response({"access_token": "T"})) as call:
            oauth.request_token(CONF)
        body = call.call_args[0][0].data.decode()
        self.assertIn("grant_type=client_credentials", body)
        self.assertIn("client_id=abc", body)

    def test_missing_config_is_caught_before_the_network(self):
        with self.assertRaises(OAuthError) as ctx:
            oauth.request_token(OAuthConf(tenant="x"))
        self.assertIn("client_id", str(ctx.exception))

    def test_keeps_the_aadsts_code_from_microsoft(self):
        """Ma AADSTS la thu duy nhat tra cuu duoc; nuot no di thi nguoi dung
        chi thay "HTTP 401" va khong biet phai sua cai gi."""
        payload = json.dumps({
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided."
        }).encode()
        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {},
                                     io.BytesIO(payload))
        with mock.patch("migrate_mail.oauth.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(OAuthError) as ctx:
                oauth.request_token(CONF)
        self.assertIn("AADSTS7000215", str(ctx.exception))

    def test_reply_without_a_token_is_an_error(self):
        with mock.patch("migrate_mail.oauth.urllib.request.urlopen",
                        return_value=_response({"token_type": "Bearer"})):
            with self.assertRaises(OAuthError):
                oauth.request_token(CONF)


class TestTokenSource(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.clock = [1000.0]

    def fetch(self, conf):
        self.calls.append(conf)
        return "token-%d" % len(self.calls), 3600

    def source(self):
        return TokenSource(CONF, fetch=self.fetch, now=lambda: self.clock[0])

    def test_token_is_fetched_once_and_reused(self):
        src = self.source()
        self.assertEqual(src.token(), "token-1")
        self.assertEqual(src.token(), "token-1")
        self.assertEqual(len(self.calls), 1)

    def test_token_is_renewed_before_it_expires(self):
        """Mot lan sync chay hang gio; token het han giua chung se lam hong
        cac mailbox chay sau chu khong bao loi ngay."""
        src = self.source()
        src.token()
        self.clock[0] += 3600 - oauth.REFRESH_MARGIN + 1
        self.assertEqual(src.token(), "token-2")

    def test_invalidate_forces_a_new_token(self):
        src = self.source()
        src.token()
        src.invalidate()
        self.assertEqual(src.token(), "token-2")

    def test_one_source_is_shared_by_every_mailbox(self):
        """Token cua client_credentials khong gan voi mailbox nao, nen 20 hop
        chay song song chi can mot lan goi Microsoft."""
        a = oauth.source_for(CONF)
        b = oauth.source_for(OAuthConf(tenant=CONF.tenant, client_id=CONF.client_id,
                                       client_secret=CONF.client_secret))
        self.assertIs(a, b)

    def test_changing_the_secret_starts_a_new_source(self):
        a = oauth.source_for(CONF)
        b = oauth.source_for(OAuthConf(tenant=CONF.tenant, client_id=CONF.client_id,
                                       client_secret="da-doi"))
        self.assertIsNot(a, b)


class TestXoauth2(unittest.TestCase):
    def test_builds_the_sasl_string(self):
        raw = oauth.xoauth2("an@contoso.com", "T")
        self.assertEqual(raw, b"user=an@contoso.com\x01auth=Bearer T\x01\x01")


def oauth_cfg():
    source = ServerConf("outlook.office365.com", 993, True,
                        provider=providers.M365, auth=providers.AUTH_OAUTH2,
                        oauth=CONF)
    return Config(
        source=source,
        dest=ServerConf("mail.congty.vn", 993, True, provider=providers.ICEWARP),
        sync=SyncConf(),
        paths=Paths(imapsync="imapsync", logdir=Path("logs"), statedir=Path("state")),
        path=Path("config.ini"),
    )


class TestCommandLine(unittest.TestCase):
    def cmd(self):
        return build_command(oauth_cfg(), USER, None, MODE_SYNC,
                             Path("/s/src.pass"), Path("/s/dst.pass"), Path("/s"),
                             0, Path("/s/src.token"), Path("/s/dst.token"))

    def test_source_uses_a_token_file_instead_of_a_passfile(self):
        cmd = self.cmd()
        self.assertNotIn("--passfile1", cmd)
        self.assertIn("--oauthaccesstoken1", cmd)
        pairs = list(zip(cmd, cmd[1:]))
        self.assertIn(("--oauthaccesstoken1", str(Path("/s/src.token"))), pairs)

    def test_destination_still_uses_a_password(self):
        cmd = self.cmd()
        self.assertIn("--passfile2", cmd)
        self.assertNotIn("--oauthaccesstoken2", cmd)

    def test_token_path_is_redacted_in_the_log(self):
        """File token la bi mat song, khong duoc de duong dan cua no nam lai
        trong dong lenh ghi vao log."""
        redacted = _redact(self.cmd())
        self.assertNotIn(str(Path("/s/src.token")), redacted)
        self.assertIn("<passfile>", redacted)

    def test_doctor_only_checks_oauth_flags_when_oauth_is_used(self):
        from migrate_mail.runner import flags_used
        from test_runner import make_cfg
        self.assertIn("--oauthaccesstoken1", flags_used(oauth_cfg()))
        self.assertNotIn("--oauthaccesstoken1", flags_used(make_cfg()))


class TestVersionGate(unittest.TestCase):
    """--oauthaccesstoken1 co tu imapsync 2.113, nhung truoc 2.251 no van doi
    co --password1 di kem. Doi chieu ten tuy chon khong thay duoc chuyen do,
    nen doctor phai nhin ca so phien ban."""

    def check(self, version_text):
        from migrate_mail import cli
        lines = []
        with mock.patch("migrate_mail.runner.imapsync_run", return_value=version_text), \
             mock.patch("migrate_mail.cli.check_permissions", return_value=""), \
             mock.patch("migrate_mail.oauth.request_token", return_value=("T", 3600)), \
             cli.capture(lines.append):
            problems = cli._check_oauth(oauth_cfg())
        return problems, "\n".join(lines)

    def test_old_version_is_reported(self):
        problems, out = self.check("2.229\n")
        self.assertEqual(problems, 1)
        self.assertIn("2.251", out)

    def test_new_enough_version_passes(self):
        problems, out = self.check("2.314\n")
        self.assertEqual(problems, 0)
        self.assertIn("lay duoc token", out)

    def test_password_auth_skips_the_check_entirely(self):
        from migrate_mail import cli
        from test_runner import make_cfg
        lines = []
        with cli.capture(lines.append):
            self.assertEqual(cli._check_oauth(make_cfg()), 0)
        self.assertEqual(lines, [])


class TestTokenFileStaysFresh(unittest.TestCase):
    """imapsync doc lai file token moi lan no ket noi lai giua chung, nen file
    phai con han suot ca lan chay chu khong chi luc khoi dong."""

    def test_refresher_rewrites_the_file_while_the_run_is_going(self):
        import tempfile
        from migrate_mail import runner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "src.token"
            server = oauth_cfg().source
            runner._write_secret(path, "cu")

            values = iter(["moi-1", "moi-2"])
            fake = mock.MagicMock()
            fake.token.side_effect = lambda: next(values)
            with mock.patch.object(runner, "TOKEN_CHECK_SECONDS", 0.01), \
                 mock.patch.object(runner.oauth, "source_for", return_value=fake):
                with runner._TokenRefresher([(server, path)]):
                    for _ in range(200):
                        if path.read_text(encoding="utf-8") != "cu":
                            break
                        time.sleep(0.01)
            self.assertTrue(path.read_text(encoding="utf-8").startswith("moi-"))

    def test_a_failed_refresh_leaves_the_old_token_in_place(self):
        """Mot lan goi mang hong khong duoc phep lam hong ca lan sync -- ban
        token dang nam tren dia van con dung duoc them mot luc."""
        import tempfile
        from migrate_mail import runner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "src.token"
            runner._write_secret(path, "con-han")
            with mock.patch.object(runner, "TOKEN_CHECK_SECONDS", 0.01), \
                 mock.patch.object(runner.oauth, "source_for",
                                   side_effect=OAuthError("mang hong")):
                with runner._TokenRefresher([(oauth_cfg().source, path)]):
                    time.sleep(0.1)
            self.assertEqual(path.read_text(encoding="utf-8"), "con-han")

    def test_writing_a_secret_is_atomic(self):
        """Ghi de bang xoa-roi-tao-lai se de lo mot khoang file khong ton tai;
        imapsync doc dung luc do se that bai xac thuc."""
        import tempfile
        from migrate_mail.runner import _write_secret

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "src.token"
            _write_secret(path, "mot")
            seen = []

            real_replace = os.replace

            def watching_replace(src, dst):
                seen.append(Path(dst).exists())
                return real_replace(src, dst)

            with mock.patch("migrate_mail.runner.os.replace", watching_replace):
                _write_secret(path, "hai")
            self.assertEqual(seen, [True])       # file cu van con luc doi cho
            self.assertEqual(path.read_text(encoding="utf-8"), "hai")


if __name__ == "__main__":
    unittest.main(verbosity=2)
