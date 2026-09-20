#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Offline tests for the evidence-backed ATA syslog lookup atlas."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from firmware import syslog_lookup


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"


class SyslogLookupTest(unittest.TestCase):
    def test_checked_in_atlas_is_complete(self):
        atlas = syslog_lookup.load_atlas()
        packed = [entry for entry in atlas["entries"]
                  if entry["scope"] == "packed"]
        self.assertEqual(len(packed), 27)
        self.assertEqual(len({entry["call"] for entry in packed}), 27)
        conditional = [entry for entry in packed if entry["class"] is None]
        self.assertEqual([entry["call"] for entry in conditional], ["0x4da78"])

    def test_search_by_message_owner_and_address(self):
        entries = syslog_lookup.load_atlas()["entries"]
        self.assertEqual(
            [entry["call"] for entry in syslog_lookup.search(entries, "Config Update")],
            ["0x33c4c"])
        self.assertEqual(
            [entry["call"] for entry in syslog_lookup.search(entries, "0x4d924")],
            ["0x4da78", "0x4db44", "0x4dc68"])
        self.assertEqual(
            [entry["scope"] for entry in syslog_lookup.search(entries, "ARP Update")],
            ["resident"])

    def test_cli_output_is_stable(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = syslog_lookup.main(["ATA Config Update OK"])
        self.assertEqual(result, 0)
        self.assertIn("Emitter call: 0x33c4c", output.getvalue())
        self.assertIn("Class/mode:   3 / 0", output.getvalue())

    def test_control_character_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "query is invalid"):
            syslog_lookup.search(syslog_lookup.load_atlas()["entries"],
                                 "forged\nline")

    def test_atlas_reader_rejects_symlink_and_duplicate_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "atlas.json")
            link = os.path.join(directory, "atlas-link.json")
            with open(syslog_lookup.DEFAULT_ATLAS, "rb") as source, \
                    open(target, "wb") as output:
                output.write(source.read())
            os.symlink(target, link)
            with self.assertRaisesRegex(ValueError, "regular file"):
                syslog_lookup.load_atlas(link)

            with open(target, "r", encoding="utf-8") as source:
                atlas = json.load(source)
            atlas["entries"][1]["call"] = atlas["entries"][0]["call"]
            duplicate = os.path.join(directory, "duplicate.json")
            with open(duplicate, "w", encoding="utf-8") as output:
                json.dump(atlas, output)
            with self.assertRaisesRegex(ValueError, "duplicate call"):
                syslog_lookup.load_atlas(duplicate)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_pinned_package_matches_all_calls_and_strings(self):
        atlas = syslog_lookup.load_atlas()
        syslog_lookup.verify_package(atlas, str(ATA_ZUP))


if __name__ == "__main__":
    unittest.main()
