# -*- coding: utf-8 -*-
"""Canh cac file trong deploy/.

Chung khong chay duoc trong test (khong co Caddy lan systemd o day), nen o day
chi kiem mot thu duy nhat nhung dang kiem: KHONG CO BI MAT THAT nao bi commit
vao. Repo nay dang public. Mot cho sua tay roi `git add -A` la bam mat khau hay
ten mien that len GitHub vinh vien, va lich su git thi khong xoa bang mot commit
sau duoc.
"""

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

DEPLOY = HERE.parent / "deploy"


class TestDeployFilesExist(unittest.TestCase):

    def test_ca_ba_file_deu_con(self):
        for name in ("Caddyfile", "postboat.service", "README.md"):
            self.assertTrue((DEPLOY / name).is_file(), name)


class TestKhongCommitBiMat(unittest.TestCase):

    def caddyfile(self) -> str:
        return (DEPLOY / "Caddyfile").read_text(encoding="utf-8")

    def test_khong_co_bam_bcrypt_that(self):
        """Bam bcrypt that bat dau bang $2a$ / $2b$ / $2y$ roi den cost va
        muoi. Cho danh cho no phai con la placeholder.
        """
        found = re.search(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{10,}", self.caddyfile())
        self.assertIsNone(found,
                          "deploy/Caddyfile co bam mat khau that -- repo nay public")

    def test_cho_dien_mat_khau_van_la_placeholder(self):
        self.assertIn("<BAM-MAT-KHAU>", self.caddyfile())

    def test_cho_dien_ip_van_la_placeholder(self):
        self.assertIn("<IP-CUA-BAN>", self.caddyfile())

    def test_ten_mien_van_la_vi_du(self):
        self.assertIn("mm.congty.vn", self.caddyfile())


class TestCauHinhKhongTuVoHieu(unittest.TestCase):
    """Hai cho ma sai thi Caddy van chay, van cap chung chi, van cho vao --
    chi la mot lop bao ve am tham khong con tac dung. Khong co gi bao ca.
    """

    def caddyfile(self) -> str:
        return (DEPLOY / "Caddyfile").read_text(encoding="utf-8")

    def test_chan_ip_nam_trong_route(self):
        """Ngoai route, Caddy tu sap xep lai theo bang thu tu cua no, va trong
        bang do basic_auth nam TRUOC abort: mot IP ngoai danh sach van duoc moi
        nhap mat khau truoc khi bi tu choi -- tuc la noi cho nguoi la biet o
        day co cai de dang nhap. Trong route thi giu nguyen thu tu viet.
        """
        # Doi chieu theo "basic_auth {" chu khong theo "basic_auth": ten do
        # con nam trong chinh doan chu thich giai thich vi sao phai dung route,
        # va doan do dung TRUOC khoi route trong file.
        src = self.caddyfile()
        self.assertIn("route {", src)
        self.assertLess(src.index("route {"), src.index("abort @ngoai"))
        self.assertLess(src.index("abort @ngoai"), src.index("basic_auth {"))

    def test_dung_ten_chi_thi_moi(self):
        """Caddy 2.8 doi ten basicauth -> basic_auth. Viet ten cu tren ban moi
        thi Caddy bao loi luc nap, con viet ten moi tren ban cu cung vay -- nen
        deploy/README.md bat kiem `caddy version`. O day chot ten moi.
        """
        src = self.caddyfile()
        self.assertIn("basic_auth {", src)
        self.assertIsNone(re.search(r"(?<![_\w])basicauth\b", src))

    def test_van_tro_ve_localhost(self):
        """Doi thanh IP that hay 0.0.0.0 la vut het ba lop bao ve: nguoi ta go
        thang vao cong do la vao, khong qua Caddy.
        """
        self.assertIn("reverse_proxy 127.0.0.1:8765", self.caddyfile())


if __name__ == "__main__":
    unittest.main()
