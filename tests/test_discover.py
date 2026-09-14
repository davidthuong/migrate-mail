# -*- coding: utf-8 -*-
"""Test phan loai folder Gmail.

Chay:  python -m unittest discover -s tests

Luu y: file nay co tinh KHONG viet ky tu backslash truc tiep trong source.
Cac co IMAP (HasNoChildren, Sent, ...) duoc gan backslash o runtime bang
helper `imap_line`. Ly do: backslash rat de bi bien dang khi file di qua
shell/heredoc/editor, va khi hong thi test van chay nhung so khop sai am tham.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_mail import providers
from migrate_mail.config import (MASTER_AUTHZID, MASTER_SEPARATOR, MasterConf,
                                 ServerConf, SyncConf)
from migrate_mail.discover import (_login, _parse_list_line, _Plain,
                                   build_plan, special_use_roles)
from migrate_mail.imaputf7 import decode
from migrate_mail.providers import AUTH_MASTER

BS = chr(92)
Q = chr(34)


def imap_line(flags, name, delim="/"):
    """Dung mot dong tra ve LIST giong that. `flags` viet khong co backslash."""
    marked = " ".join(BS + f for f in flags.split())
    return ("(%s) %s%s%s %s%s%s" % (marked, Q, delim, Q, Q, name, Q)).encode("utf-8")


def parse(lines):
    out = [_parse_list_line(l) for l in lines]
    assert all(f is not None for f in out), "co dong LIST khong parse duoc"
    return out


# Output LIST that cua Gmail, account ngon ngu tieng Anh
GMAIL_EN = [
    imap_line("HasNoChildren", "INBOX"),
    imap_line("HasChildren Noselect", "[Gmail]"),
    imap_line("All HasNoChildren", "[Gmail]/All Mail"),
    imap_line("Drafts HasNoChildren", "[Gmail]/Drafts"),
    imap_line("HasNoChildren Important", "[Gmail]/Important"),
    imap_line("HasNoChildren Sent", "[Gmail]/Sent Mail"),
    imap_line("Flagged HasNoChildren", "[Gmail]/Starred"),
    imap_line("HasNoChildren Junk", "[Gmail]/Spam"),
    imap_line("HasNoChildren Trash", "[Gmail]/Trash"),
    imap_line("HasChildren", "Work"),
    imap_line("HasNoChildren", "Work/Project A"),
]

# Cung hop thu do nhung account de ngon ngu tieng Viet: ten folder doi hoan
# toan va bi ma hoa modified UTF-7. Chi co cac co la khong doi.
GMAIL_VI = [
    imap_line("HasNoChildren", "INBOX"),
    imap_line("HasChildren Noselect", "[Gmail]"),
    imap_line("All HasNoChildren", "[Gmail]/T&HqU-t c&HqM- th&AbA-"),
    imap_line("HasNoChildren Sent", "[Gmail]/Th&AbA- &AREA4w- g&Hu0-i"),
    imap_line("Drafts HasNoChildren", "[Gmail]/Th&AbA- nh&AOE-p"),
    imap_line("HasNoChildren Trash", "[Gmail]/Th&APk-ng r&AOE-c"),
    imap_line("HasNoChildren Junk", "[Gmail]/Th&AbA- r&AOE-c"),
    imap_line("HasNoChildren", "C&APQ-ng vi&Hsc-c/D&HvE- &AOE-n A"),
]


class TestParse(unittest.TestCase):
    def test_parses_flags_delim_name(self):
        f = _parse_list_line(imap_line("HasNoChildren Sent", "[Gmail]/Sent Mail"))
        self.assertEqual(f.raw, "[Gmail]/Sent Mail")
        self.assertEqual(f.delim, "/")
        self.assertEqual(f.flags, {"hasnochildren", "sent"})

    def test_parses_unquoted_name(self):
        line = ("(%sHasNoChildren) %s/%s INBOX" % (BS, Q, Q)).encode()
        self.assertEqual(_parse_list_line(line).raw, "INBOX")

    def test_parses_literal_name(self):
        # Ten folder tra ve dang literal {5} -> imaplib cho ra tuple
        head = ("(%sHasNoChildren) %s/%s {5}" % (BS, Q, Q)).encode()
        self.assertEqual(_parse_list_line((head, b"INBOX")).raw, "INBOX")

    def test_ignores_non_list_response(self):
        self.assertIsNone(_parse_list_line(b"* OK something else"))

    def test_flags_are_normalised_without_backslash(self):
        """Chan lai dung loi da tung gap: hang so mat backslash -> khop hut."""
        f = _parse_list_line(imap_line("HasNoChildren Noselect", "X"))
        for flag in f.flags:
            self.assertFalse(flag.startswith(BS))
            self.assertTrue(flag.isalpha(), "co bi bien dang: %r" % flag)


class TestPlanEnglish(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(parse(GMAIL_EN), SyncConf())

    def test_excludes_all_mail_important_starred_and_container(self):
        self.assertEqual(
            {f.raw for f, _ in self.plan.excluded},
            {"[Gmail]", "[Gmail]/All Mail", "[Gmail]/Important", "[Gmail]/Starred"},
        )

    def test_maps_special_folders_to_icewarp_names(self):
        self.assertEqual(
            {f.raw: d for f, d in self.plan.mapped},
            {
                "[Gmail]/Sent Mail": "Sent",
                "[Gmail]/Drafts": "Drafts",
                "[Gmail]/Trash": "Trash",
                "[Gmail]/Spam": "Spam",
            },
        )

    def test_keeps_inbox_and_user_labels(self):
        self.assertEqual([f.raw for f in self.plan.kept], ["INBOX", "Work", "Work/Project A"])

    def test_every_folder_classified_exactly_once(self):
        total = len(self.plan.excluded) + len(self.plan.mapped) + len(self.plan.kept)
        self.assertEqual(total, len(self.plan.folders))

    def test_exclude_regex_is_anchored_and_escaped(self):
        args = self.plan.imapsync_args()
        pairs = list(zip(args, args[1:]))
        excludes = [v for k, v in pairs if k == "--exclude"]
        self.assertTrue(all(e.startswith("^") and e.endswith("$") for e in excludes))
        # Ngoac vuong cua "[Gmail]" phai duoc escape, neu khong Perl doc thanh
        # character class va se exclude nham hang loat folder khac.
        self.assertIn("^" + BS + "[Gmail" + BS + "]$", excludes)

    def test_f1f2_uses_raw_imap_name(self):
        args = self.plan.imapsync_args()
        pairs = list(zip(args, args[1:]))
        maps = [v for k, v in pairs if k == "--f1f2"]
        self.assertIn("[Gmail]/Sent Mail=Sent", maps)


class TestPlanVietnamese(unittest.TestCase):
    """Ten folder doi theo ngon ngu account, phan loai van phai dung."""

    def setUp(self):
        self.plan = build_plan(parse(GMAIL_VI), SyncConf())

    def test_all_mail_still_excluded(self):
        self.assertIn(u"[Gmail]/Tất cả thư", {f.display for f, _ in self.plan.excluded})

    def test_special_folders_map_to_icewarp_english_names(self):
        self.assertEqual(
            {f.display: d for f, d in self.plan.mapped},
            {
                u"[Gmail]/Thư đã gửi": "Sent",
                u"[Gmail]/Thư nháp": "Drafts",
                u"[Gmail]/Thùng rác": "Trash",
                u"[Gmail]/Thư rác": "Spam",
            },
        )

    def test_user_label_keeps_raw_name_but_readable_display(self):
        label = [f for f in self.plan.kept if f.raw != "INBOX"][0]
        self.assertEqual(label.raw, "C&APQ-ng vi&Hsc-c/D&HvE- &AOE-n A")
        self.assertEqual(label.display, u"Công việc/Dự án A")

    def test_f1f2_sends_raw_utf7_name_to_imapsync(self):
        args = self.plan.imapsync_args()
        pairs = list(zip(args, args[1:]))
        maps = [v for k, v in pairs if k == "--f1f2"]
        self.assertIn("[Gmail]/Th&AbA- &AREA4w- g&Hu0-i=Sent", maps)


class TestPlanOptions(unittest.TestCase):
    def test_can_keep_all_mail(self):
        plan = build_plan(parse(GMAIL_EN), SyncConf(exclude_all_mail=False))
        self.assertNotIn("[Gmail]/All Mail", {f.raw for f, _ in plan.excluded})
        self.assertIn("[Gmail]/All Mail", [f.raw for f in plan.kept])

    def test_custom_junk_folder_name(self):
        plan = build_plan(parse(GMAIL_EN), SyncConf(junk_folder="Junk E-mail"))
        self.assertIn(("[Gmail]/Spam", "Junk E-mail"), [(f.raw, d) for f, d in plan.mapped])

    def test_noselect_container_always_excluded(self):
        plan = build_plan(
            parse(GMAIL_EN),
            SyncConf(exclude_all_mail=False, exclude_important=False, exclude_starred=False),
        )
        self.assertEqual([f.raw for f, _ in plan.excluded], ["[Gmail]"])

    def test_dest_name_equal_to_source_is_not_remapped(self):
        # Neu ten dich trung ten nguon thi khong can --f1f2
        plan = build_plan([_parse_list_line(imap_line("Sent", "Sent"))], SyncConf())
        self.assertEqual(plan.mapped, [])
        self.assertEqual([f.raw for f in plan.kept], ["Sent"])


class TestUtf7(unittest.TestCase):
    def test_decodes_known_samples(self):
        self.assertEqual(decode("Work/&ZeVnLIqe-"), u"Work/日本語")
        self.assertEqual(decode("&-"), "&")
        self.assertEqual(decode("INBOX"), "INBOX")
        self.assertEqual(decode("[Gmail]/Th&AbA- r&AOE-c"), u"[Gmail]/Thư rác")

    def test_malformed_input_preserved(self):
        self.assertEqual(decode("&BAD"), "&BAD")
        self.assertEqual(decode("&!!!-"), "&!!!-")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# Hop thu Gmail da tung import tu Outlook: ben canh folder chuan cua Gmail
# (ten tieng Viet, co SPECIAL-USE) con sot lai cac label kieu Outlook.
GMAIL_SAU_KHI_IMPORT_OUTLOOK = [
    imap_line("HasNoChildren", "INBOX"),
    imap_line("HasChildren Noselect", "[Gmail]"),
    imap_line("All HasNoChildren", "[Gmail]/T&HqU-t c&HqM- th&AbA-"),
    imap_line("HasNoChildren Sent", "[Gmail]/Th&AbA- &AREA4w- g&Hu0-i"),
    imap_line("Drafts HasNoChildren", "[Gmail]/Th&AbA- nh&AOE-p"),
    imap_line("HasNoChildren Trash", "[Gmail]/Th&APk-ng r&AOE-c"),
    imap_line("HasNoChildren Junk", "[Gmail]/Th&AbA- r&AOE-c"),
    imap_line("HasNoChildren", "Drafts"),        # sot lai tu Outlook
    imap_line("HasNoChildren", "Sent Items"),    # sot lai tu Outlook
    imap_line("HasNoChildren", "ESET Antispam"),
]


class TestDestinationCollisions(unittest.TestCase):
    def test_detects_label_colliding_with_mapped_folder(self):
        """Label 'Drafts' con sot va [Gmail]/Thu nhap deu ra 'Drafts' ben dich."""
        plan = build_plan(parse(GMAIL_SAU_KHI_IMPORT_OUTLOOK), SyncConf())
        collisions = dict((d, [f.display for f in s]) for d, s in plan.collisions())
        self.assertIn("Drafts", collisions)
        self.assertEqual(len(collisions["Drafts"]), 2)
        self.assertIn("Drafts", collisions["Drafts"])
        self.assertIn(u"[Gmail]/Thư nháp", collisions["Drafts"])

    def test_differently_named_leftover_does_not_collide(self):
        # 'Sent Items' khac ten voi 'Sent' nen khong tron
        plan = build_plan(parse(GMAIL_SAU_KHI_IMPORT_OUTLOOK), SyncConf())
        self.assertNotIn("Sent", dict(plan.collisions()))

    def test_clean_mailbox_has_no_collisions(self):
        self.assertEqual(build_plan(parse(GMAIL_EN), SyncConf()).collisions(), [])

    def test_renaming_dest_in_config_resolves_the_collision(self):
        plan = build_plan(parse(GMAIL_SAU_KHI_IMPORT_OUTLOOK),
                          SyncConf(drafts_folder="Drafts-gmail"))
        self.assertEqual(plan.collisions(), [])

    def test_collision_appears_when_two_specials_map_to_one_name(self):
        cfg = SyncConf(drafts_folder="Luu", trash_folder="Luu")
        plan = build_plan(parse(GMAIL_EN), cfg)
        self.assertEqual([d for d, _ in plan.collisions()], ["Luu"])

    def test_destinations_lists_every_transferred_folder(self):
        plan = build_plan(parse(GMAIL_SAU_KHI_IMPORT_OUTLOOK), SyncConf())
        dests = plan.destinations()
        self.assertEqual(sum(len(v) for v in dests.values()),
                         len(plan.mapped) + len(plan.kept))
        for name in ("INBOX", "Sent", "Trash", "Spam", "Sent Items", "ESET Antispam"):
            self.assertIn(name, dests)


class TestF1f2Separator(unittest.TestCase):
    """imapsync tach --f1f2 bang dau '=' (sub split_around_equal), khong phai ':'.

    Dung sai dau thi imapsync coi ca cum "nguon:dich" la mot ten folder, khong
    tim thay folder do, va bo qua mapping MA KHONG BAO LOI. Hau qua: folder dac
    biet cua Gmail giu nguyen ten "[Gmail]/..." ben dich, con Sent/Drafts/Trash
    that thi rong. Loi nay tung lot qua vi chinh test cung viet theo gia dinh sai.
    """

    def maps(self, plan):
        args = plan.imapsync_args()
        return [v for k, v in zip(args, args[1:]) if k == "--f1f2"]

    def test_uses_equals_not_colon(self):
        maps = self.maps(build_plan(parse(GMAIL_EN), SyncConf()))
        self.assertTrue(maps)
        for m in maps:
            self.assertIn("=", m)
        self.assertIn("[Gmail]/Sent Mail=Sent", maps)

    def test_colon_form_never_appears(self):
        for m in self.maps(build_plan(parse(GMAIL_EN), SyncConf())):
            self.assertNotIn(":", m)

    def test_split_on_first_equals_recovers_original_pair(self):
        """Mo phong dung cach imapsync doc: split(/=/, chuoi, 2)."""
        plan = build_plan(parse(GMAIL_VI), SyncConf())
        wanted = {f.raw: d for f, d in plan.mapped}
        for m in self.maps(plan):
            src, dest = m.split("=", 1)
            self.assertIn(src, wanted)
            self.assertEqual(wanted[src], dest)

    def test_source_name_containing_equals_is_reported_not_silently_broken(self):
        folders = parse([
            imap_line("HasNoChildren", "INBOX"),
            imap_line("HasNoChildren Sent", "[Gmail]/a=b"),
        ])
        plan = build_plan(folders, SyncConf())
        self.assertEqual([f.raw for f, _ in plan.unmappable], ["[Gmail]/a=b"])
        self.assertIn("[Gmail]/a=b", [f.raw for f in plan.kept])
        self.assertEqual(self.maps(plan), [])

    def test_normal_names_are_not_reported_as_unmappable(self):
        self.assertEqual(build_plan(parse(GMAIL_EN), SyncConf()).unmappable, [])
        self.assertEqual(build_plan(parse(GMAIL_VI), SyncConf()).unmappable, [])


# Byte 0 dung ngan ba truong cua SASL PLAIN. Dat qua bytes([0]) chu khong viet
# thang trong chuoi, theo dung ghi chu o dau file nay.
NUL = bytes([0])


class _FakeConn:
    """Ghi lai lenh dang nhap thay vi noi chuyen voi server that."""

    def __init__(self):
        self.logins = []
        self.auths = []

    def login(self, user, password):
        self.logins.append((user, password))

    def authenticate(self, mech, authobject):
        # imaplib goi callback moi lan server gui challenge.
        self.auths.append((mech, authobject(b"")))
        return "OK", [b"done"]


def master_side(style=MASTER_AUTHZID, sep="*"):
    return ServerConf("mail.cu.vn", 993, True, provider=providers.DOVECOT,
                      auth=AUTH_MASTER,
                      master=MasterConf(user="migrate", password="BiMat",
                                        style=style, separator=sep))


class TestMasterLogin(unittest.TestCase):
    """Duong dang nhap cua auth = master khi tool tu mo IMAP (discover,
    preflight, verify) -- khac duong cua imapsync nen phai kiem rieng."""

    def test_authzid_sends_mailbox_then_admin_then_password(self):
        server = master_side()
        conn = _FakeConn()
        _login(conn, server, server.login_for("an@cu.vn", ""))

        mech, payload = conn.auths[0]
        self.assertEqual(mech, "PLAIN")
        # RFC 4616: authzid (hop thu can mo), authcid (tai khoan dang nhap),
        # roi mat khau. Dao hai truong dau la dang nhap bang quyen cua khach
        # thay vi cua quan tri -- va server van tra ve OK, nen khong ai thay.
        self.assertEqual(payload,
                         b"an@cu.vn" + NUL + b"migrate" + NUL + b"BiMat")
        self.assertEqual(conn.logins, [])

    def test_second_challenge_gets_an_empty_answer(self):
        """Server tu choi thi no gui challenge lan hai va cho mot dong rong.
        Gui lai bi mat o day se treo phien."""
        server = master_side()
        callback = _Plain(server.login_for("an@cu.vn", ""))
        self.assertTrue(callback(b""))
        self.assertEqual(callback(b"loi gi do"), b"")

    def test_separator_style_uses_a_plain_login(self):
        server = master_side(style=MASTER_SEPARATOR)
        conn = _FakeConn()
        _login(conn, server, server.login_for("an@cu.vn", ""))
        self.assertEqual(conn.logins, [("an@cu.vn*migrate", "BiMat")])
        self.assertEqual(conn.auths, [])

    def test_password_auth_is_untouched(self):
        server = ServerConf("mail.cu.vn", 993, True, provider=providers.DOVECOT)
        conn = _FakeConn()
        _login(conn, server, server.login_for("an@cu.vn", "MatKhauCuaAn"))
        self.assertEqual(conn.logins, [("an@cu.vn", "MatKhauCuaAn")])
        self.assertEqual(conn.auths, [])

    def test_non_ascii_password_is_sent_as_utf8(self):
        server = master_side()
        server.master.password = "MatKhau"  # noqa: giu ascii o day
        login = server.login_for("an@cu.vn", "")
        login.password = "Biật"
        self.assertIn("Biật".encode("utf-8"), _Plain(login).data)


class TestSpecialUseRoles(unittest.TestCase):
    """Doc co SPECIAL-USE tu danh sach LIST cua ben dich."""

    def roles(self, lines):
        return special_use_roles(parse(lines))

    def test_reads_every_role_the_server_flags(self):
        got = self.roles(GMAIL_EN)
        self.assertEqual(got, {"sent": "[Gmail]/Sent Mail",
                               "drafts": "[Gmail]/Drafts",
                               "trash": "[Gmail]/Trash",
                               "junk": "[Gmail]/Spam"})

    def test_all_mail_is_not_an_archive_folder(self):
        """Gmail gan co All cho All Mail. Coi no la folder luu tru thi moi
        mail trong hop thu se do vao do lan thu hai."""
        self.assertNotIn("archive", self.roles(GMAIL_EN))

    def test_returns_the_raw_name_not_the_decoded_one(self):
        """Ten nay di thang vao --f1f2, ma imapsync noi chuyen bang ten tho."""
        got = self.roles(GMAIL_VI)
        self.assertNotIn("Thư đã gửi", got["sent"])
        self.assertEqual(decode(got["sent"]), "[Gmail]/Thư đã gửi")

    def test_a_container_folder_is_never_a_role(self):
        """Folder Noselect khong SELECT duoc thi cung khong chua mail duoc."""
        lines = [imap_line("Noselect Sent", "Archive"),
                 imap_line("HasNoChildren Sent", "Sent Items")]
        self.assertEqual(self.roles(lines), {"sent": "Sent Items"})

    def test_a_server_that_flags_nothing_gives_nothing(self):
        lines = [imap_line("HasNoChildren", "INBOX"),
                 imap_line("HasNoChildren", "Sent Items")]
        self.assertEqual(self.roles(lines), {})


# Nguon kieu Dovecot/cPanel: tien to "INBOX." va dau phan cach "."; dich phang
# voi dau phan cach "/". Day la cap hay gap nhat cua mot nha cung cap.
DOVECOT_CO_DAU_BANG = [
    imap_line("HasNoChildren", "INBOX", delim="."),
    imap_line("HasNoChildren", "INBOX.Bao gia = 2024", delim="."),
    imap_line("HasNoChildren", "INBOX.Cong viec", delim="."),
]


class TestDestOfKnowsWhereEachFolderLands(unittest.TestCase):
    """Ke hoach phai biet folder nguon nao sang folder dich nao -- KE CA nhung
    folder khong sinh --f1f2.

    Truoc day verify tu doan "khong nam trong mapped thi ten dich = ten nguon".
    Voi folder co dau '=' thi doan sai: khong co --f1f2 nhung imapsync VAN tu
    cat tien to va doi dau phan cach, nen ten dich khac ten nguon. Do that tren
    rig: "INBOX.Bao gia = 2024" sang dich thanh "Bao gia = 2024"; verify di tim
    theo ten nguon thi "khong mo duoc folder" va bao ca hop thu la LECH trong
    khi sync da chay dung.
    """

    def setUp(self):
        self.plan = build_plan(parse(DOVECOT_CO_DAU_BANG), SyncConf(),
                               prefix="INBOX.")

    def pairs(self):
        return {f.raw: dest for f, dest in self.plan.sync_pairs()}

    def test_folder_co_dau_bang_van_biet_ten_dich(self):
        self.assertEqual(self.pairs()["INBOX.Bao gia = 2024"], "Bao gia = 2024")

    def test_folder_thuong_van_nhu_cu(self):
        self.assertEqual(self.pairs()["INBOX.Cong viec"], "Cong viec")

    def test_moi_folder_se_chuyen_deu_co_mat(self):
        se_chuyen = {f.raw for f, _ in self.plan.mapped} | {f.raw for f in self.plan.kept}
        self.assertEqual(set(self.pairs()), se_chuyen)

    def test_khong_canh_bao_khi_ten_tu_suy_ra_da_dung(self):
        """Folder thuong co dau '=': imapsync tu ra dung ten, khong co gi de
        bao. Canh bao thua thi nguoi ta di doi ten folder ben nguon vo ich."""
        self.assertEqual(self.plan.unmappable, [])

    def test_van_canh_bao_khi_ten_mong_muon_khac(self):
        """Folder dac biet co dau '=': ten dich lay tu cau hinh/SPECIAL-USE,
        khac han ten tu suy ra -- luc nay mat --f1f2 la mat that."""
        folders = parse([
            imap_line("HasNoChildren", "INBOX", delim="."),
            imap_line("HasNoChildren Sent", "INBOX.Da gui = cu", delim="."),
        ])
        plan = build_plan(folders, SyncConf(), prefix="INBOX.")
        self.assertEqual([f.raw for f, _ in plan.unmappable], ["INBOX.Da gui = cu"])
        # Va ten dich that su van la ten imapsync tu dat, khong phai "Sent"
        self.assertEqual(dict((f.raw, d) for f, d in plan.sync_pairs())
                         ["INBOX.Da gui = cu"], "Da gui = cu")
