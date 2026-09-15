"""Offline tests for the bounded Asterisk 20 bench config generator."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from telephony import asterisk_conf  # noqa: E402


class RenderTests(unittest.TestCase):
    def test_render_returns_expected_files(self):
        files = asterisk_conf.render()
        self.assertIn("sip.conf", files)
        self.assertIn("extensions.conf", files)
        self.assertIn("modules.conf", files)
        self.assertIn("rtp.conf", files)
        self.assertIn("ASTERISK.md", files)

    def test_sip_conf_targets_bench_topology(self):
        sip = asterisk_conf.render()["sip.conf"]
        self.assertIn("bindaddr = 192.168.2.2", sip)
        self.assertIn("bindport = 5060", sip)
        self.assertIn("[100]", sip)
        self.assertIn("host = dynamic", sip)
        self.assertIn("permit = 192.168.2.10", sip)
        self.assertIn("allowguest = no", sip)
        self.assertIn("allow = ulaw", sip)

    def test_extension_context_and_prompt(self):
        exten = asterisk_conf.render()["extensions.conf"]
        self.assertIn("[from-ata]", exten)
        self.assertIn("exten => 100,1,Answer()", exten)
        self.assertIn("same => n,Playback(hello-world)", exten)

    def test_modules_explicit_no_autoload(self):
        mods = asterisk_conf.render()["modules.conf"]
        self.assertIn("autoload = no", mods)
        self.assertIn("load => chan_sip.so", mods)
        self.assertIn("load => res_rtp_asterisk.so", mods)

    def test_modules_match_asterisk_20_modules_only(self):
        mods = asterisk_conf.render()["modules.conf"]
        self.assertNotIn("app_answer.so", mods)
        self.assertIn("load => format_wav.so", mods)
        self.assertIn("load => app_playback.so", mods)

    def test_rtp_bounded_range(self):
        rtp = asterisk_conf.render()["rtp.conf"]
        self.assertIn("rtpstart = 20000", rtp)
        self.assertIn("rtpend = 20100", rtp)

    def test_no_secret_values_present(self):
        for content in asterisk_conf.render().values():
            self.assertNotIn("secret = something", content)


class ValidationTests(unittest.TestCase):
    def test_rejects_bad_extension(self):
        with self.assertRaises(asterisk_conf.ConfigError):
            asterisk_conf._fmt_extension("1-100")
        with self.assertRaises(asterisk_conf.ConfigError):
            asterisk_conf._fmt_extension("12345")
        with self.assertRaises(asterisk_conf.ConfigError):
            asterisk_conf._fmt_extension("10 0")

    def test_rejects_non_ip(self):
        with self.assertRaises(asterisk_conf.ConfigError):
            asterisk_conf._fmt_address("192.168.2")
        with self.assertRaises(asterisk_conf.ConfigError):
            asterisk_conf._fmt_address("host")

    def test_rejects_reversed_rtp_range(self):
        with self.assertRaises(asterisk_conf.ConfigError):
            asterisk_conf._fmt_port_range(1200, 1200 - 1)
        with self.assertRaises(asterisk_conf.ConfigError):
            asterisk_conf._fmt_port_range(100, 200)


class WriteTests(unittest.TestCase):
    def test_dry_run_argparse(self):
        argv = ["--address", "192.168.2.2", "--extension", "100"]
        args = asterisk_conf.parse_args(argv)
        self.assertIsNone(args.apply)

    def test_write_creates_private_files(self):
        with tempfile.TemporaryDirectory() as frame:
            target = os.path.join(frame, "gen")
            os.makedirs(target, mode=0o700)
            imported = asterisk_conf.write_tree(target, asterisk_conf.render())
            self.assertEqual(sorted(imported),
                             ["ASTERISK.md", "extensions.conf",
                              "modules.conf", "rtp.conf", "sip.conf"])
            for name in imported:
                full = os.path.join(target, name)
                self.assertTrue(os.path.isfile(full))
                self.assertTrue(os.access(full, os.R_OK))
            self.assertTrue(os.path.isdir(target))

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as target:
            with open(os.path.join(target, "sip.conf"), "w") as handle:
                handle.write("stale\n")
            with self.assertRaises(asterisk_conf.ConfigError):
                asterisk_conf.write_tree(target, asterisk_conf.render())


if __name__ == "__main__":
    unittest.main()