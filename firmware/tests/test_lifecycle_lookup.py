#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Offline tests for the ATA SIP lifecycle atlas."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from firmware import lifecycle_lookup


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"


class LifecycleLookupTest(unittest.TestCase):
    def test_checked_in_inventory_and_registration_states(self):
        atlas = lifecycle_lookup.load_atlas()
        self.assertEqual(len(atlas["contexts"]), 3)
        self.assertEqual(len(atlas["transitions"]), 28)
        registration = lifecycle_lookup.search(
            atlas["transitions"], "0x16 registered")
        self.assertEqual([entry["id"] for entry in registration],
                         ["registration.success"])
        self.assertEqual(registration[0]["next_state"], "0x16 registered")

    def test_refresh_transfer_media_and_fxs_additions(self):
        atlas = lifecycle_lookup.load_atlas()
        by_id = {entry["id"]: entry for entry in atlas["transitions"]}
        self.assertEqual(by_id["session-refresh.incoming-refresh"]["next_state"],
                         "0x11")
        self.assertEqual(by_id["session-refresh.timeout-disconnect"]["next_state"],
                         "0x5")
        self.assertEqual(by_id["transfer.blind"]["next_state"],
                         "transfer active (+0x924 = 1)")
        self.assertEqual(by_id["media.start-rx"]["machine"], "media")
        self.assertEqual(by_id["failure.retr-failed"]["next_state"], "0x7")
        fxs = by_id["fxs.hook-event"]
        self.assertEqual(fxs["scope"], "packed")
        self.assertEqual(fxs["materialization_register"], 6)
        self.assertIn("session-refresh", lifecycle_lookup.MACHINES)
        self.assertIn("transfer", lifecycle_lookup.MACHINES)
        self.assertIn("media", lifecycle_lookup.MACHINES)

    def test_search_spans_messages_and_contexts(self):
        atlas = lifecycle_lookup.load_atlas()
        self.assertEqual(
            lifecycle_lookup.search(lifecycle_lookup.entries(atlas),
                                    "Min-Expires")[0]["id"],
            "registration.interval-too-brief")
        self.assertEqual(
            lifecycle_lookup.search(lifecycle_lookup.entries(atlas),
                                    "0xbefc")[0]["id"],
            "context.call-leg-table")

    def test_cli_filters_machine(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = lifecycle_lookup.main(
                ["timeout", "--machine", "call-teardown"])
        self.assertEqual(result, 0)
        self.assertIn("call.teardown-timeout", output.getvalue())
        self.assertNotIn("call.answer-ack-timeout", output.getvalue())

    def test_control_character_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "query is invalid"):
            lifecycle_lookup.search([], "forged\ntransition")

    def test_reader_rejects_symlink_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "atlas.json")
            link = os.path.join(directory, "atlas-link.json")
            with open(lifecycle_lookup.DEFAULT_ATLAS, "rb") as source, \
                    open(target, "wb") as output:
                output.write(source.read())
            os.symlink(target, link)
            with self.assertRaisesRegex(ValueError, "regular file"):
                lifecycle_lookup.load_atlas(link)
            with open(target, "r", encoding="utf-8") as source:
                atlas = json.load(source)
            atlas["transitions"][0]["id"] = atlas["contexts"][0]["id"]
            duplicate = os.path.join(directory, "duplicate.json")
            with open(duplicate, "w", encoding="utf-8") as output:
                json.dump(atlas, output)
            with self.assertRaisesRegex(ValueError, "duplicate entry"):
                lifecycle_lookup.load_atlas(duplicate)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_pinned_package_matches_atlas(self):
        atlas = lifecycle_lookup.load_atlas()
        lifecycle_lookup.verify_package(atlas, str(ATA_ZUP))
        altered = copy.deepcopy(atlas)
        altered["transitions"][0]["instruction_checks"][0]["text"] = \
            "addi r0,+0xbb9,r5"
        with self.assertRaisesRegex(ValueError, "instruction check"):
            lifecycle_lookup.verify_package(altered, str(ATA_ZUP))
        packed = copy.deepcopy(atlas)
        fxs = next(entry for entry in packed["transitions"]
                   if entry["id"] == "fxs.hook-event")
        fxs["materialization_register"] = 4
        with self.assertRaisesRegex(ValueError, "materialization"):
            lifecycle_lookup.verify_package(packed, str(ATA_ZUP))


if __name__ == "__main__":
    unittest.main()
