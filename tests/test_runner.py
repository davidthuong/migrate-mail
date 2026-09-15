# -*- coding: utf-8 -*-
"""Test dung lenh imapsync va doc output cua no."""

import os
import shutil
import signal
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from postboat import providers, runner
from postboat.config import (MASTER_AUTHZID, MASTER_SEPARATOR, Config,
                                 MasterConf, Paths, ServerConf, SyncConf)
from postboat.discover import _parse_list_line, build_plan
from postboat.providers import AUTH_MASTER
from postboat.runner import (MODE_DRY, MODE_SYNC, build_command, flags_used,
                                 logins_for, parse_output, _redact, _write_secret)
from postboat.users import User

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


def master_server(host="mail.cu.vn", style=MASTER_AUTHZID, sep="*") -> ServerConf:
    return ServerConf(
        host, 993, True, provider=providers.DOVECOT, auth=AUTH_MASTER,
        master=MasterConf(user="migrate", password="BiMat", style=style,
                          separator=sep),
    )


class TestMasterAuthCommand(unittest.TestCase):
    """auth = master: mot tai khoan quan tri mo hop thu cua tung nguoi."""

    def test_authzid_keeps_user1_as_the_mailbox(self):
        cfg = make_cfg()
        cfg.source = master_server()
        p = pairs(build(cfg))
        # --user1 van la hop thu can mo; tai khoan dang nhap di rieng.
        self.assertIn(("--user1", "an@cu.com"), p)
        self.assertIn(("--authuser1", "migrate"), p)

    def test_authzid_forces_plain(self):
        """Co che LOGIN khong mang duoc hai danh tinh, va imapsync mac dinh
        chon co che 'manh nhat' server quang ba -- gap CRAM-MD5 la no bo roi
        authuser ma khong bao gi."""
        self.assertIn(("--authmech1", "PLAIN"), pairs(build(self._cfg())))

    def test_separator_style_sends_one_glued_name_and_no_authuser(self):
        cfg = make_cfg()
        cfg.source = master_server(style=MASTER_SEPARATOR)
        cmd = build(cfg)
        self.assertIn(("--user1", "an@cu.com*migrate"), pairs(cmd))
        self.assertNotIn("--authuser1", cmd)
        self.assertNotIn("--authmech1", cmd)

    def test_master_password_never_reaches_the_command_line(self):
        cmd = build(self._cfg())
        self.assertNotIn("BiMat", cmd)
        self.assertIn("--passfile1", cmd)

    def test_passfile_gets_the_admin_password_not_the_mailbox_one(self):
        """Cho de sai nhat cua tinh nang nay: ghi mat khau cua hop thu vao
        passfile trong khi dong lenh lai dang nhap bang tai khoan quan tri."""
        cfg = self._cfg()
        login1, _login2 = logins_for(cfg, USER)
        self.assertEqual(login1.password, "BiMat")
        self.assertNotEqual(login1.password, USER.src_password)

    def test_destination_side_works_the_same_way(self):
        cfg = make_cfg()
        cfg.dest = master_server(host="moi.vn")
        p = pairs(build(cfg))
        self.assertIn(("--user2", "an@moi.vn"), p)
        self.assertIn(("--authuser2", "migrate"), p)
        self.assertIn(("--authmech2", "PLAIN"), p)
        # Dau nguon khong dung master thi khong duoc dinh flag nao.
        self.assertNotIn("--authuser1", build(cfg))

    def test_doctor_checks_the_flags_only_when_they_are_used(self):
        plain = make_cfg()
        self.assertNotIn("--authuser1", flags_used(plain))
        self.assertIn("--authuser1", flags_used(self._cfg()))
        # Kieu separator ghep ten ngay trong --user1, khong can flag nao them.
        sep = make_cfg()
        sep.source = master_server(style=MASTER_SEPARATOR)
        self.assertNotIn("--authuser1", flags_used(sep))

    def _cfg(self) -> Config:
        cfg = make_cfg()
        cfg.source = master_server()
        return cfg


class TestTlsArgs(unittest.TestCase):
    """imapsync cung khong kiem chung chi neu khong duoc bao.

    Mac dinh cua no la SSL_verify_mode=0, va no in han ra dong do trong log.
    Nen ca hai nua cua tool deu phai duoc noi ro, khong dua vao mac dinh nao.
    """

    def cfg(self, verify=True, ssl=True):
        cfg = make_cfg()
        cfg.source = ServerConf("imap.gmail.com", 993 if ssl else 143, ssl,
                                tls_verify=verify)
        return cfg

    def test_verification_asked_for_by_default(self):
        self.assertIn(("--sslargs1", "SSL_verify_mode=1"), pairs(build(self.cfg())))

    def test_turned_off_is_written_out_not_left_to_the_default(self):
        """Doc lai log mot lan chay cu phai biet duoc no CO kiem hay khong."""
        self.assertIn(("--sslargs1", "SSL_verify_mode=0"),
                      pairs(build(self.cfg(verify=False))))

    def test_name_check_scheme_is_pinned_not_inherited(self):
        """Kiem chuoi chung chi va kiem ten host la hai viec khac nhau.

        Khong dat scheme thi IO::Socket::SSL van kiem ten, nhung bang scheme
        'default' -- rong hon: ky tu dai dien o moi vi tri, IP duoc nam trong
        CN. 'imap' la scheme dung cho giao thuc nay. imapsync hom nay cung dat
        dung no cho duong --ssl, nhung day phai la lua chon cua tool.
        """
        self.assertIn(("--sslargs1", "SSL_verifycn_scheme=imap"),
                      pairs(build(self.cfg())))

    def test_no_name_check_claimed_when_verification_is_off(self):
        """Tat doi chieu ma log van ghi scheme thi nguoi doc lai tuong con kiem."""
        p = pairs(build(self.cfg(verify=False)))
        self.assertNotIn(("--sslargs1", "SSL_verifycn_scheme=imap"), p)

    def test_no_tls_args_on_a_plain_connection(self):
        cmd = build(self.cfg(ssl=False))
        self.assertNotIn("--sslargs1", cmd)
        self.assertIn("--notls1", cmd)

    def test_each_side_decides_for_itself(self):
        cfg = make_cfg()
        cfg.source = ServerConf("imap.gmail.com", 993, True, tls_verify=False)
        cfg.dest = ServerConf("mail.moi.vn", 993, True, tls_verify=True)
        p = pairs(build(cfg))
        self.assertIn(("--sslargs1", "SSL_verify_mode=0"), p)
        self.assertIn(("--sslargs2", "SSL_verify_mode=1"), p)

    def test_doctor_checks_the_flag_only_when_ssl_is_used(self):
        self.assertIn("--sslargs1", flags_used(self.cfg()))
        self.assertNotIn("--sslargs1", flags_used(self.cfg(ssl=False)))


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
            from postboat.runner import declared_options
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
        from postboat.runner import declared_options
        self.assertEqual(declared_options("/khong/ton/tai/imapsync"), set())


class TestUnsupportedFlags(unittest.TestCase):
    """Bug that: --filterflags co trong GetOptions nhung KHONG co trong --help.

    Kiem tra dua vao --help se bao dong gia va lam nguoi dung tuong tool hong.
    """

    def check(self, script_text, flags):
        import postboat.runner as R
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
        from postboat.runner import MODE_FOLDERS
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
        from postboat.runner import MODE_SIZES
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

    LIMIT = providers.GMAIL.daily_limit

    def days(self, n, limit=None):
        from postboat.cli import _days_needed
        return _days_needed(n, self.LIMIT if limit is None else limit)

    def test_empty_mailbox(self):
        self.assertEqual(self.days(0), 0)

    def test_exactly_at_the_limit_is_one_day(self):
        self.assertEqual(self.days(self.LIMIT), 1)

    def test_one_byte_over_needs_two_days(self):
        self.assertEqual(self.days(self.LIMIT + 1), 2)

    def test_five_gigabytes(self):
        self.assertEqual(self.days(5 * 1024 ** 3), 3)

    def test_rounds_up_never_down(self):
        for n in (1, 100, self.LIMIT - 1):
            self.assertEqual(self.days(n), 1)

    def test_provider_without_published_limit_reports_nothing(self):
        """Chi Gmail cong bo han muc/ngay. Voi nguon khac, cot 'Ngay toi da'
        khong co nghia gi va phai bien mat chu khong duoc doan bua."""
        self.assertEqual(providers.M365.daily_limit, 0)
        self.assertEqual(self.days(50 * 1024 ** 3, providers.M365.daily_limit), 0)


class TestStopAll(unittest.TestCase):
    """runner.stop_all() phai voi toi duoc imapsync dang chay.

    Ly do co ham nay: MOT SIGINT khong dung duoc imapsync. Ngoai Docker no gan
    INT cho catch_reconnect -- noi lai hai dau roi chep tiep (do that tren rig:
    "Got a signal INT ... reconnected to both imap servers"). TERM thi moi vao
    catch_exit. Nen Ctrl-C o tool phai tu ha TERM xuong, khong ngoi cho.
    """

    def setUp(self):
        runner._LIVE_PROCS.clear()
        self.addCleanup(runner._LIVE_PROCS.clear)

    class FakeProc:
        def __init__(self, alive=True):
            self.alive = alive
            self.signals = []

        def poll(self):
            return None if self.alive else 0

        def send_signal(self, sig):
            self.signals.append(sig)

    def test_khong_co_gi_chay_thi_tra_ve_0(self):
        self.assertEqual(0, runner.stop_all())

    def test_bao_cho_moi_tien_trinh_con_song(self):
        a, b = self.FakeProc(), self.FakeProc()
        runner._LIVE_PROCS.update({a, b})
        self.assertEqual(2, runner.stop_all(signal.SIGTERM))
        self.assertEqual([signal.SIGTERM], a.signals)
        self.assertEqual([signal.SIGTERM], b.signals)

    def test_bo_qua_tien_trinh_da_chet(self):
        dead, alive = self.FakeProc(alive=False), self.FakeProc()
        runner._LIVE_PROCS.update({dead, alive})
        self.assertEqual(1, runner.stop_all())
        self.assertEqual([], dead.signals)

    def test_tien_trinh_nem_loi_khong_lam_hong_ca_lo(self):
        """Chay tu trong signal handler: nem ra la mat luon duong dung."""
        class Angry(self.FakeProc):
            def send_signal(self, sig):
                raise OSError("da bien mat")

        angry, ok = Angry(), self.FakeProc()
        runner._LIVE_PROCS.update({angry, ok})
        runner.stop_all()
        self.assertEqual([signal.SIGTERM], ok.signals)

    def test_so_dang_ky_rong_sau_khi_chay_xong(self):
        """run_user phai go tien trinh ra khoi so khi chay xong.

        Neu quen go, lan Ctrl-C sau se gui tin hieu vao mot PID da chet -- ma
        PID thi duoc cap lai, nen co ngay ban nham tien trinh khac.
        """
        tmp = Path(tempfile.mkdtemp(prefix="pbtest-stopall-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        fake = Path(__file__).resolve().parent / "fake_imapsync.py"
        cfg = make_cfg()
        cfg.paths.imapsync = "%s %s" % (sys.executable, fake)
        cfg.paths.logdir = tmp / "logs"
        cfg.paths.statedir = tmp / "state"
        cfg.paths.logdir.mkdir(parents=True, exist_ok=True)

        plan = build_plan(parse(GMAIL_EN), cfg.sync)
        result = runner.run_user(cfg, USER, plan, MODE_SYNC)

        self.assertEqual(set(), runner._LIVE_PROCS)
        self.assertEqual(0, result.exit_code)


class TestDeltaWindowUsesArrivalDate(unittest.TestCase):
    """--since-days phai do bang dung cai moc ngay tool dang giu.

    imapsync mac dinh chon mail cho --maxage bang SEARCH SENTSINCE, tuc header
    Date:. Nhung mac dinh cua tool la giu INTERNALDATE. Do tren rig: 3 mail
    cung vua ve nguon, `--since-days 2` chi chuyen 1 -- hai cai kia mang Date:
    cu va Date: rong nen bi bo lai, con tong ket van bao "1/1 mailbox OK".
    """

    def test_since_days_do_theo_ngay_mail_ve(self):
        cmd = build(since_days=7)
        self.assertIn(("--maxage", "7"), pairs(cmd))
        self.assertIn("--noabletosearch", cmd)

    def test_dat_cho_ca_hai_dau_chu_khong_rieng_nguon(self):
        """Chi dat cho nguon thi dau dich van loc bang Date: -- no khong thay
        mail da co san nen chep lai, thanh nhan ban."""
        cmd = build(since_days=7)
        self.assertNotIn("--noabletosearch1", cmd)
        self.assertNotIn("--noabletosearch2", cmd)

    def test_khong_co_since_days_thi_khong_dat(self):
        """Chay day du thi khong loc theo tuoi, dat co nay chi lam cham."""
        self.assertNotIn("--noabletosearch", build())

    def test_date_source_header_thi_de_imapsync_search_theo_date(self):
        """date_source = header nghia la ta CO Y lay Date: lam moc, va luc do
        ca hai dau deu mang Date: do -- search theo Date: la dung."""
        cmd = build(make_cfg(date_source="header"), since_days=7)
        self.assertIn(("--maxage", "7"), pairs(cmd))
        self.assertNotIn("--noabletosearch", cmd)
        self.assertIn("--idatefromheader", cmd)

    def test_doctor_kiem_ca_co_nay(self):
        """imapsync qua cu khong biet --noabletosearch se dung ngay khi gap
        tuy chon la, nen doctor phai bat truoc."""
        self.assertIn("--noabletosearch", flags_used(make_cfg()))


COPIED_LOG = """Host1: folder [INBOX] has 3 messages in total (mentioned by SELECT)
msg INBOX/1 {576}    copied to INBOX/1     132.04 msgs/s  73.020 KiB/s 108.942 KiB copied 
msg INBOX/2 {539}    copied to INBOX/2     132.08 msgs/s  73.022 KiB/s 109.469 KiB copied 
msg INBOX/3 {571}    copied to INBOX/3     132.11 msgs/s  73.043 KiB/s 2.500 MiB copied 
sleeping 2.00 s
"""


class TestPartialStatsWhenImapsyncDies(unittest.TestCase):
    """imapsync chet giua chung thi khoi thong ke o cuoi khong bao gio duoc in.

    Do tren rig: giet server nguon bang `docker stop` luc dang chep, dau dich
    dem duoc 205 mail, con bao cao ghi "0 mail, 0 B". Bao cao la thu nguoi ta
    giu lai, nen no noi "chua co gi sang ca" la kieu sai te nhat.
    """

    def test_dem_lai_tu_cac_dong_da_in(self):
        out = parse_output(COPIED_LOG)
        self.assertEqual(out["stats"]["messages_transferred"], 3)
        self.assertTrue(out.get("partial"))

    def test_lay_tong_dung_luong_cong_don_cuoi_cung(self):
        out = parse_output(COPIED_LOG)
        self.assertEqual(out["stats"]["bytes_transferred"], int(2.5 * 1024 ** 2))

    def test_khoi_thong_ke_that_van_duoc_uu_tien(self):
        """Chay xong binh thuong thi lay so cua imapsync, khong tu dem."""
        text = COPIED_LOG + "\nMessages transferred: 999\nTotal bytes transferred: 12345\n"
        out = parse_output(text)
        self.assertEqual(out["stats"]["messages_transferred"], 999)
        self.assertEqual(out["stats"]["bytes_transferred"], 12345)
        self.assertNotIn("partial", out)

    def test_khong_co_dong_nao_thi_khong_bia_ra_so(self):
        out = parse_output("Host1: folder [INBOX] has 0 messages\n")
        self.assertEqual(out["stats"], {})
        self.assertNotIn("partial", out)


class TestSignalLabel(unittest.TestCase):
    """'exit code -13' khong noi gi voi ai doc bao cao."""

    def test_sigpipe_co_ten(self):
        label = runner._signal_label(13)
        self.assertIn("SIGPIPE", label)
        self.assertIn("13", label)

    def test_sigkill_co_ten(self):
        self.assertIn("SIGKILL", runner._signal_label(9))

    def test_so_la_hoac_khong_phai_tin_hieu_van_khong_nem(self):
        self.assertIn("99", runner._signal_label(99))
