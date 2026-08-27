# -*- coding: utf-8 -*-
"""Test dashboard web: phan quyen, khong lo mat khau, chay job, them mailbox."""

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from migrate_mail import web
from migrate_mail.config import load_config

from test_cli import CONFIG, USERS, quote
from test_discover import GMAIL_EN, parse

FAKE = HERE / "fake_imapsync.py"


def fake_folders(cfg, user, side="source", timeout=60):
    if "loi" in user.src_user:
        from migrate_mail.discover import DiscoveryError
        raise DiscoveryError("login that bai")
    return parse(GMAIL_EN)


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmweb-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        imapsync = "%s %s" % (quote(sys.executable), quote(FAKE))
        (self.tmp / "config.ini").write_text(
            CONFIG.format(imapsync=imapsync), encoding="utf-8")
        self.users_path = self.tmp / "users.csv"
        self.users_path.write_text(USERS, encoding="utf-8")

        cfg = load_config(self.tmp / "config.ini")
        self.token = "test-token-abcdefghijklmnop"
        web.Handler.manager = web.JobManager(cfg, self.users_path)
        web.Handler.token = self.token
        web.Handler.users_path = self.users_path

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        # addCleanup chay nguoc thu tu dang ky: dang ky close truoc de no
        # chay sau shutdown, neu khong se shutdown tren socket da dong.
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def get(self, path, token=True):
        req = urllib.request.Request(self.url(path))
        if token:
            req.add_header("Cookie", "mmtoken=" + self.token)
        return urllib.request.urlopen(req, timeout=10)

    def post(self, path, payload, token=True):
        req = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        if token:
            req.add_header("Cookie", "mmtoken=" + self.token)
        return urllib.request.urlopen(req, timeout=30)

    def state(self, attempts=4):
        """Doc trang thai. Thu lai vai lan vi test poll rat day, thinh thoang
        gap mot ket noi bi dut giua chung -- do la nhieu cua test, khong phai
        loi cua server."""
        last = None
        for i in range(attempts):
            try:
                return json.loads(self.get("/api/state").read().decode("utf-8"))
            except (ValueError, OSError, urllib.error.URLError) as exc:
                last = exc
                time.sleep(0.15 * (i + 1))
        raise AssertionError("khong doc duoc /api/state: %s" % last)


class TestAuth(WebTestCase):
    def test_api_refuses_without_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/state", token=False)
        self.assertEqual(ctx.exception.code, 401)

    def test_api_refuses_wrong_token(self):
        req = urllib.request.Request(self.url("/api/state"))
        req.add_header("Cookie", "mmtoken=sai-token")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 401)

    def test_page_refuses_without_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/", token=False)
        self.assertEqual(ctx.exception.code, 401)

    def test_page_served_with_cookie(self):
        body = self.get("/").read().decode("utf-8")
        self.assertIn("migrate-mail", body)
        self.assertIn("<table>", body)

    def test_token_in_query_sets_cookie_and_redirects(self):
        """Token chi dung mot lan de dat cookie, roi bien khoi thanh dia chi."""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(self.url("/?t=" + self.token), timeout=10)
            self.fail("le ra phai chuyen huong")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            self.assertEqual(exc.headers.get("Location"), "/")
            self.assertIn("mmtoken=" + self.token, exc.headers.get("Set-Cookie"))
            self.assertIn("HttpOnly", exc.headers.get("Set-Cookie"))

    def test_post_refuses_without_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/run", {"action": "sync"}, token=False)
        self.assertEqual(ctx.exception.code, 401)


class TestState(WebTestCase):
    def test_lists_mailboxes_from_csv(self):
        data = self.state()
        self.assertEqual(len(data["mailboxes"]), 3)
        self.assertEqual(data["mailboxes"][0]["src_user"], "an@cu.com")

    def test_never_sends_passwords_to_the_browser(self):
        raw = self.get("/api/state").read().decode("utf-8")
        for secret in ("aaaabbbbccccdddd", "aaaa bbbb cccc dddd",
                       "MatKhau1", "MatKhau2", "eeeeffffgggghhhh"):
            self.assertNotIn(secret, raw)

    def test_reports_whether_password_is_present(self):
        box = self.state()["mailboxes"][0]
        self.assertTrue(box["has_src_password"])
        self.assertTrue(box["has_dst_password"])

    def test_exposes_endpoints_config(self):
        data = self.state()
        self.assertIn("imap.gmail.com", data["source"])
        self.assertIn("mail.congty.vn", data["dest"])

    def test_no_job_at_start(self):
        self.assertIsNone(self.state()["job"])


class TestRunJob(WebTestCase):
    def run_action(self, action, only=None):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.post("/api/run", {"action": action, "only": only or []})
            for _ in range(200):
                job = self.state()["job"]
                if job and not job["running"]:
                    return job
                time.sleep(0.05)
        self.fail("job khong ket thuc")

    def test_sync_runs_and_reports_exit_code(self):
        job = self.run_action("sync", ["an@cu.com"])
        self.assertEqual(job["action"], "sync")
        self.assertEqual(job["exit_code"], 0)
        self.assertFalse(job["error"])

    def test_output_is_captured_into_the_job(self):
        job = self.run_action("sync", ["an@cu.com"])
        text = "\n".join(job["lines"])
        self.assertIn("an@cu.com", text)
        self.assertIn("mailbox OK", text)

    def test_captured_output_has_no_passwords(self):
        job = self.run_action("sync", ["an@cu.com"])
        text = "\n".join(job["lines"])
        self.assertNotIn("aaaabbbbccccdddd", text)
        self.assertNotIn("MatKhau1", text)

    def test_failing_mailbox_gives_nonzero_exit(self):
        job = self.run_action("sync", ["fail.chi@cu.com"])
        self.assertNotEqual(job["exit_code"], 0)

    def test_dry_action_does_not_write(self):
        self.run_action("dry", ["an@cu.com"])
        self.assertFalse((self.tmp / "state" / "an@cu.com" / "done.marker").exists())

    def test_sync_marks_mailbox_done_in_state(self):
        self.run_action("sync", ["an@cu.com"])
        box = [m for m in self.state()["mailboxes"] if m["src_user"] == "an@cu.com"][0]
        self.assertTrue(box["done"])

    def test_results_show_up_in_the_table(self):
        self.run_action("sync", ["an@cu.com"])
        box = [m for m in self.state()["mailboxes"] if m["src_user"] == "an@cu.com"][0]
        self.assertEqual(box["ket_qua"], "OK")
        self.assertEqual(box["mail"], "421")

    def test_unknown_action_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/run", {"action": "xoa-het"})
        self.assertEqual(ctx.exception.code, 409)

    def test_second_job_rejected_while_one_runs(self):
        job = web.Job(action="sync", only=[])
        web.Handler.manager.job = job          # gia lap mot job dang chay
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post("/api/run", {"action": "sync"})
            self.assertEqual(ctx.exception.code, 409)
        finally:
            job.finished = time.time()


class TestAddUser(WebTestCase):
    def test_appends_to_csv(self):
        self.post("/api/users", {
            "src_user": "moi@cu.com", "src_password": "aaaabbbbccccdddd",
            "dst_user": "moi@moi.vn", "dst_password": "MatKhauMoi"})
        self.assertEqual(len(self.state()["mailboxes"]), 4)
        self.assertIn("moi@cu.com", self.users_path.read_text(encoding="utf-8"))

    def test_rejects_duplicate(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users", {
                "src_user": "an@cu.com", "src_password": "x" * 16,
                "dst_user": "khac@moi.vn", "dst_password": "y"})
        self.assertEqual(ctx.exception.code, 400)

    def test_rejects_missing_field(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users", {"src_user": "a@b.c"})
        self.assertEqual(ctx.exception.code, 400)

    def test_rejects_malformed_address(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users", {
                "src_user": "khongcoatcong", "src_password": "x" * 16,
                "dst_user": "a@b.c", "dst_password": "y"})
        self.assertEqual(ctx.exception.code, 400)

    def test_written_row_is_usable(self):
        self.post("/api/users", {
            "src_user": "moi@cu.com", "src_password": "aaaa bbbb cccc dddd",
            "dst_user": "moi@moi.vn", "dst_password": "MatKhauMoi"})
        from migrate_mail.users import load_users
        u = [x for x in load_users(self.users_path) if x.src_user == "moi@cu.com"][0]
        self.assertEqual(u.src_password, "aaaabbbbccccdddd")   # khoang trang da bo
        self.assertEqual(u.dst_user, "moi@moi.vn")


class TestHeaders(WebTestCase):
    def test_page_sets_protective_headers(self):
        res = self.get("/")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'self'", res.headers.get("Content-Security-Policy"))
        self.assertEqual(res.headers.get("Cache-Control"), "no-store")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestOutputRouting(WebTestCase):
    """Bang ket qua phai vao log cua job, khong duoc in ra stdout cua server.

    report.py truoc day dung print() thang, nen phan quan trong nhat cua output
    khong bao gio hien tren dashboard.
    """

    def test_result_table_reaches_the_job_not_stdout(self):
        buf = io.StringIO()
        from contextlib import redirect_stdout
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            with redirect_stdout(buf):
                self.post("/api/run", {"action": "sync", "only": ["an@cu.com"]})
                for _ in range(200):
                    job = self.state()["job"]
                    if job and not job["running"]:
                        break
                    time.sleep(0.05)
        text = "\n".join(job["lines"])
        self.assertIn("Tong ket:", text)
        self.assertIn("Dung luong", text)      # tieu de bang
        self.assertNotIn("Tong ket:", buf.getvalue())


class TestNoteColumn(WebTestCase):
    def test_successful_row_has_no_exit_noise(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.post("/api/run", {"action": "sync", "only": ["an@cu.com"]})
            for _ in range(200):
                job = self.state()["job"]
                if job and not job["running"]:
                    break
                time.sleep(0.05)
        box = [m for m in self.state()["mailboxes"] if m["src_user"] == "an@cu.com"][0]
        self.assertEqual(box["ket_qua"], "OK")
        self.assertEqual(box["ghi_chu"], "")

    def test_failed_row_keeps_its_reason(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.post("/api/run", {"action": "sync", "only": ["fail.chi@cu.com"]})
            for _ in range(200):
                job = self.state()["job"]
                if job and not job["running"]:
                    break
                time.sleep(0.05)
        box = [m for m in self.state()["mailboxes"] if m["src_user"] == "fail.chi@cu.com"][0]
        self.assertIn("AUTHENTICATION", box["ghi_chu"])
