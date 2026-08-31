# -*- coding: utf-8 -*-
"""Test phan loai folder cho tung nha cung cap, va cau hinh provider.

Cung quy uoc voi test_discover: KHONG viet ky tu backslash truc tiep trong
source, cac co IMAP duoc gan backslash o runtime bang imap_line.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_mail import providers
from migrate_mail.config import ServerConf, SyncConf
from migrate_mail.discover import (Layout, build_plan, invert_separator,
                                   resolve_layout)
from migrate_mail.providers import (ROLE_JUNK, ROLE_SENT, Provider, fold,
                                    strip_namespace)

from test_discover import GMAIL_EN, imap_line, parse


def plan_for(lines, provider, prefix="", dest=None, **sync_kwargs):
    return build_plan(parse(lines), SyncConf(**sync_kwargs), provider, prefix,
                      dest)


def mapping(plan):
    return {f.display: dest for f, dest in plan.mapped}


def excluded(plan):
    return {f.display for f, _reason in plan.excluded}


def kept(plan):
    return {f.display for f in plan.kept}


# --------------------------------------------------------------------------- #
# Bang tra ten
# --------------------------------------------------------------------------- #

class TestFold(unittest.TestCase):
    def test_ignores_case_spacing_and_punctuation(self):
        self.assertEqual(fold("Junk E-mail"), fold("junk email"))
        self.assertEqual(fold("Sent Items"), "sentitems")

    def test_strips_vietnamese_accents(self):
        self.assertEqual(fold(u"Thư đã gửi"), "thudagui")
        self.assertEqual(fold(u"Thùng rác"), "thungrac")

    def test_d_with_stroke_is_not_lost(self):
        """'d' gach ngang khong tach ra duoc bang NFD -- neu quen doi tay thi
        no bien mat va "Da gui" thanh "agui", khong khop bang nao ca."""
        self.assertEqual(fold(u"Đã gửi"), "dagui")


class TestLookup(unittest.TestCase):
    def test_finds_by_key_and_alias(self):
        self.assertIs(providers.get("m365"), providers.M365)
        self.assertIs(providers.get("office365"), providers.M365)
        self.assertIs(providers.get("O365"), providers.M365)
        self.assertIs(providers.get("cPanel"), providers.DOVECOT)

    def test_unknown_name_lists_valid_ones(self):
        with self.assertRaises(ValueError) as ctx:
            providers.get("hotmail")
        self.assertIn("gmail", str(ctx.exception))

    def test_empty_falls_back_to_default(self):
        self.assertIs(providers.get("", providers.ICEWARP), providers.ICEWARP)


class TestNamespace(unittest.TestCase):
    def test_strips_prefix(self):
        self.assertEqual(strip_namespace("INBOX.Sent", "INBOX."), "Sent")

    def test_inbox_itself_is_untouched(self):
        self.assertEqual(strip_namespace("INBOX", "INBOX."), "INBOX")

    def test_no_prefix_changes_nothing(self):
        self.assertEqual(strip_namespace("INBOX/Luu", ""), "INBOX/Luu")


# --------------------------------------------------------------------------- #
# Microsoft 365 / Exchange
# --------------------------------------------------------------------------- #

# Exchange khong phai luc nao cung quang ba SPECIAL-USE: bang duoi la truong
# hop xau nhat, khong co co nao ca, chi con ten folder de nhin.
M365_NO_FLAGS = [
    imap_line("HasNoChildren", "INBOX"),
    imap_line("HasNoChildren", "Sent Items"),
    imap_line("HasNoChildren", "Deleted Items"),
    imap_line("HasNoChildren", "Junk Email"),
    imap_line("HasNoChildren", "Drafts"),
    imap_line("HasNoChildren", "Outbox"),
    imap_line("HasChildren", "Sync Issues"),
    imap_line("HasNoChildren", "Sync Issues/Conflicts"),
    imap_line("HasNoChildren", "Conversation History"),
    imap_line("HasNoChildren", "Khach hang"),
]


class TestMicrosoft365(unittest.TestCase):
    def setUp(self):
        self.plan = plan_for(M365_NO_FLAGS, providers.M365)

    def test_maps_outlook_names_without_special_use_flags(self):
        self.assertEqual(mapping(self.plan), {
            "Sent Items": "Sent",
            "Deleted Items": "Trash",
            "Junk Email": "Spam",
        })

    def test_drafts_already_has_the_right_name(self):
        self.assertIn("Drafts", kept(self.plan))

    def test_drops_folders_that_are_not_mail(self):
        self.assertEqual(
            excluded(self.plan),
            {"Outbox", "Sync Issues", "Sync Issues/Conflicts",
             "Conversation History"})

    def test_child_of_a_dropped_folder_goes_with_its_parent(self):
        """Sync Issues/Conflicts phai di theo cha chu khong duoc chep sang."""
        self.assertIn("Sync Issues/Conflicts", excluded(self.plan))

    def test_user_folder_is_untouched(self):
        self.assertIn("Khach hang", kept(self.plan))

    def test_special_use_flag_wins_over_the_name(self):
        """Khi Exchange CO gan co, co la thu duoc tin -- ten chi la du phong."""
        plan = plan_for([imap_line("HasNoChildren Sent", "Muc da Gui")],
                        providers.M365)
        self.assertEqual(mapping(plan), {"Muc da Gui": "Sent"})

    def test_supports_oauth_and_password(self):
        self.assertTrue(providers.M365.supports(providers.AUTH_OAUTH2))
        self.assertTrue(providers.M365.supports(providers.AUTH_PASSWORD))


# --------------------------------------------------------------------------- #
# cPanel / DirectAdmin (Dovecot, Courier)
# --------------------------------------------------------------------------- #

# Hosting kieu Maildir++: moi folder nam duoi "INBOX." va dau phan cach la '.'
CPANEL = [
    imap_line("HasNoChildren", "INBOX", "."),
    imap_line("HasNoChildren", "INBOX.Sent", "."),
    imap_line("HasNoChildren", "INBOX.Drafts", "."),
    imap_line("HasNoChildren", "INBOX.Trash", "."),
    imap_line("HasNoChildren", "INBOX.spam", "."),
    imap_line("HasNoChildren", "INBOX.C&APQ-ng vi&Hsc-c", "."),
]


class TestDovecotPrefix(unittest.TestCase):
    def setUp(self):
        self.plan = plan_for(CPANEL, providers.DOVECOT, prefix="INBOX.")

    def test_prefix_is_cut_off_on_the_destination(self):
        """Khong cat thi ben dich moc ra mot folder ten "INBOX" chua tat ca."""
        self.assertEqual(mapping(self.plan)[u"INBOX.Công việc"],
                         "C&APQ-ng vi&Hsc-c")

    def test_special_folders_map_by_name(self):
        maps = mapping(self.plan)
        self.assertEqual(maps["INBOX.Sent"], "Sent")
        self.assertEqual(maps["INBOX.Trash"], "Trash")
        self.assertEqual(maps["INBOX.spam"], "Spam")

    def test_inbox_stays_inbox(self):
        self.assertIn("INBOX", kept(self.plan))

    def test_f1f2_keeps_the_raw_source_name(self):
        args = self.plan.imapsync_args()
        maps = [v for k, v in zip(args, args[1:]) if k == "--f1f2"]
        self.assertIn("INBOX.Sent=Sent", maps)
        self.assertIn("INBOX.C&APQ-ng vi&Hsc-c=C&APQ-ng vi&Hsc-c", maps)

    def test_without_a_namespace_the_names_are_left_alone(self):
        """Server khong co tien to: "INBOX/Luu" that su la con cua INBOX."""
        plan = plan_for([imap_line("HasNoChildren", "INBOX/Luu")],
                        providers.DOVECOT)
        self.assertIn("INBOX/Luu", kept(plan))


class TestNameFallbackDepth(unittest.TestCase):
    def test_only_top_level_folders_are_matched_by_name(self):
        """"Luu tru/Sent 2019" la folder luu tru cua nguoi dung, khong phai
        folder Sent -- doi ten no se tron mail cu vao Sent that."""
        plan = plan_for([imap_line("HasNoChildren", "Luu tru/Sent")],
                        providers.IMAP)
        self.assertIn("Luu tru/Sent", kept(plan))

    def test_gmail_does_not_guess_by_name(self):
        """Gmail gan co cho du folder cua no, nen mot label ten "Sent Items"
        con sot lai tu lan import Outlook la label thuong, phai giu nguyen."""
        plan = plan_for(GMAIL_EN + [imap_line("HasNoChildren", "Sent Items")],
                        providers.GMAIL)
        self.assertIn("Sent Items", kept(plan))
        self.assertNotIn("Sent Items", mapping(plan))


# --------------------------------------------------------------------------- #
# Zimbra
# --------------------------------------------------------------------------- #

ZIMBRA_LIST = [
    imap_line("HasNoChildren", "INBOX"),
    imap_line("HasNoChildren", "Sent"),
    imap_line("HasNoChildren", "Junk"),
    imap_line("HasNoChildren", "Contacts"),
    imap_line("HasNoChildren", "Emailed Contacts"),
    imap_line("HasNoChildren", "Chats"),
    imap_line("HasNoChildren", "Bao gia"),
]


class TestZimbra(unittest.TestCase):
    def setUp(self):
        self.plan = plan_for(ZIMBRA_LIST, providers.ZIMBRA)

    def test_pim_folders_are_not_copied(self):
        """Zimbra bay ca danh ba va lich su chat ra duong IMAP; chep sang la
        do rac vao hop thu moi."""
        self.assertEqual(excluded(self.plan),
                         {"Contacts", "Emailed Contacts", "Chats"})

    def test_junk_maps_to_the_configured_name(self):
        self.assertEqual(mapping(self.plan)["Junk"], "Spam")

    def test_mail_folders_survive(self):
        self.assertEqual(kept(self.plan), {"INBOX", "Sent", "Bao gia"})


# --------------------------------------------------------------------------- #
# Ten folder mac dinh cua ben dich
# --------------------------------------------------------------------------- #

class TestDestinationDefaults(unittest.TestCase):
    def test_icewarp_calls_junk_spam(self):
        self.assertEqual(providers.ICEWARP.folder_default(ROLE_JUNK, "x"), "Spam")

    def test_exchange_uses_outlook_names(self):
        self.assertEqual(providers.M365.folder_default(ROLE_JUNK, "x"), "Junk Email")
        self.assertEqual(providers.M365.folder_default(ROLE_SENT, "x"), "Sent Items")

    def test_unknown_role_falls_back(self):
        self.assertEqual(providers.IMAP.folder_default(ROLE_JUNK, "Spam"), "Spam")


# --------------------------------------------------------------------------- #
# Tien to cua ben DICH
# --------------------------------------------------------------------------- #

# Hosting Maildir++ lam dich: moi folder phai nam duoi "INBOX." va dau phan
# cach la '.'. Khong tinh dieu nay thi mail do vao mot folder ten "Sent" nam
# ngoai INBOX -- co server tao ra, co server tu choi han.
MAILDIR_DEST = Layout(prefix="INBOX.", delim=".")


class TestDestinationPrefix(unittest.TestCase):
    def setUp(self):
        self.plan = plan_for(GMAIL_EN, providers.GMAIL, dest=MAILDIR_DEST)
        self.maps = mapping(self.plan)

    def test_special_folders_land_under_the_prefix(self):
        self.assertEqual(self.maps["[Gmail]/Sent Mail"], "INBOX.Sent")
        self.assertEqual(self.maps["[Gmail]/Spam"], "INBOX.Spam")

    def test_inbox_never_gets_the_prefix(self):
        """INBOX la ten dac biet cua giao thuc IMAP; "INBOX.INBOX" la mot
        folder khac han va mail se do nham vao do."""
        self.assertIn("INBOX", kept(self.plan))
        self.assertNotIn("INBOX", self.maps)

    def test_nested_folders_get_the_destination_separator(self):
        self.assertEqual(self.maps["Work/Project A"], "INBOX.Work.Project A")

    def test_a_dot_in_a_source_name_does_not_become_a_new_level(self):
        """Nguon dung '/' lam dau phan cach nen dau '.' trong ten chi la ky tu
        thuong. De nguyen thi ben dich doc no thanh mot cap thu muc moi."""
        plan = plan_for([imap_line("HasNoChildren", "Bao gia v1.2")],
                        providers.IMAP, dest=MAILDIR_DEST)
        self.assertEqual(mapping(plan)["Bao gia v1.2"], "INBOX.Bao gia v1/2")

    def test_configured_name_that_already_has_the_prefix_is_left_alone(self):
        """Nguoi dung viet san "INBOX.Sent" trong config thi phai ra dung the,
        khong phai "INBOX.INBOX.Sent"."""
        plan = plan_for(GMAIL_EN, providers.GMAIL, dest=MAILDIR_DEST,
                        sent_folder="INBOX.Sent")
        self.assertEqual(mapping(plan)["[Gmail]/Sent Mail"], "INBOX.Sent")

    def test_same_layout_on_both_sides_leaves_names_where_they_are(self):
        """cPanel -> cPanel: cat tien to ben nguon roi them lai y het ben dich,
        nen ket qua phai la ten cu chu khong phai mot cay folder moi.

        Rieng "INBOX.spam" van doi ten: nguon goi folder rac la "spam" con
        config dat ten dich la "Spam". Do la doi ten do CAU HINH, khong phai
        do tien to -- va discover se canh bao neu ben dich chua co ten do.
        """
        plan = plan_for(CPANEL, providers.DOVECOT, prefix="INBOX.",
                        dest=MAILDIR_DEST)
        self.assertEqual(
            kept(plan),
            {"INBOX", "INBOX.Sent", "INBOX.Drafts", "INBOX.Trash",
             u"INBOX.Công việc"})
        self.assertEqual(mapping(plan), {"INBOX.spam": "INBOX.Spam"})

    def test_folder_names_survive_a_round_trip_through_the_same_layout(self):
        """Chan lai loi de mac nhat: cat tien to ben nguon nhung quen them lai
        ben dich, the la moi folder bi keo ra ngoai INBOX."""
        plan = plan_for(CPANEL, providers.DOVECOT, prefix="INBOX.",
                        dest=MAILDIR_DEST)
        for name in plan.destinations():
            self.assertTrue(name == "INBOX" or name.startswith("INBOX."),
                            "'%s' nam ngoai INBOX" % name)

    def test_no_destination_layout_keeps_the_old_behaviour(self):
        plan = plan_for(GMAIL_EN, providers.GMAIL)
        self.assertEqual(mapping(plan)["[Gmail]/Sent Mail"], "Sent")


class TestSeparatorInversion(unittest.TestCase):
    def test_swaps_the_two_characters(self):
        self.assertEqual(invert_separator("A/B.C", "/", "."), "A.B/C")

    def test_nothing_to_do_when_they_match(self):
        self.assertEqual(invert_separator("A/B", "/", "/"), "A/B")

    def test_unknown_destination_separator_changes_nothing(self):
        self.assertEqual(invert_separator("A/B", "/", ""), "A/B")


class TestResolveLayout(unittest.TestCase):
    def conf(self, prefix):
        return ServerConf("mail.vn", 993, True, provider=providers.DOVECOT,
                          prefix=prefix)

    def test_auto_takes_what_the_server_said(self):
        got = resolve_layout(self.conf("auto"), Layout("INBOX.", "."))
        self.assertEqual((got.prefix, got.delim), ("INBOX.", "."))

    def test_none_ignores_what_the_server_said(self):
        got = resolve_layout(self.conf("none"), Layout("INBOX.", "."))
        self.assertEqual(got.prefix, "")

    def test_a_written_prefix_overrides_the_server(self):
        """Cho server tra ve NAMESPACE sai -- co that, nhat la ban Courier cu."""
        got = resolve_layout(self.conf("Mail."), Layout("INBOX.", "."))
        self.assertEqual(got.prefix, "Mail.")
        self.assertEqual(got.delim, ".", "dau phan cach van lay tu server")


class TestCustomProvider(unittest.TestCase):
    """Them mot nguon moi phai la khai bao du lieu, khong phai sua logic."""

    def test_a_provider_declared_inline_classifies_folders(self):
        mdaemon = Provider(
            key="mdaemon", name="MDaemon",
            extra_names={fold("Junk E-mail"): ROLE_JUNK},
            skip_names={fold("Public Folders"): "folder chung, khong phai mail"},
        )
        plan = plan_for([
            imap_line("HasNoChildren", "Junk E-mail"),
            imap_line("HasNoChildren", "Public Folders"),
            imap_line("HasNoChildren", "Du an"),
        ], mdaemon)
        self.assertEqual(mapping(plan), {"Junk E-mail": "Spam"})
        self.assertEqual(excluded(plan), {"Public Folders"})
        self.assertEqual(kept(plan), {"Du an"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
