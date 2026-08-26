# -*- coding: utf-8 -*-
"""Test doi chieu ngay thang giua hai dau."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_mail import verify
from migrate_mail.config import Config, Paths, ServerConf, SyncConf
from migrate_mail.runner import build_command
from migrate_mail.users import User
from pathlib import Path


def fetch_head(seq, internaldate):
    return ('%d (INTERNALDATE "%s" BODY[HEADER.FIELDS (MESSAGE-ID)] {40}'
            % (seq, internaldate)).encode()


def fetch_item(seq, internaldate, msgid):
    body = ("Message-Id: %s\r\n\r\n" % msgid).encode()
    return (fetch_head(seq, internaldate), body)


class TestParseInternaldate(unittest.TestCase):
    def test_reads_a_normal_date(self):
        epoch = verify.parse_internaldate(fetch_head(1, "17-Mar-2024 09:15:30 +0700"))
        self.assertIsNotNone(epoch)

    def test_same_instant_in_different_timezones_is_equal(self):
        """Hai dau ghi mui gio khac nhau van phai ra cung mot thoi diem."""
        hanoi = verify.parse_internaldate(fetch_head(1, "17-Mar-2024 09:00:00 +0700"))
        utc = verify.parse_internaldate(fetch_head(1, "17-Mar-2024 02:00:00 +0000"))
        self.assertEqual(hanoi, utc)

    def test_different_instants_are_not_equal(self):
        a = verify.parse_internaldate(fetch_head(1, "17-Mar-2024 09:00:00 +0700"))
        b = verify.parse_internaldate(fetch_head(1, "18-Mar-2024 09:00:00 +0700"))
        self.assertNotEqual(a, b)
        self.assertAlmostEqual(b - a, 86400, delta=1)

    def test_garbage_returns_none(self):
        self.assertIsNone(verify.parse_internaldate(b"khong co ngay o day"))
        self.assertIsNone(verify.parse_internaldate(b""))


class TestParseMessageId(unittest.TestCase):
    def test_reads_message_id(self):
        self.assertEqual(
            verify.parse_message_id(b"Message-Id: <abc@gmail.com>\r\n\r\n"),
            "<abc@gmail.com>")

    def test_case_insensitive(self):
        self.assertEqual(
            verify.parse_message_id(b"MESSAGE-ID: <x@y.z>\r\n"), "<x@y.z>")

    def test_missing_gives_empty(self):
        self.assertEqual(verify.parse_message_id(b"Subject: hi\r\n"), "")


class TestParseFetchResponse(unittest.TestCase):
    def test_builds_map(self):
        data = [
            fetch_item(1, "17-Mar-2024 09:00:00 +0700", "<a@x.com>"), b")",
            fetch_item(2, "18-Mar-2024 09:00:00 +0700", "<b@x.com>"), b")",
        ]
        out = verify.parse_fetch_response(data)
        self.assertEqual(sorted(out), ["<a@x.com>", "<b@x.com>"])

    def test_skips_entries_without_message_id(self):
        data = [(fetch_head(1, "17-Mar-2024 09:00:00 +0700"), b"Subject: no id\r\n")]
        self.assertEqual(verify.parse_fetch_response(data), {})

    def test_empty_input_is_safe(self):
        self.assertEqual(verify.parse_fetch_response([]), {})
        self.assertEqual(verify.parse_fetch_response(None), {})


class TestSampleSequenceSet(unittest.TestCase):
    def test_takes_everything_when_below_cap(self):
        self.assertEqual(verify.sample_sequence_set(50, 200), "1:50")

    def test_cap_zero_means_everything(self):
        self.assertEqual(verify.sample_sequence_set(9999, 0), "1:9999")

    def test_samples_spread_across_the_folder(self):
        seq = verify.sample_sequence_set(1000, 10)
        nums = [int(x) for x in seq.split(",")]
        self.assertLessEqual(len(nums), 10)
        self.assertEqual(nums, sorted(nums))
        self.assertGreaterEqual(nums[0], 1)
        self.assertLessEqual(nums[-1], 1000)
        # Phai trai deu chu khong dồn ve dau folder
        self.assertGreater(nums[-1], 800)

    def test_empty_folder(self):
        self.assertEqual(verify.sample_sequence_set(0, 200), "")


class TestFolderMessageCount(unittest.TestCase):
    def test_reads_exists_count(self):
        self.assertEqual(verify.folder_message_count([b"1234"]), 1234)

    def test_empty_response(self):
        self.assertEqual(verify.folder_message_count([]), 0)
        self.assertEqual(verify.folder_message_count(None), 0)


class TestQuoteFolder(unittest.TestCase):
    def test_wraps_names_with_spaces(self):
        self.assertEqual(verify.quote_folder("[Gmail]/Sent Mail"),
                         '"[Gmail]/Sent Mail"')

    def test_escapes_quotes_and_backslashes(self):
        bs = chr(92)
        self.assertEqual(verify.quote_folder('a"b'), '"a' + bs + '"b"')
        self.assertEqual(verify.quote_folder("a" + bs + "b"),
                         '"a' + bs + bs + 'b"')


class TestCompareIndexes(unittest.TestCase):
    def test_all_matching(self):
        src = {"<a>": 1000.0, "<b>": 2000.0}
        compared, matched, mismatched, samples = verify.compare_indexes(src, dict(src))
        self.assertEqual((compared, matched, mismatched), (2, 2, 0))
        self.assertEqual(samples, [])

    def test_small_drift_is_tolerated(self):
        src = {"<a>": 1000.0}
        dst = {"<a>": 1001.0}
        _c, matched, mismatched, _s = verify.compare_indexes(src, dst)
        self.assertEqual((matched, mismatched), (1, 0))

    def test_dates_reset_to_migration_time_are_caught(self):
        """Trieu chung that: moi mail deu mang cung mot ngay moi."""
        migrate_time = 1_800_000_000.0
        src = {"<a>": 1000.0, "<b>": 2000.0, "<c>": 3000.0}
        dst = {k: migrate_time for k in src}
        compared, matched, mismatched, samples = verify.compare_indexes(src, dst)
        self.assertEqual((compared, matched, mismatched), (3, 0, 3))
        self.assertEqual(len(samples), 3)

    def test_messages_absent_on_dest_are_not_counted_as_compared(self):
        src = {"<a>": 1000.0, "<b>": 2000.0}
        dst = {"<a>": 1000.0}
        compared, matched, mismatched, _s = verify.compare_indexes(src, dst)
        self.assertEqual((compared, matched, mismatched), (1, 1, 0))

    def test_sample_list_is_capped(self):
        src = {"<%d>" % i: 1000.0 for i in range(50)}
        dst = {k: 9999.0 for k in src}
        _c, _m, mismatched, samples = verify.compare_indexes(src, dst, max_samples=3)
        self.assertEqual(mismatched, 50)
        self.assertEqual(len(samples), 3)


def make_cfg(**kw):
    return Config(
        source=ServerConf("imap.gmail.com", 993, True),
        dest=ServerConf("mail.congty.vn", 993, True),
        sync=SyncConf(**kw),
        paths=Paths(imapsync="imapsync", logdir=Path("logs"), statedir=Path("state")),
        path=Path("config.ini"),
    )


USER = User("an@cu.com", "apppassword16chr", "an@moi.vn", "MatKhau", row=2)


class TestDateFlagsInCommand(unittest.TestCase):
    def build(self, **kw):
        return build_command(make_cfg(**kw), USER, None, "sync",
                             Path("/s/a.pass"), Path("/s/b.pass"), Path("/s"))

    def test_internal_date_is_the_default_and_is_explicit(self):
        """Khong dua vao mac dinh ngam cua imapsync -- viet ra de nhin thay trong log."""
        cmd = self.build()
        self.assertIn("--syncinternaldates", cmd)
        self.assertNotIn("--idatefromheader", cmd)

    def test_header_mode_switches_flag(self):
        cmd = self.build(date_source="header")
        self.assertIn("--idatefromheader", cmd)
        self.assertNotIn("--syncinternaldates", cmd)

    def test_the_two_flags_are_never_both_present(self):
        # imapsync tat syncinternaldates khi idatefromheader bat; gui ca hai
        # chi lam log kho doc.
        for mode in ("internal", "header"):
            cmd = self.build(date_source=mode)
            both = ("--syncinternaldates" in cmd) and ("--idatefromheader" in cmd)
            self.assertFalse(both, mode)


class TestDateSourceConfigValidation(unittest.TestCase):
    def test_rejects_unknown_value(self):
        from migrate_mail.config import _date_source
        with self.assertRaises(ValueError):
            _date_source("hom-qua")

    def test_accepts_known_values_case_insensitively(self):
        from migrate_mail.config import _date_source
        self.assertEqual(_date_source("INTERNAL"), "internal")
        self.assertEqual(_date_source(" Header "), "header")


if __name__ == "__main__":
    unittest.main(verbosity=2)
