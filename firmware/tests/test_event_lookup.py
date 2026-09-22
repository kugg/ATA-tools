#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Offline tests for the evidence-backed ATA packed log-event atlas."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from firmware import event_lookup


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"


class EventLookupTest(unittest.TestCase):
    def test_checked_in_atlas_is_complete(self):
        atlas = event_lookup.load_atlas()
        entries = atlas["entries"]
        self.assertEqual(len(entries), 108)
        self.assertEqual(len({entry["call"] for entry in entries}), 108)
        self.assertEqual(atlas["direct_calls"], 108)
        exact = [entry for entry in entries
                 if entry["confidence"] == "exact-message"]
        self.assertEqual(len(exact), 108)
        self.assertTrue(all(entry["message"] for entry in exact))
        self.assertTrue(all(entry["args"] for entry in entries))

    def test_search_by_message_owner_and_address(self):
        entries = event_lookup.load_atlas()["entries"]
        self.assertEqual(
            [entry["call"] for entry in event_lookup.search(entries, "kup(")],
            ["0x1f834"])
        self.assertEqual(
            [entry["call"] for entry in event_lookup.search(entries, "0x44ac4")],
            ["0x44c8c", "0x44d14"])
        self.assertEqual(
            [entry["subsystem"] for entry in
             event_lookup.search(entries, "RTP Rx Init")],
            ["rtp-media"])

    def test_classless_path_is_recorded(self):
        atlas = event_lookup.load_atlas()
        self.assertIn("no class/mode arguments", atlas["class_note"])
        for entry in atlas["entries"]:
            if entry["call"] == "0x1cc58":
                self.assertEqual(entry["class_source"],
                                 "inherited-from-maybe_syslog_emit_class")
            else:
                self.assertEqual(entry["class_source"], "none")

    def test_cli_output_is_stable(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = event_lookup.main(["Close RTPRX"])
        self.assertEqual(result, 0)
        self.assertIn("Event call:   0x4bcb4", output.getvalue())

    def test_argument_strings_are_escaped_for_terminal_output(self):
        entry = event_lookup.load_atlas()["entries"][0]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            event_lookup._print_entry(entry)
        self.assertIn(r"e: need ver > 3.0!\n", output.getvalue())
        self.assertNotIn("e: need ver > 3.0!\n\n", output.getvalue())

    def test_control_character_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "query is invalid"):
            event_lookup.search(event_lookup.load_atlas()["entries"],
                                "forged\nline")

    def test_atlas_reader_rejects_symlink_and_duplicate_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "atlas.json")
            link = os.path.join(directory, "atlas-link.json")
            with open(event_lookup.DEFAULT_ATLAS, "rb") as source, \
                    open(target, "wb") as output:
                output.write(source.read())
            os.symlink(target, link)
            with self.assertRaisesRegex(ValueError, "regular file"):
                event_lookup.load_atlas(link)

            with open(target, "r", encoding="utf-8") as source:
                atlas = json.load(source)
            atlas["entries"][1]["call"] = atlas["entries"][0]["call"]
            duplicate = os.path.join(directory, "duplicate.json")
            with open(duplicate, "w", encoding="utf-8") as output:
                json.dump(atlas, output)
            with self.assertRaisesRegex(ValueError, "duplicate call"):
                event_lookup.load_atlas(duplicate)

    def test_atlas_reader_rejects_control_characters_in_output_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(event_lookup.DEFAULT_ATLAS, "r", encoding="utf-8") as source:
                atlas = json.load(source)
            cases = (
                ("class-source", lambda entry: entry.__setitem__(
                    "class_source", "none\nforged")),
                ("argument-kind", lambda entry: entry["args"][0].__setitem__(
                    "kind", "constant\nforged")),
                ("argument-value", lambda entry: entry["args"][0].__setitem__(
                    "value", "0x1\nforged")),
                ("argument-string", lambda entry: entry["args"][0].__setitem__(
                    "string", "safe\x1b[31m")),
                ("argument-c1", lambda entry: entry["args"][0].__setitem__(
                    "string", "safe\u009b31m")),
                ("argument-format", lambda entry: entry["args"][0].__setitem__(
                    "string", "safe\u202eforged")),
            )
            for name, mutate in cases:
                with self.subTest(name=name):
                    changed = json.loads(json.dumps(atlas))
                    mutate(changed["entries"][0])
                    path = os.path.join(directory, f"{name}.json")
                    with open(path, "w", encoding="utf-8") as output:
                        json.dump(changed, output)
                    with self.assertRaisesRegex(ValueError, "invalid|control"):
                        event_lookup.load_atlas(path)

    def test_atlas_reader_rejects_incomplete_output_relationships(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(event_lookup.DEFAULT_ATLAS, "r", encoding="utf-8") as source:
                atlas = json.load(source)
            cases = (
                ("missing-offset", lambda entry: entry["args"][0].update(
                    {"base": "r2"})),
                ("missing-conditional-args", lambda entry: (
                    entry.__setitem__("args_dominance", "may-be-conditional"),
                    entry.pop("conditional_args", None))),
            )
            for name, mutate in cases:
                with self.subTest(name=name):
                    changed = json.loads(json.dumps(atlas))
                    mutate(changed["entries"][0])
                    path = os.path.join(directory, f"{name}.json")
                    with open(path, "w", encoding="utf-8") as output:
                        json.dump(changed, output)
                    with self.assertRaisesRegex(ValueError, "invalid|missing"):
                        event_lookup.load_atlas(path)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_pinned_package_matches_all_calls_arguments_and_messages(self):
        atlas = event_lookup.load_atlas()
        event_lookup.verify_package(atlas, str(ATA_ZUP))


if __name__ == "__main__":
    unittest.main()
