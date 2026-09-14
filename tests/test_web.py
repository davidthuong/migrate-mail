# -*- coding: utf-8 -*-
"""Test dashboard web: phan quyen, khong lo mat khau, chay job, them mailbox."""

import io
import json
import os
import re
import shutil
import subprocess
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

from test_cli import CONFIG, USERS, no_dest_namespace, quote
from test_discover import GMAIL_EN, parse

FAKE = HERE / "fake_imapsync.py"


def fake_folders(cfg, user, side="source", timeout=60):
    if "loi" in user.src_user:
        from migrate_mail.discover import DiscoveryError
        raise DiscoveryError("login that bai")
    return parse(GMAIL_EN)


class WebTestCase(unittest.TestCase):
    # Lop con doi hai cai nay de chay tren mot cau hinh khac.
    config_text = CONFIG
    users_text = USERS

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmweb-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch("migrate_mail.discover.server_layout",
                             side_effect=no_dest_namespace)
        patcher.start()
        self.addCleanup(patcher.stop)
        imapsync = "%s %s" % (quote(sys.executable), quote(FAKE))
        (self.tmp / "config.ini").write_text(
            self.config_text.format(imapsync=imapsync), encoding="utf-8")
        self.users_path = self.tmp / "users.csv"
        self.users_path.write_text(self.users_text, encoding="utf-8")

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

    def test_unauthorised_post_with_a_big_body_still_answers_401(self):
        """Tu choi ma khong doc het body thi client nhan connection reset chu
        khong nhan duoc cau tra loi 401 -- no khong bao gio biet vi sao bi
        tu choi. Body cang lon cang de dinh, nen o day co y gui mot body to.
        """
        payload = {"src_user": "binh@cu.com", "rac": "x" * 200_000}
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users/remove", payload, token=False)
        self.assertEqual(ctx.exception.code, 401)
        # Doc duoc than cau tra loi moi tinh la da nhan tron ven.
        self.assertIn("quyen", ctx.exception.read().decode("utf-8"))

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

    def test_says_which_password_fields_the_form_should_ask_for(self):
        """Trang an o mat khau cua dau nao khong dung toi. Config cua bo test
        nay chay password ca hai dau, nen ca hai deu duoc hoi."""
        data = self.state()
        self.assertTrue(data["needs_src_password"])
        self.assertTrue(data["needs_dst_password"])


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

    def test_resume_skips_a_mailbox_already_done(self):
        """Dashboard phai doc done.marker giong het CLI --resume."""
        self.run_action("sync", ["an@cu.com"])
        job = self.run_action("resume", ["an@cu.com"])
        self.assertEqual(job["exit_code"], 0)
        self.assertIn("Khong con mailbox nao can chay", "\n".join(job["lines"]))

    def test_resume_still_runs_a_mailbox_not_done(self):
        job = self.run_action("resume", ["binh@cu.com"])
        self.assertEqual(job["exit_code"], 0)
        self.assertTrue((self.tmp / "state" / "binh@cu.com" / "done.marker").exists())

    def test_resume_leaves_out_the_finished_mailbox(self):
        """Tinh huong that: mot hop da xong, hop kia thi chua."""
        self.run_action("sync", ["an@cu.com"])
        job = self.run_action("resume", ["an@cu.com", "binh@cu.com"])
        text = "\n".join(job["lines"])
        self.assertIn("bo qua 1 mailbox", text)
        self.assertIn("binh@cu.com", text)
        self.assertNotIn("an@cu.com", text)

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


CONFIG_DEST_MASTER = """[source]
host = imap.gmail.com
port = 993
ssl = true

[dest]
provider = dovecot
host = mail.moi.vn
port = 993
ssl = true
auth = master
master_user = migrate
master_password = BiMat

[paths]
imapsync = {imapsync}
logdir = logs
statedir = state
"""

# Khong co cot dst_password -- dich dang nhap bang tai khoan quan tri.
USERS_NO_DST_PASSWORD = """src_user,src_password,dst_user
an@cu.com,aaaa bbbb cccc dddd,an@moi.vn
binh@cu.com,eeeeffffgggghhhh,binh@moi.vn
"""


class TestAddUserWithMasterDest(WebTestCase):
    """Them mailbox qua dashboard khi DICH chay auth = master.

    Form tren trang an o mat khau dich di, nen no khong gui truong do len.
    Neu server van doi truong do thi nut "Them vao danh sach" bao thieu mat
    khau ma nguoi dung khong co cach nao dien -- o nhap da bien mat roi.
    """

    config_text = CONFIG_DEST_MASTER
    users_text = USERS_NO_DST_PASSWORD

    def test_state_tells_the_form_to_hide_the_field(self):
        data = self.state()
        self.assertTrue(data["needs_src_password"])
        self.assertFalse(data["needs_dst_password"])
        self.assertEqual(data["dest_auth"], "master")

    def test_accepts_a_row_without_a_destination_password(self):
        self.post("/api/users", {
            "src_user": "moi@cu.com", "src_password": "aaaabbbbccccdddd",
            "dst_user": "moi@moi.vn"})
        self.assertEqual(len(self.state()["mailboxes"]), 3)

    def test_written_row_is_usable(self):
        self.post("/api/users", {
            "src_user": "moi@cu.com", "src_password": "aaaabbbbccccdddd",
            "dst_user": "moi@moi.vn"})
        from migrate_mail.users import load_users
        users = load_users(self.users_path, need_dst_password=False)
        u = [x for x in users if x.src_user == "moi@cu.com"][0]
        self.assertEqual(u.dst_user, "moi@moi.vn")
        self.assertEqual(u.dst_password, "")

    def test_address_fields_are_still_required(self):
        """Bo bot mot cot khong duoc lam long het moi kiem tra con lai."""
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users", {"src_user": "moi@cu.com",
                                     "src_password": "x" * 16})
        self.assertEqual(ctx.exception.code, 400)

    def test_duplicates_are_still_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users", {
                "src_user": "an@cu.com", "src_password": "x" * 16,
                "dst_user": "khac@moi.vn"})
        self.assertEqual(ctx.exception.code, 400)

    def test_no_mailbox_is_flagged_as_missing_a_password(self):
        flagged = [m["src_user"] for m in self.state()["mailboxes"]
                   if not m["has_src_password"] or not m["has_dst_password"]]
        self.assertEqual(flagged, [])


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


class TestConfigReload(WebTestCase):
    """Sua config.ini phai an o lan chay sau, khong bat nguoi dung restart server."""

    def set_workers(self, n):
        imapsync = "%s %s" % (quote(sys.executable), quote(FAKE))
        text = CONFIG.format(imapsync=imapsync).replace("workers = 2", "workers = %d" % n)
        (self.tmp / "config.ini").write_text(text, encoding="utf-8")

    def run_once(self):
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.post("/api/run", {"action": "sync", "only": ["an@cu.com"]})
            for _ in range(200):
                job = self.state()["job"]
                if job and not job["running"]:
                    return job
                time.sleep(0.05)
        self.fail("job khong ket thuc")

    def test_state_exposes_workers(self):
        self.assertEqual(self.state()["workers"], 2)

    def test_edited_config_takes_effect_on_next_job(self):
        self.set_workers(7)
        self.run_once()
        self.assertEqual(self.state()["workers"], 7)

    def test_broken_config_keeps_the_previous_one(self):
        (self.tmp / "config.ini").write_text("[sync]\nworkers = khong-phai-so\n",
                                             encoding="utf-8")
        job = self.run_once()
        self.assertIn("khong doc lai duoc config", "\n".join(job["lines"]))
        self.assertEqual(job["exit_code"], 0)     # van chay duoc bang config cu


class TestRemoveUser(WebTestCase):
    def remove(self, src_user):
        return self.post("/api/users/remove", {"src_user": src_user})

    def test_removes_the_row(self):
        self.remove("binh@cu.com")
        users = [m["src_user"] for m in self.state()["mailboxes"]]
        self.assertNotIn("binh@cu.com", users)
        self.assertEqual(len(users), 2)

    def test_leaves_other_rows_untouched(self):
        self.remove("binh@cu.com")
        from migrate_mail.users import load_users
        rest = load_users(self.users_path)
        self.assertEqual([u.src_user for u in rest], ["an@cu.com", "fail.chi@cu.com"])
        self.assertEqual(rest[0].src_password, "aaaabbbbccccdddd")   # con nguyen
        self.assertEqual(rest[0].dst_password, "MatKhau1")

    def test_keeps_comments_in_the_file(self):
        """File cua nguoi dung co ghi chu; xoa mot dong khong duoc nuot chung."""
        self.remove("binh@cu.com")
        text = self.users_path.read_text(encoding="utf-8")
        self.assertIn("# dong ghi chu se bi bo qua", text)
        self.assertTrue(text.startswith("src_user,"))

    def test_unknown_address_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.remove("khongco@cu.com")
        self.assertEqual(ctx.exception.code, 400)

    def test_missing_address_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users/remove", {})
        self.assertEqual(ctx.exception.code, 400)

    def test_refuses_while_a_job_is_running(self):
        job = web.Job(action="sync", only=[])
        web.Handler.manager.job = job
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.remove("binh@cu.com")
            self.assertEqual(ctx.exception.code, 409)
        finally:
            job.finished = time.time()
        self.assertIn("binh@cu.com", [m["src_user"] for m in self.state()["mailboxes"]])

    def test_needs_a_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users/remove", {"src_user": "binh@cu.com"}, token=False)
        self.assertEqual(ctx.exception.code, 401)

    def test_does_not_touch_state_or_logs(self):
        """Mail da chuyen va log la du lieu -- xoa khoi danh sach khong xoa chung."""
        with mock.patch("migrate_mail.cli.list_folders", side_effect=fake_folders):
            self.post("/api/run", {"action": "sync", "only": ["an@cu.com"]})
            for _ in range(200):
                job = self.state()["job"]
                if job and not job["running"]:
                    break
                time.sleep(0.05)
        marker = self.tmp / "state" / "an@cu.com" / "done.marker"
        self.assertTrue(marker.exists())
        self.remove("an@cu.com")
        self.assertTrue(marker.exists())
        self.assertTrue(list((self.tmp / "logs").glob("an@cu.com.sync.*.log")))

    def test_add_then_remove_round_trip(self):
        self.post("/api/users", {
            "src_user": "moi@cu.com", "src_password": "aaaabbbbccccdddd",
            "dst_user": "moi@moi.vn", "dst_password": "MatKhauMoi"})
        self.assertEqual(len(self.state()["mailboxes"]), 4)
        self.remove("moi@cu.com")
        self.assertEqual(len(self.state()["mailboxes"]), 3)

    def test_file_stays_owner_only_readable(self):
        self.remove("binh@cu.com")
        if os.name == "posix":
            self.assertEqual(oct(self.users_path.stat().st_mode & 0o777), "0o600")


class TestPageScript(unittest.TestCase):
    """Kiem cu phap khoi <script> cua dashboard.

    Loi tung gap: mot dong thieu dau nhay dong lam ca khoi script hong, trang
    dung o "Dang tai..." nhung moi test Python van xanh vi chung khong chay JS.
    Test nay bat dung loai loi do. Bo qua neu may khong co node -- no chi la
    cong cu luc phat trien, chay that khong can node.
    """

    def script_source(self):
        from migrate_mail.web_ui import PAGE
        start = PAGE.index("<script>") + len("<script>")
        return PAGE[start:PAGE.index("</script>", start)]

    def test_script_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("khong co node tren may nay")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.js"
            io.open(str(path), "w", encoding="utf-8",
                    newline="\n").write(self.script_source())
            # encoding phai chi dinh ro: node in lai dong loi, ma dong do co
            # tieng Viet -- de mac dinh thi Python decode theo locale va nem
            # UnicodeDecodeError, lam mat luon thong bao loi.
            proc = subprocess.run([node, "--check", str(path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_script_is_not_empty(self):
        self.assertGreater(len(self.script_source()), 1000)

    def test_every_element_id_the_script_asks_for_exists_in_the_page(self):
        """Cung noi lo voi test_every_button_on_the_page_is_a_known_action:
        $("id") tra ve null cho id khong co, va JS chi hong luc chay -- moi
        test Python van xanh. Bat luc doc file thay vi luc nguoi dung mo trang.
        """
        from migrate_mail.web_ui import PAGE
        wanted = set(re.findall(r'\$\("([a-z0-9-]+)"\)', self.script_source()))
        self.assertTrue(wanted, "khong doc duoc id nao tu script")
        present = set(re.findall(r'id="([a-z0-9-]+)"', PAGE))
        self.assertEqual(wanted - present, set())


class TestActionTable(unittest.TestCase):
    """Ban do tac vu -> tham so.

    Nut tren trang duoc viet cung trong HTML chu khong sinh ra tu ACTIONS, nen
    ba noi (HTML, ACTIONS, _ACTION_FN) rat de lech nhau ma khong ai bao. Cho
    den truoc khi co 'resume', web hoan toan khong biet done.marker la gi
    trong khi CLI thi co -- cung mot tool, hai cua vao hieu "da xong" khac nhau.
    """

    def args(self, action):
        return web._make_args(action, [], Path("users.csv"))

    def test_resume_sets_only_the_resume_flag(self):
        a = self.args("resume")
        self.assertTrue(a.resume)
        self.assertFalse(a.dry)
        self.assertFalse(a.sizes)
        self.assertFalse(a.folders_only)

    def test_plain_sync_does_not_resume(self):
        self.assertFalse(self.args("sync").resume)

    def test_every_action_has_a_function(self):
        self.assertEqual(set(web.ACTIONS), set(web._ACTION_FN))

    def test_every_button_on_the_page_is_a_known_action(self):
        from migrate_mail.web_ui import PAGE
        acts = set(re.findall(r'data-act="([a-z-]+)"', PAGE))
        self.assertTrue(acts, "khong doc duoc nut nao tu trang")
        self.assertEqual(acts - set(web.ACTIONS), set())

    def test_resume_has_a_button(self):
        from migrate_mail.web_ui import PAGE
        self.assertIn('data-act="resume"', PAGE)


CONFIG_SOURCE_MASTER = """[source]
provider = dovecot
host = mail.cu.vn
port = 993
ssl = true
auth = master
master_user = migrate
master_password = BiMatNguon

[dest]
provider = dovecot
host = mail.moi.vn
port = 993
ssl = true

[sync]
workers = 2

[paths]
imapsync = {imapsync}
logdir = logs
statedir = state
"""

# Dung dinh dang ma README bao dung khi nguon chay auth = master: KHONG co cot
# src_password. Khac fixture kia o mot cho quan trong -- cot bi bo nam o GIUA,
# khong phai o cuoi.
USERS_NO_SRC_PASSWORD = """src_user,dst_user,dst_password
an@cu.vn,an@moi.vn,MatKhauDichAn
binh@cu.vn,binh@moi.vn,MatKhauDichBinh
"""


class TestAddUserKeepsTheFileReadable(WebTestCase):
    """Them mailbox qua dashboard khong duoc lam hong users.csv.

    Truoc day _add_user luon ghi du BON cot theo COLUMNS, bat ke file that co
    may cot. Voi file bo cot GIUA (src_user,dst_user,dst_password -- dung dinh
    dang cho auth = master) thi moi truong bi lech mot nac: gia tri rong cua
    src_password roi vao cot dst_user, va dia chi dich roi vao cot mat khau.

    Hau qua tren rig that: bam "Them vao danh sach" xong thi CA TOOL ngung
    chay -- preflight lan sync deu chet voi "users.csv dong 5 thieu gia tri:
    dst_user" -- cho den khi co nguoi mo file ra sua tay.
    """

    config_text = CONFIG_SOURCE_MASTER
    users_text = USERS_NO_SRC_PASSWORD

    def test_form_khong_hoi_mat_khau_nguon(self):
        self.assertFalse(self.state()["needs_src_password"])

    def test_dong_moi_doc_lai_dung(self):
        self.post("/api/users", {"src_user": "moi@cu.vn",
                                 "dst_user": "moi@moi.vn",
                                 "dst_password": "MatKhauMoi"})
        from migrate_mail.users import load_users
        users = load_users(self.users_path, need_src_password=False)
        moi = [u for u in users if u.src_user == "moi@cu.vn"]
        self.assertEqual(len(moi), 1, self.users_path.read_text(encoding="utf-8"))
        self.assertEqual(moi[0].dst_user, "moi@moi.vn")
        self.assertEqual(moi[0].dst_password, "MatKhauMoi")

    def test_so_truong_moi_dong_bang_so_cot(self):
        self.post("/api/users", {"src_user": "moi@cu.vn",
                                 "dst_user": "moi@moi.vn",
                                 "dst_password": "MatKhauMoi"})
        lines = [l for l in self.users_path.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
        widths = {len(l.split(",")) for l in lines}
        self.assertEqual(widths, {3}, lines)

    def test_danh_sach_van_dung_duoc_sau_khi_them(self):
        """Cai nay moi la thu nguoi dung thay: bam xong thi tool con chay."""
        self.post("/api/users", {"src_user": "moi@cu.vn",
                                 "dst_user": "moi@moi.vn",
                                 "dst_password": "MatKhauMoi"})
        self.assertEqual(len(self.state()["mailboxes"]), 3)

    def test_gia_tri_khong_co_cho_thi_bao_ra_chu_khong_vut(self):
        """File nay khong co cot src_password. Neu ai do van gui mat khau
        nguon len thi phai bao, dung im lang vut di."""
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/users", {"src_user": "moi@cu.vn",
                                     "src_password": "aaaabbbbccccdddd",
                                     "dst_user": "moi@moi.vn",
                                     "dst_password": "MatKhauMoi"})
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("src_password", ctx.exception.read().decode("utf-8"))


class TestPageStructure(unittest.TestCase):
    """Hai cai bay trong trang HTML, deu tim ra khi mo that trong trinh duyet."""

    def test_cho_bao_ket_qua_khong_chua_usersfile(self):
        """Handler thanh cong ghi de len #addstatus. Neu #usersfile nam trong
        do thi textContent xoa no, roi refresh() nem TypeError va vong cap
        nhat chet han -- dashboard dung hinh khong mot loi bao."""
        from migrate_mail.web_ui import PAGE
        start = PAGE.index('id="addstatus"')
        end = PAGE.index("</div>", start)
        self.assertNotIn("usersfile", PAGE[start:end])

    def test_refresh_goi_schedule_du_phia_tren_hong(self):
        from migrate_mail.web_ui import PAGE
        body = PAGE[PAGE.index("async function refresh()"):]
        body = body[:body.index("\n}")]
        self.assertIn("catch", body)
        # schedule() phai nam NGOAI khoi try, o cuoi ham
        self.assertGreater(body.rindex("schedule()"), body.rindex("catch"))

    def test_nhan_form_noi_ro_nguon_hay_dich(self):
        """cPanel -> cPanel la ca hay gap nhat cua mot nha cung cap; luc do
        ten provider khong phan biet duoc o nao la dau nao."""
        from migrate_mail.web_ui import PAGE
        for label in ('$("lb-src")', '$("lb-dst")', '$("lb-dstpass")'):
            line = [l for l in PAGE.splitlines() if label in l and "textContent" in l]
            self.assertTrue(line, label)
            text = line[0]
            self.assertTrue("nguồn" in text or "đích" in text,
                            "%s khong noi nguon hay dich: %s" % (label, text))


class TestPreflightShowsInTheTable(WebTestCase):
    """Bam "Kiem tra dang nhap" xong thi tung dong phai noi duoc ket qua.

    Truoc day bang chi doc tu state/runs/*.json, ma chi ho lenh sync moi ghi
    file do -- nen sau mot lan preflight, ca ba dong van ghi "chua chay", ke ca
    dong vua dang nhap hong. Voi 200 mailbox va 15 cai sai mat khau thi cho duy
    nhat biet la cuon mot tuong chu trong khung log.
    """

    def _save(self, **users):
        from migrate_mail.report import save_preflight
        statedir = self.tmp / "state"
        save_preflight(statedir, [
            (name, ok_src, msg_src, ok_dst, msg_dst)
            for name, (ok_src, msg_src, ok_dst, msg_dst) in users.items()])

    def row(self, src_user):
        rows = [m for m in self.state()["mailboxes"] if m["src_user"] == src_user]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_chua_kiem_thi_khong_co_gi(self):
        self.assertIsNone(self.row("an@cu.com")["preflight"])

    def test_dang_nhap_duoc(self):
        self._save(**{"an@cu.com": (True, "", True, "")})
        pf = self.row("an@cu.com")["preflight"]
        self.assertTrue(pf["ok"])
        self.assertEqual(pf["hong"], [])
        self.assertTrue(pf["when"])

    def test_noi_ro_hong_o_dau(self):
        self._save(**{"an@cu.com": (True, "", False,
                                    "[AUTHENTICATIONFAILED] Authentication failed.")})
        pf = self.row("an@cu.com")["preflight"]
        self.assertFalse(pf["ok"])
        self.assertEqual(pf["hong"], ["dich"])
        self.assertIn("Authentication failed", pf["loi"])

    def test_hong_ca_hai_dau(self):
        self._save(**{"an@cu.com": (False, "loi nguon", False, "loi dich")})
        self.assertEqual(self.row("an@cu.com")["preflight"]["hong"], ["nguon", "dich"])

    def test_kem_goi_y_sua_loi(self):
        self._save(**{"an@cu.com": (True, "", False,
                                    "[AUTHENTICATIONFAILED] Invalid credentials")})
        tips = self.row("an@cu.com")["preflight"]["goi_y"]
        self.assertTrue(tips)
        self.assertTrue(all(t.startswith("dich: ") for t in tips), tips)

    def test_chi_kiem_mot_hop_thi_hop_khac_van_con_ket_qua_cu(self):
        """preflight --only mot-dia-chi khong duoc xoa ket qua cua 199 hop kia."""
        self._save(**{"an@cu.com": (True, "", True, ""),
                      "binh@cu.com": (True, "", True, "")})
        self._save(**{"an@cu.com": (False, "hong roi", True, "")})
        self.assertFalse(self.row("an@cu.com")["preflight"]["ok"])
        self.assertTrue(self.row("binh@cu.com")["preflight"]["ok"])

    def test_file_hong_thi_coi_nhu_chua_kiem(self):
        (self.tmp / "state").mkdir(parents=True, exist_ok=True)
        (self.tmp / "state" / "preflight.json").write_text("{khong phai json",
                                                           encoding="utf-8")
        self.assertIsNone(self.row("an@cu.com")["preflight"])


class TestPreflightBadgeRules(unittest.TestCase):
    """Quy tac hien cot KET QUA, doc thang tu trang."""

    def setUp(self):
        from migrate_mail.web_ui import PAGE
        self.badge = PAGE[PAGE.index("function badge("):]
        self.badge = self.badge[:self.badge.index("\n}")]

    def test_ket_qua_sync_thang_preflight(self):
        """Sync da chay thi no moi la viec that su da lam; preflight chi lap
        cho khi chua co gi."""
        self.assertLess(self.badge.index('m.ket_qua === "OK"'),
                        self.badge.index("m.preflight"))
        self.assertLess(self.badge.index('m.ket_qua === "LOI"'),
                        self.badge.index("m.preflight"))

    def test_con_chua_chay_cho_hop_chua_kiem_gi(self):
        self.assertIn("chưa chạy", self.badge)
        self.assertGreater(self.badge.rindex("chưa chạy"),
                           self.badge.index("m.preflight"))


class TestSideNamesAreAccented(unittest.TestCase):
    """Ma nguon Python trong repo viet khong dau, con trang thi co dau.

    Ghep ten dau o phia may chu thi "dich" khong dau loi thang ra giao dien,
    nam canh "dang nhap hong o" co dau. Doi o lop giao dien.
    """

    def test_may_chu_tra_ve_danh_sach_chu_khong_ghep_san(self):
        from migrate_mail.web import _preflight_row
        from migrate_mail.config import load_config
        import tempfile as tf
        tmp = Path(tf.mkdtemp(prefix="mmside-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "config.ini").write_text(CONFIG.format(imapsync="imapsync"),
                                        encoding="utf-8")
        cfg = load_config(tmp / "config.ini")
        row = _preflight_row({"src_ok": False, "dst_ok": False,
                              "src_msg": "a", "dst_msg": "b"}, cfg)
        self.assertEqual(row["hong"], ["nguon", "dich"])

    def test_trang_doi_sang_co_dau(self):
        from migrate_mail.web_ui import PAGE
        self.assertIn('nguon: "nguồn"', PAGE)
        self.assertIn('dich: "đích"', PAGE)
