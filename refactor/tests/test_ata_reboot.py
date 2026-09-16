#!/usr/bin/env python3
"""Synthetic offline tests for the bounded reset planner.

No device, socket, or firmware I/O: profile content is synthetic, the
config-view fetch is monkeypatched, and the work directory is a
temporary private directory.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib
import types

ata_reboot = importlib.import_module("refactor.ata_reboot") \
    if False else importlib.import_module("ata_reboot")


PROFILE = b"#txt\nUseTftp:1\nAltGkTimeOut:0\nSyslogCtrl:0x00000000\n"


class RebootPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = tempfile.mkdtemp(prefix="reboot-test-", dir=None)
        os.chmod(self.work, 0o700)
        self.profile = os.path.join(self.work, "profile.txt")
        with open(self.profile, "wb") as fh:
            fh.write(PROFILE)

    def test_toggle_is_exactly_one_line(self) -> None:
        out = ata_reboot.render_toggled_profile(
            PROFILE.decode("latin-1").splitlines(),
            "AltGkTimeOut", "1")
        text = out.decode("latin-1")
        self.assertIn("AltGkTimeOut:1", text)
        self.assertNotIn("AltGkTimeOut:0", text)
        # everything else byte-identical
        self.assertEqual(len(out.splitlines()), len(PROFILE.splitlines()))

    def test_toggle_missing_knob_fails(self) -> None:
        with self.assertRaises(ValueError):
            ata_reboot.render_toggled_profile(
                PROFILE.decode("latin-1").splitlines(), "NoSuchKnob", "1")
        # duplicated knob also refused
        dup = PROFILE + b"AltGkTimeOut:1\n"
        with self.assertRaises(ValueError):
            ata_reboot.render_toggled_profile(
                dup.decode("latin-1").splitlines(), "AltGkTimeOut", "1")

    def test_read_profile_requires_txt_magic(self) -> None:
        bad = os.path.join(self.work, "bad.txt")
        with open(bad, "wb") as fh:
            fh.write(b"NOT#txt\n")
        with self.assertRaises(SystemExit):
            ata_reboot.read_profile_lines(bad)

    def test_collect_records_sha256(self) -> None:
        calls = []

        def fake_get(host, path, seconds):
            calls.append((host, path))
            return b"<dev>ok</dev>"

        with mock.patch.object(ata_reboot, "http_get_text", fake_get):
            rc = ata_reboot.main(["collect", "--work", self.work,
                                  "--profile", self.profile])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [(ata_reboot.DEVICE_HTTP_HOST, "/dev.xml")])
        with open(os.path.join(self.work, "dev.xml"), "rb") as fh:
            self.assertEqual(fh.read(), b"<dev>ok</dev>")
        with open(os.path.join(self.work, "baseline.sha256")) as fh:
            self.assertIn("dev.xml", fh.read())

    def test_verify_passes_on_identical_and_flags_change(self) -> None:
        body = b"<dev>ok</dev>"
        with mock.patch.object(ata_reboot, "http_get_text",
                               editable := lambda h, p, s: None):
            pass
        with mock.patch.object(
                ata_reboot, "http_get_text",
                lambda h, p, s: body):
            self.assertEqual(ata_reboot.main(
                ["collect", "--work", self.work]), 0)
            self.assertEqual(ata_reboot.main(
                ["verify", "--work", self.work]), 0)
        changed = b"<dev>changed</dev>"
        with mock.patch.object(ata_reboot, "http_get_text",
                               lambda h, p, s: changed):
            self.assertEqual(ata_reboot.main(
                ["verify", "--work", self.work]), 1)
        self.assertTrue(os.path.isfile(
            os.path.join(self.work, "dev.xml.changed")))

    def test_serve_dry_run_stays_offline(self) -> None:
        # no --apply: must not execute the tftp tool nor bind sockets
        rc = ata_reboot.main(["serve", "--work", self.work])
        self.assertEqual(rc, 0)

    def test_work_dir_must_be_private(self) -> None:
        os.chmod(self.work, 0o755)
        with self.assertRaises(SystemExit):
            ata_reboot.main(["collect", "--work", self.work])


if __name__ == "__main__":
    unittest.main()
