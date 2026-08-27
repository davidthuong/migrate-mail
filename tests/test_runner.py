# -*- coding: utf-8 -*-
"""Test dung lenh imapsync va doc output cua no."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_mail.config import Config, Paths, ServerConf, SyncConf
from migrate_mail.discover import _parse_list_line, build_plan
from migrate_mail.runner import (MODE_DRY, MODE_SYNC, build_command, parse_output,
                                 _redact, _write_secret)
from migrate_mail.users import User

from test_discover import GMAIL_EN, parse


def make_cfg(**sync_kwargs) -> Config:
    return Config(
        source=ServerConf("imap.gmail.com", 993, True),
        dest=ServerConf("mail.congty.vn", 993, True),
        sync=SyncConf(**sync_kwargs),
        paths=Paths(imapsync="imapsync", logdir=Path("logs"), statedir=Path("state")),
        path=Path("config.ini"),
    )


USER = User("an@cu.com", "apppassword16chr", "an@moi.vn", "MatKhau", row=2)


def build(cfg=None, mode=MODE_SYNC, plan=None, since_days=0):
    cfg = cfg or make_cfg()
    if plan is None:
        plan = build_plan(parse(GMAIL_EN), cfg.sync)
    return build_command(cfg, USER, plan, mode, Path("/s/src.pass"), Path("/s/dst.pass"),
                         Path("/s"), since_days)


def pairs(cmd):
    return list(zip(cmd, cmd[1:]))


class TestBuildCommand(unittest.TestCase):
    def test_passwords_never_appear_on_command_line(self):
        """Tham so dong lenh hien trong `ps aux` cho moi user tren may."""
        cmd = build()
        self.assertNotIn(USER.src_password, cmd)
        self.assertNotIn(USER.dst_password, cmd)
        self.assertIn("--passfile1", cmd)
        self.assertIn("--passfile2", cmd)

    def test_uses_both_hosts_and_ports(self):
        cmd = build()
        p = pairs(cmd)
        self.assertIn(("--host1", "imap.gmail.com"), p)
        self.assertIn(("--host2", "mail.congty.vn"), p)
        self.assertIn(("--port1", "993"), p)
        self.assertIn(("--port2", "993"), p)
        self.assertIn("--ssl1", cmd)
        self.assertIn("--ssl2", cmd)

    def test_plain_connection_uses_notls(self):
        cfg = make_cfg()
        cfg.dest = ServerConf("mail.congty.vn", 143, False)
        cmd = build(cfg)
        self.assertIn("--notls2", cmd)
        self.assertNotIn("--ssl2", cmd)

    def test_per_user_pidfile_and_tmpdir(self):
        """Chay song song ma dung chung pidfile thi imapsync tu choi khoi dong."""
        cmd = build()
        p = pairs(cmd)
        self.assertIn(("--tmpdir", str(Path("/s"))), p)
        self.assertIn(("--pidfile", str(Path("/s/imapsync.pid"))), p)

    def test_gmail_exclusions_present(self):
        cmd = build()
        excludes = [v for k, v in pairs(cmd) if k == "--exclude"]
        self.assertEqual(len(excludes), 4)  # [Gmail], All Mail, Important, Starred

    def test_folder_mapping_present(self):
        cmd = build()
        maps = [v for k, v in pairs(cmd) if k == "--f1f2"]
        self.assertIn("[Gmail]/Sent Mail=Sent", maps)
        self.assertIn("[Gmail]/Spam=Spam", maps)

    def test_message_id_used_for_identity(self):
        self.assertIn(("--useheader", "Message-Id"), pairs(build()))

    def test_addheader_always_on(self):
        # Mail thieu Message-Id se bi chep lai o moi vong delta neu khong co no
        self.assertIn("--addheader", build())

    def test_maxsize_omitted_when_zero(self):
        self.assertNotIn("--maxsize", build(make_cfg(maxsize=0)))
        self.assertIn(("--maxsize", "52428800"), pairs(build(make_cfg(maxsize=52428800))))

    def test_throttle_omitted_when_zero(self):
        self.assertNotIn("--maxbytespersecond", build(make_cfg(maxbytespersecond=0)))
        self.assertIn(("--maxbytespersecond", "2097152"),
                      pairs(build(make_cfg(maxbytespersecond=2097152))))

    def test_since_days_maps_to_maxage(self):
        self.assertNotIn("--maxage", build())
        self.assertIn(("--maxage", "7"), pairs(build(since_days=7)))

    def test_dry_mode_adds_dry_flag(self):
        self.assertNotIn("--dry", build())
        self.assertIn("--dry", build(mode=MODE_DRY))

    def test_filterflags_toggle(self):
        self.assertIn("--filterflags", build(make_cfg(filterflags=True)))
        self.assertNotIn("--filterflags", build(make_cfg(filterflags=False)))

    def test_skipcrossduplicates_off_by_default(self):
        self.assertNotIn("--skipcrossduplicates", build())
        self.assertIn("--skipcrossduplicates", build(make_cfg(skipcrossduplicates=True)))

    def test_no_network_release_check(self):
        self.assertIn("--noreleasecheck", build())

    def test_extra_args_appended_last(self):
        cfg = make_cfg(extra_args=["--debugimap", "--exclude", "^Archive$"])
        cmd = build(cfg)
        self.assertEqual(cmd[-3:], ["--debugimap", "--exclude", "^Archive$"])

    def test_no_none_or_non_string_tokens(self):
        # subprocess se nem TypeError neu lot mot phan tu khong phai chuoi
        for token in build():
            self.assertIsInstance(token, str)


class TestRedact(unittest.TestCase):
    def test_passfile_paths_hidden_in_log(self):
        cmd = ["imapsync", "--passfile1", "/s/src.pass", "--user1", "an@cu.com"]
        self.assertEqual(
            _redact(cmd),
            ["imapsync", "--passfile1", "<passfile>", "--user1", "an@cu.com"],
        )


class TestWriteSecret(unittest.TestCase):
    def test_writes_content_and_restricts_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "src.pass"
            _write_secret(p, "hunter2")
            self.assertEqual(p.read_text(encoding="utf-8"), "hunter2")
            if os.name == "posix":
                self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "src.pass"
            _write_secret(p, "old")
            _write_secret(p, "new")
            self.assertEqual(p.read_text(encoding="utf-8"), "new")


IMAPSYNC_TAIL = """
Folders synced                    : 12/12 synced
++++ Statistics ++++
Transfer started on               : Tue Aug 25 10:15:00 2026
Transfer ended on                 : Tue Aug 25 10:22:31 2026
Transfer time                     : 451.3 sec
Messages transferred              : 12453
Messages skipped                  : 87
Messages found duplicate on host1 : 3
Total bytes transferred           : 2684354560
Total bytes skipped               : 10240
Biggest message                   : 26214400 bytes
Detected 0 errors
Exiting with return value 0 (EX_OK: successful termination, 0 error)
"""

IMAPSYNC_AUTH_FAIL = """
Host1 failure: Error login on [imap.gmail.com] with user [an@cu.com]:
AUTHENTICATIONFAILED Invalid credentials (Failure)
Detected 1 errors
Exiting with return value 16 (EXIT_AUTHENTICATION_FAILURE: error after authentication)
"""


class TestParseOutput(unittest.TestCase):
    def test_reads_statistics_block(self):
        out = parse_output(IMAPSYNC_TAIL)
        self.assertEqual(out["stats"]["messages_transferred"], 12453)
        self.assertEqual(out["stats"]["messages_skipped"], 87)
        self.assertEqual(out["stats"]["bytes_transferred"], 2684354560)
        self.assertEqual(out["stats"]["biggest_message"], 26214400)
        self.assertEqual(out["stats"]["errors"], 0)
        self.assertEqual(out["transfer_time"], 451.3)
        self.assertEqual(out["folders_synced"], "12/12")

    def test_takes_exit_label_from_imapsync_itself(self):
        """Khong tu doan y nghia ma loi -- imapsync da in san ten cua no."""
        out = parse_output(IMAPSYNC_AUTH_FAIL)
        self.assertIn("EXIT_AUTHENTICATION_FAILURE", out["exit_label"])
        self.assertEqual(out["stats"]["errors"], 1)

    def test_uses_last_exit_line_when_several(self):
        text = ("Exiting with return value 0 (EX_OK: ok)\n"
                "Exiting with return value 16 (EXIT_AUTHENTICATION_FAILURE: x)\n")
        self.assertIn("AUTHENTICATION", parse_output(text)["exit_label"])

    def test_empty_output_is_safe(self):
        out = parse_output("")
        self.assertEqual(out["stats"], {})
        self.assertNotIn("exit_label", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# Trich tu ma nguon imapsync that (bang GetOptions). Cac tuy chon nay la co
# that, du mot so KHONG duoc ghi trong --help -- do chinh la ly do phai doc
# bang GetOptions thay vi doc help.
GETOPTIONS_SNIPPET = """
        'host1|h1=s'          => \$mysync->{ host1 },
        'port1=i'             => \$mysync->{ port1 },
        'ssl1!'               => \$mysync->{ ssl1 },
        'tls1!'               => \$mysync->{ tls1 },
        'exclude=s@'          => \$mysync->{ exclude },
        'regexflag=s@'        => \$mysync->{ regexflag },
        'filterflags!'        => \$mysync->{ filterflags },
        'foldersizes!'        => \$mysync->{ foldersizes },
        'releasecheck!'       => \$mysync->{ releasecheck },
        'log!'                => \$mysync->{ log },
        'syncinternaldates!'  => \$mysync->{ syncinternaldates },
        'idatefromheader!'    => \$mysync->{ idatefromheader },
        'dry!'                => \$mysync->{ dry },
        'tmpdir=s'            => \$mysync->{ tmpdir },
"""


class TestDeclaredOptions(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "imapsync"
            p.write_text(text, encoding="utf-8")
            from migrate_mail.runner import declared_options
            return declared_options(str(p))

    def test_reads_plain_options(self):
        opts = self.parse(GETOPTIONS_SNIPPET)
        for name in ("host1", "port1", "exclude", "tmpdir", "filterflags"):
            self.assertIn(name, opts)

    def test_reads_aliases(self):
        self.assertIn("h1", self.parse(GETOPTIONS_SNIPPET))

    def test_negatable_options_get_a_no_form(self):
        """Getopt::Long: hau to '!' tu sinh dang --noXXX du khong khai bao."""
        opts = self.parse(GETOPTIONS_SNIPPET)
        for name in ("nofoldersizes", "noreleasecheck", "nolog", "notls1", "nossl1"):
            self.assertIn(name, opts)

    def test_value_options_do_not_get_a_no_form(self):
        opts = self.parse(GETOPTIONS_SNIPPET)
        self.assertNotIn("noexclude", opts)
        self.assertNotIn("notmpdir", opts)

    def test_unknown_names_are_absent(self):
        opts = self.parse(GETOPTIONS_SNIPPET)
        self.assertNotIn("khongcothat", opts)
        self.assertNotIn("filterflagsX", opts)

    def test_unreadable_file_gives_empty_set(self):
        from migrate_mail.runner import declared_options
        self.assertEqual(declared_options("/khong/ton/tai/imapsync"), set())


class TestUnsupportedFlags(unittest.TestCase):
    """Bug that: --filterflags co trong GetOptions nhung KHONG co trong --help.

    Kiem tra dua vao --help se bao dong gia va lam nguoi dung tuong tool hong.
    """

    def check(self, script_text, flags):
        import migrate_mail.runner as R
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "imapsync"
            p.write_text(script_text, encoding="utf-8")
            cfg = make_cfg()
            cfg.paths.imapsync = str(p)
            return R.unsupported_flags(cfg, flags)

    def test_undocumented_but_real_option_is_not_flagged(self):
        # Nhan ban snippet cho du >50 option de kich hoat nhanh doc GetOptions
        big = GETOPTIONS_SNIPPET + "".join(
            "        'opt%d!' => \$m->{ x },\n" % i for i in range(60))
        self.assertEqual(self.check(big, ["--filterflags"]), [])

    def test_genuinely_unknown_option_is_flagged(self):
        big = GETOPTIONS_SNIPPET + "".join(
            "        'opt%d!' => \$m->{ x },\n" % i for i in range(60))
        self.assertEqual(self.check(big, ["--khongcothat"]), ["--khongcothat"])

    def test_negated_form_of_real_option_is_accepted(self):
        big = GETOPTIONS_SNIPPET + "".join(
            "        'opt%d!' => \$m->{ x },\n" % i for i in range(60))
        self.assertEqual(self.check(big, ["--nofoldersizes", "--nolog"]), [])


class TestFoldersOnlyMode(unittest.TestCase):
    """--folders-only tao that cay folder, khong dong bo mail.

    Khong duoc kem --dry: imapsync khong mo phong duoc folder chua ton tai ben
    dich, nen phai tao that thi lan chay khan sau moi ra so lieu day du.
    """

    def build_folders(self):
        from migrate_mail.runner import MODE_FOLDERS
        return build(mode=MODE_FOLDERS)

    def test_uses_justfolders(self):
        self.assertIn("--justfolders", self.build_folders())

    def test_is_not_a_dry_run(self):
        self.assertNotIn("--dry", self.build_folders())

    def test_dry_mode_has_no_justfolders(self):
        cmd = build(mode=MODE_DRY)
        self.assertIn("--dry", cmd)
        self.assertNotIn("--justfolders", cmd)

    def test_sync_mode_has_neither(self):
        cmd = build(mode=MODE_SYNC)
        self.assertNotIn("--dry", cmd)
        self.assertNotIn("--justfolders", cmd)

    def test_folder_mapping_still_applied(self):
        # Tao folder ma khong ap mapping thi se tao nham ten [Gmail]/...
        maps = [v for k, v in pairs(self.build_folders()) if k == "--f1f2"]
        self.assertIn("[Gmail]/Sent Mail=Sent", maps)


SIZES_OUTPUT = """
Host1 Nb folders:                    11 folders
Host2 Nb folders:                    10 folders

Host1 Nb messages:                49720 messages
Host2 Nb messages:                    0 messages

Host1 Total size:            5368709120 bytes (5.000 GiB)
Host2 Total size:                     0 bytes (0.000 KiB)

Host1 Biggest message:         26214400 bytes (25.000 MiB)
Exiting with return value 0 (EX_OK: successful termination)
"""


class TestSizesMode(unittest.TestCase):
    def build_sizes(self):
        from migrate_mail.runner import MODE_SIZES
        return build(mode=MODE_SIZES)

    def test_asks_imapsync_for_folder_sizes(self):
        self.assertIn("--justfoldersizes", self.build_sizes())

    def test_does_not_suppress_folder_sizes(self):
        """--nofoldersizes se vo hieu hoa chinh thu ta dang muon do."""
        self.assertNotIn("--nofoldersizes", self.build_sizes())

    def test_other_modes_still_suppress_folder_sizes(self):
        for mode in (MODE_SYNC, MODE_DRY):
            self.assertIn("--nofoldersizes", build(mode=mode))

    def test_is_not_a_dry_run(self):
        # --justfoldersizes tu thoat sau khi dem, khong can --dry
        self.assertNotIn("--dry", self.build_sizes())

    def test_parses_source_totals(self):
        stats = parse_output(SIZES_OUTPUT)["stats"]
        self.assertEqual(stats["source_messages"], 49720)
        self.assertEqual(stats["source_bytes"], 5368709120)
        self.assertEqual(stats["source_biggest"], 26214400)
        self.assertEqual(stats["source_folders"], 11)

    def test_does_not_confuse_host2_numbers_with_host1(self):
        stats = parse_output(SIZES_OUTPUT)["stats"]
        self.assertNotEqual(stats["source_bytes"], 0)


class TestDaysNeeded(unittest.TestCase):
    """Gioi han Gmail 2500 MB/ngay/account quyet dinh lich chay."""

    def days(self, n):
        from migrate_mail.cli import _days_needed
        return _days_needed(n)

    def test_empty_mailbox(self):
        self.assertEqual(self.days(0), 0)

    def test_exactly_at_the_limit_is_one_day(self):
        from migrate_mail.runner import GMAIL_DAILY_LIMIT
        self.assertEqual(self.days(GMAIL_DAILY_LIMIT), 1)

    def test_one_byte_over_needs_two_days(self):
        from migrate_mail.runner import GMAIL_DAILY_LIMIT
        self.assertEqual(self.days(GMAIL_DAILY_LIMIT + 1), 2)

    def test_five_gigabytes(self):
        self.assertEqual(self.days(5 * 1024 ** 3), 3)

    def test_rounds_up_never_down(self):
        from migrate_mail.runner import GMAIL_DAILY_LIMIT
        for n in (1, 100, GMAIL_DAILY_LIMIT - 1):
            self.assertEqual(self.days(n), 1)
