#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Offline tests for the ATA web/TFTP service lookup atlas."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from firmware import service_lookup


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"


class ServiceLookupTest(unittest.TestCase):
    def test_checked_in_inventory_is_complete(self):
        atlas = service_lookup.load_atlas()
        web = atlas["services"]["web"]
        self.assertEqual(sum(entry["kind"] == "route"
                             for entry in web["entries"]), 14)
        self.assertEqual(sum(entry["kind"] == "method"
                             for entry in web["entries"]), 2)
        self.assertEqual(atlas["services"]["tftp"]["role"], "client")
        self.assertFalse(atlas["services"]["tftp"]["server_present"])
        opflags = service_lookup.search(web["entries"], "OpFlags web gates")
        self.assertEqual([entry["id"] for entry in opflags],
                         ["web.state.opflags"])
        self.assertEqual(
            service_lookup.search(atlas["services"]["tftp"]["entries"],
                                  "persisted timer remainder")[0]["id"],
            "tftp.state.remaining")

    def test_web_and_tftp_search(self):
        atlas = service_lookup.load_atlas()
        web = service_lookup.search(atlas["services"]["web"]["entries"],
                                    "/stats")
        self.assertEqual([entry["id"] for entry in web], ["web.route.stats"])
        tftp = service_lookup.search(
            atlas["services"]["tftp"]["entries"], "receive success")
        self.assertEqual([entry["id"] for entry in tftp],
                         ["tftp.receive.success"])

    def test_cli_reports_tftp_role_and_escapes_line_endings(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = service_lookup.main(["tftp", "receive success"])
        self.assertEqual(result, 0)
        self.assertIn("Role:        client", output.getvalue())
        self.assertIn("Server:      absent", output.getvalue())
        self.assertIn(r"\n", output.getvalue())

    def test_control_character_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "query is invalid"):
            service_lookup.search([], "forged\nline")

    def test_reader_rejects_symlink_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "atlas.json")
            link = os.path.join(directory, "atlas-link.json")
            with open(service_lookup.DEFAULT_ATLAS, "rb") as source, \
                    open(target, "wb") as output:
                output.write(source.read())
            os.symlink(target, link)
            with self.assertRaisesRegex(ValueError, "regular file"):
                service_lookup.load_atlas(link)
            with open(target, "r", encoding="utf-8") as source:
                atlas = json.load(source)
            web = atlas["services"]["web"]["entries"]
            web[1]["id"] = web[0]["id"]
            duplicate = os.path.join(directory, "duplicate.json")
            with open(duplicate, "w", encoding="utf-8") as output:
                json.dump(atlas, output)
            with self.assertRaisesRegex(ValueError, "duplicate entry"):
                service_lookup.load_atlas(duplicate)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_pinned_package_matches_atlas(self):
        atlas = service_lookup.load_atlas()
        service_lookup.verify_package(atlas, str(ATA_ZUP))
        altered = copy.deepcopy(atlas)
        state = next(entry for entry in altered["services"]["web"]["entries"]
                     if entry["id"] == "web.state.opflags")
        state["instruction_checks"][0]["text"] = "ld +0xa32c[r0],r8"
        with self.assertRaisesRegex(ValueError, "instruction check"):
            service_lookup.verify_package(altered, str(ATA_ZUP))


if __name__ == "__main__":
    unittest.main()
