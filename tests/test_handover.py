# -*- coding: utf-8 -*-
"""Test cho bien ban ban giao.

To giay nay di ra khoi tay minh va co chu ky o duoi, nen cai dang kiem o day
khong phai "co chay khong" ma la "no co noi dung su that khong": khong im lang
ve buoc chua chay, khong bo sot hop thu that bai, khong bia so.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from postboat import handover, report
from postboat.config import HandoverConf


def row(src, ok=True, mail=100, byts=1024, **kw):
    base = dict(src_user=src, dst_user=src.replace("cu.com", "moi.vn"),
                ket_qua="OK" if ok else "LOI", folder="5",
                mail_chuyen=str(mail), bytes=str(byts),
                dung_luong=report.human_bytes(byts), goi_y="")
    base.update(kw)
    return base


class TestDinhDangSo(unittest.TestCase):

    def test_ngan_cach_hang_nghin_bang_dau_cham(self):
        self.assertEqual(handover.vn_number(122700), "122.700")
        self.assertEqual(handover.vn_number("48213"), "48.213")

    def test_so_hong_thi_ra_khong_chu_khong_no(self):
        self.assertEqual(handover.vn_number(None), "0")
        self.assertEqual(handover.vn_number("khong phai so"), "0")

    def test_ngay_doc_tu_ten_file_run(self):
        self.assertEqual(handover.vn_date("20260825-101500"), "25/08/2026")
        self.assertEqual(handover.vn_date("2026-08-25 10:15:00"), "25/08/2026")

    def test_ngay_khong_doc_duoc_thi_de_trong(self):
        self.assertEqual(handover.vn_date("linh tinh"), "")
        self.assertEqual(handover.vn_date(""), "")

    def test_mot_lan_chay_thi_khong_hien_khoang(self):
        # "25/08/2026 - 25/08/2026" doc nhu mot loi hon la mot khoang.
        self.assertEqual(handover.period_from_runs(["20260825-101500"]),
                         "25/08/2026")

    def test_nhieu_lan_chay_thi_lay_dau_va_cuoi(self):
        got = handover.period_from_runs(
            ["20260914-233000", "20260825-101500", "20260901-020000"])
        self.assertEqual(got, "25/08/2026 – 14/09/2026")


class TestNoiThatVeKetQua(unittest.TestCase):

    def test_hop_thu_that_bai_duoc_ke_ten_o_muc_rieng(self):
        rows = [row("an@cu.com"), row("chi@cu.com", ok=False,
                                      ghi_chu="EXIT_ERR_SELECT")]
        doc = handover.build_html(rows)
        self.assertIn("Hộp thư chưa đạt", doc)
        self.assertIn("chi@cu.com", doc)
        self.assertIn("EXIT_ERR_SELECT", doc)

    def test_khong_co_hop_nao_hong_thi_khong_co_muc_do(self):
        doc = handover.build_html([row("an@cu.com")])
        self.assertNotIn("Hộp thư chưa đạt", doc)

    def test_goi_y_xu_ly_di_kem_hop_thu_hong(self):
        rows = [row("chi@cu.com", ok=False, ghi_chu="EXIT_ERR_SELECT",
                    goi_y="Doi archive_folder | Mail khong bi mat")]
        doc = handover.build_html(rows)
        self.assertIn("Doi archive_folder", doc)
        self.assertIn("Mail khong bi mat", doc)

    def test_goi_y_cua_hop_thanh_cong_khong_in_ra(self):
        # Goi y chi co nghia khi that bai; in o dong OK lam khach hoang mang.
        rows = [row("an@cu.com", goi_y="Giam workers")]
        self.assertNotIn("Giam workers", handover.build_html(rows))

    def test_tong_so_cong_tu_tung_dong(self):
        rows = [row("an@cu.com", mail=48213), row("binh@cu.com", mail=7104)]
        doc = handover.build_html(rows)
        self.assertIn("55.317", doc)       # 48213 + 7104

    def test_dem_hop_thu_hoan_tat_tren_tong(self):
        rows = [row("an@cu.com"), row("binh@cu.com"), row("chi@cu.com", ok=False)]
        self.assertIn("2/3", handover.build_html(rows))


class TestKhongImLangVeBuocChuaChay(unittest.TestCase):
    """Muc de sai nhat cua to giay nay.

    Neu chua chay verify ma bien ban khong co muc nao ve ngay thang, nguoi doc
    se hieu la da kiem va khong co van de. Phai noi thang la chua kiem.
    """

    def test_chua_verify_thi_noi_ro_la_chua_ket_luan(self):
        doc = handover.build_html([row("an@cu.com")], verify_users={})
        self.assertIn("Đối chiếu ngày tháng", doc)
        self.assertIn("Chưa chạy", doc)
        self.assertNotIn("Khớp", doc)

    def test_co_verify_thi_in_bang_va_phuong_phap(self):
        vu = {"an@cu.com": dict(src_user="an@cu.com", ok=True, error="",
                                compared=2400, mismatched=0, missing=0,
                                without_msgid=0, sample=200)}
        doc = handover.build_html([row("an@cu.com")], verify_users=vu)
        self.assertIn("2.400", doc)
        self.assertIn("Khớp", doc)
        self.assertIn("tối đa 200", doc)      # noi ro ket luan tren mau bao nhieu
        self.assertNotIn("Chưa chạy", doc)

    def test_ty_le_lech_dung_dau_phay_thap_phan(self):
        vu = {"an@cu.com": dict(src_user="an@cu.com", ok=False, error="",
                                compared=4200, mismatched=3, missing=0,
                                without_msgid=0, sample=200)}
        doc = handover.build_html([row("an@cu.com")], verify_users=vu)
        self.assertIn("0,07%", doc)
        self.assertNotIn("0.07%", doc)

    def test_folder_khong_mo_duoc_khong_bi_ghi_thanh_khop(self):
        vu = {"chi@cu.com": dict(src_user="chi@cu.com", ok=False,
                                 error="khong mo duoc folder Archive",
                                 compared=0, mismatched=0, missing=0,
                                 without_msgid=0, sample=200)}
        doc = handover.build_html([row("chi@cu.com")], verify_users=vu)
        self.assertIn("Không kiểm được", doc)
        self.assertIn("khong mo duoc folder Archive", doc)

    def test_mail_khong_co_msgid_duoc_giai_thich_chu_khong_bo_qua(self):
        vu = {"an@cu.com": dict(src_user="an@cu.com", ok=True, error="",
                                compared=100, mismatched=0, missing=0,
                                without_msgid=12, sample=200)}
        doc = handover.build_html([row("an@cu.com")], verify_users=vu)
        self.assertIn("không có Message-Id", doc)
        self.assertIn("vẫn được chuyển bình thường", doc)


class TestPhamVi(unittest.TestCase):

    def test_luon_co_muc_khong_thuoc_pham_vi(self):
        doc = handover.build_html([row("an@cu.com")])
        self.assertIn("Không thuộc phạm vi", doc)
        for item in ("Lịch", "Danh bạ", "chữ ký"):
            self.assertIn(item, doc)

    def test_pham_vi_tu_sinh_khi_khong_khai_bao(self):
        doc = handover.build_html([row("a@cu.com"), row("b@cu.com")],
                                  source_name="Gmail", dest_name="IceWarp")
        self.assertIn("2 hộp thư", doc)
        self.assertIn("Gmail", doc)
        self.assertIn("IceWarp", doc)

    def test_pham_vi_khai_bao_thi_duoc_uu_tien(self):
        info = HandoverConf(scope="Chuyển 200 hộp thư theo hợp đồng số 12/2026.")
        doc = handover.build_html([row("a@cu.com")], info=info)
        self.assertIn("hợp đồng số 12/2026", doc)
        self.assertNotIn("Chuyển thư của 1 hộp thư", doc)


class TestTrangBia(unittest.TestCase):

    def test_ten_khach_hang_in_ra_khi_co(self):
        info = HandoverConf(customer="Cong ty Phuong Nam", performer="BizMac")
        doc = handover.build_html([row("a@cu.com")], info=info)
        self.assertIn("Cong ty Phuong Nam", doc)
        self.assertIn("BizMac", doc)

    def test_thieu_thong_tin_thi_de_dong_gach_dien_tay(self):
        # Ban giao hay lam voi; bat khai bao du moi thu moi in duoc mot to
        # giay la bat sai cho.
        doc = handover.build_html([row("a@cu.com")])
        self.assertIn('class="fill"', doc)

    def test_co_cho_ky_cho_ca_hai_ben(self):
        doc = handover.build_html([row("a@cu.com")])
        self.assertIn("BÊN THỰC HIỆN", doc)
        self.assertIn("BÊN NHẬN BÀN GIAO", doc)

    def test_lien_he_ho_tro_o_chan_trang(self):
        info = HandoverConf(contact="ho-tro@bizmac.com.vn")
        doc = handover.build_html([row("a@cu.com")], info=info)
        self.assertIn("ho-tro@bizmac.com.vn", doc)


class TestAnToan(unittest.TestCase):
    """Noi dung den tu log imapsync la du lieu ngoai, khong duoc tin."""

    def test_the_html_trong_ghi_chu_bi_vo_hieu(self):
        rows = [row("a@cu.com", ok=False,
                    ghi_chu="<script>alert(1)</script>")]
        doc = handover.build_html(rows)
        self.assertNotIn("<script>alert(1)</script>", doc)
        self.assertIn("&lt;script&gt;", doc)

    def test_dia_chi_co_ky_tu_dac_biet_van_an_toan(self):
        # Doi chieu theo dia chi da escape, KHONG theo mot chuoi con chung
        # chung nhu '"><b>': chuoi do trung voi markup that cua tool
        # ('class="card"><b>'), nen test se do vi ly do khong lien quan.
        doc = handover.build_html([row('a"><b>@cu.com')])
        self.assertIn("a&quot;&gt;&lt;b&gt;@cu.com", doc)
        self.assertNotIn("<b>@cu.com", doc)


class TestLuuKetQuaVerify(unittest.TestCase):
    """save_verify phai GOP chu khong de len, giong preflight.

    `verify --only mot-dia-chi` chi kiem mot hop thu. Ghi de thi bien ban lam
    sau do chi con mot dong, trong khi 199 hop kia van da duoc kiem.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def check(self, src, mismatched=0, error=""):
        from postboat.verify import FolderCheck, UserCheck
        fc = FolderCheck(source_folder="INBOX", dest_folder="INBOX",
                         compared=10, matched=10 - mismatched,
                         mismatched=mismatched)
        return UserCheck(src_user=src, dst_user=src, folders=[fc], error=error)

    def test_chay_lan_hai_khong_xoa_ket_qua_lan_mot(self):
        report.save_verify(self.tmp, [self.check("an@cu.com")], sample=200)
        report.save_verify(self.tmp, [self.check("binh@cu.com")], sample=200)
        got = report.load_verify(self.tmp)
        self.assertEqual(sorted(got), ["an@cu.com", "binh@cu.com"])

    def test_chay_lai_cung_hop_thu_thi_cap_nhat(self):
        report.save_verify(self.tmp, [self.check("an@cu.com", mismatched=5)])
        report.save_verify(self.tmp, [self.check("an@cu.com", mismatched=0)])
        got = report.load_verify(self.tmp)
        self.assertEqual(got["an@cu.com"]["mismatched"], 0)
        self.assertTrue(got["an@cu.com"]["ok"])

    def test_chi_giu_folder_co_van_de(self):
        report.save_verify(self.tmp, [self.check("an@cu.com", mismatched=0)])
        got = report.load_verify(self.tmp)
        self.assertEqual(got["an@cu.com"]["folders"], [])

    def test_folder_lech_thi_duoc_giu_lai(self):
        report.save_verify(self.tmp, [self.check("an@cu.com", mismatched=3)])
        folders = report.load_verify(self.tmp)["an@cu.com"]["folders"]
        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]["mismatched"], 3)

    def test_luu_ca_co_mau_de_bien_ban_noi_duoc(self):
        report.save_verify(self.tmp, [self.check("an@cu.com")], sample=150)
        self.assertEqual(report.load_verify(self.tmp)["an@cu.com"]["sample"], 150)

    def test_chua_chay_bao_gio_thi_ra_rong_chu_khong_no(self):
        self.assertEqual(report.load_verify(self.tmp), {})

    def test_file_hong_thi_ra_rong_chu_khong_no(self):
        (self.tmp / report.VERIFY_FILE).write_text("{ khong phai json",
                                                   encoding="utf-8")
        self.assertEqual(report.load_verify(self.tmp), {})

    def test_ghi_ra_utf8_doc_lai_duoc(self):
        report.save_verify(self.tmp, [self.check("an@cu.com")])
        with (self.tmp / report.VERIFY_FILE).open(encoding="utf-8") as fh:
            self.assertIn("users", json.load(fh))


class TestGhiFile(unittest.TestCase):

    def test_ghi_ra_utf8_va_tao_thu_muc_cha(self):
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "chua-co" / "ban-giao.html"
        handover.write_handover(out, [row("an@cu.com")],
                                info=HandoverConf(customer="Khách hàng A"))
        self.assertTrue(out.exists())
        self.assertIn("Khách hàng A", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
