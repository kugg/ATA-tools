"""Unit tests for the OpenWrt feed cache tool (offline resolution)."""
import contextlib
import gzip
import io
import os
import tempfile
import unittest
from unittest import mock

from telephony import openwrt_feed_cache as feed


def _index(entries):
    lines = []
    for name, (version, filename, depends) in entries.items():
        lines.append("Package: %s" % name)
        lines.append("Version: %s" % version)
        lines.append("Filename: %s" % filename)
        if depends:
            lines.append("Depends: %s" % depends)
        lines.append("")
    return "\n".join(lines)


BASE_INDEX = _index({
    "zlib": ("1.3.1-r1", "zlib_1.3.1-r1_x86_64.ipk", ""),
    "terminfo": ("6.4-r2", "terminfo_6.4-r2_x86_64.ipk", "libncurses6"),
    "libncurses6": ("6.4-r2", "libncurses6_6.4-r2_x86_64.ipk", ""),
    "python3": ("3.11.14-r1", "python3_3.11.14-r1_x86_64.ipk",
                "python3-light, libpthread"),
})

PACKAGES_INDEX = _index({
    "libpj": ("2.13.3-r1", "libpj_2.13.3-r1_x86_64.ipk", "libopenssl3"),
    "libopenssl3": ("3.0.14-r1", "libopenssl3_3.0.14-r1_x86_64.ipk", ""),
})

TELEPHONY_INDEX = _index({
    "asterisk": ("20.8.1-r1", "asterisk_20.8.1-r1_x86_64.ipk",
                 "libpj, libstdcpp6"),
    "asterisk-chan-sip": ("20.8.1-r1",
                          "asterisk-chan-sip_20.8.1-r1_x86_64.ipk", "asterisk"),
})

TARGET_INDEX = _index({
    "libstdcpp6": ("13.3.0-r4", "libstdcpp6_13.3.0-r4_x86_64.ipk", "libgcc"),
})


def _dry(argv):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = feed.main(argv + ["--cache", tempfile.mkdtemp()])
    return rc, stdout.getvalue()


class ParseIndexTests(unittest.TestCase):

    def test_parses_fields(self):
        entries = feed.parse_index(_index({
            "a": ("1", "a_1_x86_64.ipk", "b"),
            "b": ("2", "b_2_x86_64.ipk", ""),
        }))
        self.assertEqual(entries["a"]["Version"], "1")
        self.assertEqual(entries["a"]["Depends"], "b")
        self.assertEqual(entries["b"]["Filename"], "b_2_x86_64.ipk")

    def test_drops_entries_without_filename(self):
        self.assertEqual(
            feed.parse_index("Package: x\nVersion: 1\n\n"), {})


class FeedUrlTests(unittest.TestCase):

    def test_target_feed_arch_slash(self):
        self.assertEqual(
            feed.TARGET_FEED_TEMPLATE.format(release="24.10.8",
                                             arch="x86/64"),
            "https://downloads.openwrt.org/releases/24.10.8/"
            "targets/x86/64/packages")


class ResolveTests(unittest.TestCase):

    def test_resolves_closure_across_feeds(self):
        fetch = mock.patch.object(feed, "_fetch",
                                  side_effect=[
                                      gzip.compress(s.encode())
                                      for s in (BASE_INDEX, PACKAGES_INDEX,
                                                TELEPHONY_INDEX, TARGET_INDEX)])
        with fetch:
            rc, out = _dry(["--package", "asterisk",
                            "--package", "asterisk-chan-sip",
                            "--package", "python3"])
        self.assertEqual(rc, 0)
        for expected in ("asterisk", "asterisk-chan-sip", "python3",
                         "libpj", "libopenssl3", "libstdcpp6"):
            self.assertIn(expected, out)
        self.assertIn("libstdcpp6                   target", out)

    def test_base_image_provided_not_resolved(self):
        fetch = mock.patch.object(feed, "_fetch",
                                  side_effect=[
                                      gzip.compress(s.encode())
                                      for s in (BASE_INDEX, PACKAGES_INDEX,
                                                TELEPHONY_INDEX, TARGET_INDEX)])
        with fetch:
            rc, out = _dry(["--package", "python3"])
        self.assertEqual(rc, 0)
        self.assertNotIn(" libc", out)
        self.assertNotIn(" libgcc", out)

    def test_missing_package_reported(self):
        fetch = mock.patch.object(feed, "_fetch",
                                  side_effect=[
                                      gzip.compress(s.encode())
                                      for s in (BASE_INDEX, PACKAGES_INDEX,
                                                TELEPHONY_INDEX, TARGET_INDEX)])
        with fetch:
            rc, out = _dry(["--package", "no-such-pkg"])


if __name__ == "__main__":
    unittest.main()