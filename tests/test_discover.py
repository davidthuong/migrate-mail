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

from migrate_mail.config import SyncConf
from migrate_mail.discover import _parse_list_line, build_plan
from migrate_mail.imaputf7 import decode

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
        self.assertIn("[Gmail]/Sent Mail:Sent", maps)


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
        self.assertIn("[Gmail]/Th&AbA- &AREA4w- g&Hu0-i:Sent", maps)


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
