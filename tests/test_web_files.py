# -*- coding: utf-8 -*-
"""Dashboard: tac vu toan cuc va tep tai ve.

Tach khoi test_web.py cho de tim, khong phai vi khac loai: day van la web.py.

Bon tac vu toan cuc (doctor, providers, report, handover) khac moi tac vu cu o
mot cho -- chung khong lam viec tren mailbox duoc chon ma tren ca cuoc migrate,
va hai cai sau con SINH RA FILE de tai ve.
"""

import re
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from postboat import web
from postboat.config import load_config

from test_cli import CONFIG
from test_web import WebTestCase


class TestFilesAndDownload(WebTestCase):
    """Tai bao cao va log ve tu trinh duyet, thay vi phai SCP.

    Voi bien ban ban giao -- thu ma ca muc dich la dua cho khach -- thi bat
    nguoi ta mo terminal moi cam duoc to giay vua bam nut sinh ra la vo ly.
    """

    def logdir(self) -> Path:
        d = Path(self.tmp) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_log(self, name: str, text: str = "noi dung") -> Path:
        path = self.logdir() / name
        path.write_text(text, encoding="utf-8")
        return path

    def download(self, name: str, token: bool = True):
        return self.get("/api/file?" + urllib.parse.urlencode({"name": name}),
                        token=token)

    # -- danh sach ----------------------------------------------------------

    def test_bao_cao_len_truoc_log(self):
        # Log moi hon bao cao, nhung bao cao van phai dung dau: mot dem chay
        # 200 hop sinh ra 200 log, xep thuan thoi gian thi bao cao bi day ra
        # khoi danh sach ngay dem dau tien.
        self.write_log("ban-giao-20260915-100000.html")
        time.sleep(0.02)
        self.write_log("an@cu.com.sync.20260915-110000.log")
        names = [f["name"] for f in self.state()["files"]]
        self.assertEqual(names[0], "ban-giao-20260915-100000.html")

    def test_bao_cao_duoc_danh_dau_de_giao_dien_phan_biet(self):
        self.write_log("report-20260915-100000.html")
        self.write_log("an@cu.com.sync.log")
        kinds = {f["name"]: f["kind"] for f in self.state()["files"]}
        self.assertEqual(kinds["report-20260915-100000.html"], "bao-cao")
        self.assertEqual(kinds["an@cu.com.sync.log"], "log")

    def test_danh_sach_bi_gioi_han(self):
        for i in range(web.MAX_FILES + 12):
            self.write_log("log-%03d.log" % i)
        self.assertEqual(len(self.state()["files"]), web.MAX_FILES)

    def test_chua_co_thu_muc_logs_thi_ra_rong_chu_khong_no(self):
        self.assertEqual(self.state()["files"], [])

    def test_state_noi_logs_nam_o_dau(self):
        self.assertTrue(self.state()["logdir"].endswith("logs"))

    # -- tai ve -------------------------------------------------------------

    def test_tai_duoc_noi_dung_that(self):
        self.write_log("report-20260915-100000.html", "<h1>bao cao</h1>")
        res = self.download("report-20260915-100000.html")
        self.assertEqual(res.read().decode("utf-8"), "<h1>bao cao</h1>")

    def test_luon_la_tep_dinh_kem_khong_bao_gio_mo_tai_cho(self):
        """File .html duoc sinh tu log imapsync. Mo no o CUNG GOC voi dashboard
        nghia la chi can mot cho escape sot thi script trong do chay duoc kem
        cookie dang nhap. Tai ve roi mo tu o dia la mot goc khac -- va in ra
        PDF thi cung phai mo tu o dia, nen khong bot tien gi.
        """
        self.write_log("ban-giao-20260915-100000.html", "<h1>x</h1>")
        res = self.download("ban-giao-20260915-100000.html")
        self.assertIn("attachment", res.headers.get("Content-Disposition"))
        self.assertNotIn("text/html", res.headers.get("Content-Type"))
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")

    def test_tai_ve_van_phai_dang_nhap(self):
        self.write_log("report-20260915-100000.html")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.download("report-20260915-100000.html", token=False)
        self.assertEqual(ctx.exception.code, 401)

    def test_khong_tai_duoc_tep_ngoai_logs(self):
        """Mot cho hong o day cho tai ve config.ini, tuc la mat khau cua ca
        cuoc migrate."""
        for name in ("../config.ini", "..\\config.ini", "../../etc/passwd",
                     "logs/../config.ini", "..", "."):
            with self.assertRaises(urllib.error.HTTPError, msg=name) as ctx:
                self.download(name)
            self.assertEqual(ctx.exception.code, 404, name)

    def test_khong_co_ten_thi_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/file")
        self.assertEqual(ctx.exception.code, 404)

    def test_tep_khong_ton_tai_thi_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.download("khong-he-co.html")
        self.assertEqual(ctx.exception.code, 404)


class TestSafeLogPath(unittest.TestCase):
    """Kiem thang ham loc ten tep, gom ca thu khong gui qua HTTP duoc."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pbsafe-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "config.ini").write_text(
            CONFIG.format(imapsync="imapsync"), encoding="utf-8")
        self.cfg = load_config(self.tmp / "config.ini")
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / "ok.log").write_text("x", encoding="utf-8")
        (self.tmp / "bimat.ini").write_text("mat khau", encoding="utf-8")

    def path(self, name):
        return web._safe_log_path(self.cfg, name)

    def test_ten_binh_thuong_thi_qua(self):
        self.assertIsNotNone(self.path("ok.log"))

    def test_ky_tu_xuong_dong_bi_chan(self):
        # Ten tep di thang vao header Content-Disposition; mot ky tu xuong
        # dong trong do la header injection.
        self.assertIsNone(self.path("ok.log\r\nX-Gia: 1"))
        self.assertIsNone(self.path("ok\nlog"))

    def test_dau_nhay_kep_bi_chan(self):
        self.assertIsNone(self.path('ok".log'))

    def test_duong_dan_tuyet_doi_bi_chan(self):
        self.assertIsNone(self.path(str(self.tmp / "bimat.ini")))

    def test_thu_muc_khong_phai_tep(self):
        (self.tmp / "logs" / "mot-thu-muc").mkdir()
        self.assertIsNone(self.path("mot-thu-muc"))

    def test_ten_rong_bi_chan(self):
        self.assertIsNone(self.path(""))


class TestGlobalActions(unittest.TestCase):
    """Tac vu toan cuc: doctor, providers, report, handover."""

    NEW = ("doctor", "providers", "report", "handover")

    def args(self, action, only=(), cfg=None):
        return web._make_args(action, list(only), Path("users.csv"), cfg)

    def cfg(self):
        tmp = Path(tempfile.mkdtemp(prefix="pbglobal-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "config.ini").write_text(CONFIG.format(imapsync="imapsync"),
                                        encoding="utf-8")
        return load_config(tmp / "config.ini")

    def test_bon_tac_vu_moi_deu_co_ham(self):
        for action in self.NEW:
            self.assertIn(action, web.ACTIONS)
            self.assertIn(action, web._ACTION_FN)

    def test_tac_vu_toan_cuc_bo_qua_mailbox_duoc_chon(self):
        """Chon vai mailbox roi bam 'Xuat bao cao' ma bao cao lai loc theo lua
        chon do thi nguoi bam khong he biet -- to giay se thieu mailbox.
        """
        for action in web.GLOBAL_ACTIONS:
            self.assertEqual(self.args(action, ["an@cu.com"]).only, [], action)

    def test_tac_vu_thuong_van_giu_lua_chon(self):
        self.assertEqual(self.args("sync", ["an@cu.com"]).only, ["an@cu.com"])

    def test_report_luon_gop_tat_ca_lan_chay(self):
        # Nguoi ta bam nut nay sau nhieu dem chay; mot bao cao chi chua lan
        # chay cuoi la bao cao sai.
        self.assertTrue(self.args("report").all)

    def test_report_ghi_file_vao_logdir(self):
        cfg = self.cfg()
        out = Path(self.args("report", cfg=cfg).out)
        self.assertEqual(out.parent, Path(cfg.paths.logdir))
        self.assertTrue(out.name.startswith("report-"))
        self.assertTrue(out.name.endswith(".html"))

    def test_khong_co_cfg_thi_van_chay_chi_la_khong_ghi_file(self):
        self.assertEqual(self.args("report").out, "")

    def test_handover_tu_dat_ten_nen_out_de_rong(self):
        # cmd_handover tu sinh logs/ban-giao-<thoi-diem>.html khi out rong.
        self.assertEqual(self.args("handover", cfg=self.cfg()).out, "")

    def test_moi_tac_vu_moi_deu_co_nut_tren_trang(self):
        from postboat.web_ui import PAGE
        for action in self.NEW:
            self.assertIn('data-act="%s"' % action, PAGE)

    def test_nut_toan_cuc_duoc_danh_dau_tren_trang(self):
        """Neu quen data-global tren mot nut thi no gui kem lua chon o bang
        tren, va khong co gi bao ca -- bao cao chi im lang thieu mailbox."""
        from postboat.web_ui import PAGE
        marked = set(re.findall(r'data-act="([a-z-]+)" data-global="1"', PAGE))
        self.assertEqual(marked, set(web.GLOBAL_ACTIONS))


if __name__ == "__main__":
    unittest.main()
