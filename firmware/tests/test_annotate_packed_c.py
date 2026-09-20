#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Tests for packed-main call annotation (deterministic, target-validated)."""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from firmware import annotate_packed_c


class AnnotateTests(unittest.TestCase):
    def test_r23_call_resolves_to_verified_target(self):
        # (in_r23 + -0xffb5) * 4 with anchor 0x10000 -> 0x12c
        target = ((annotate_packed_c.R23_ANCHOR_WORD - 0xFFB5) * 4) & 0xFFFFFFFF
        text = "  (*(code *)((in_r23 + -0xffb5) * 4))();\n"
        annotated, stats = annotate_packed_c.annotate(text, {target})
        self.assertIn(
            f"sub_{annotate_packed_c.CODE_START + target:08x}()", annotated)
        self.assertEqual(stats["r23_resolved"], 1)
        self.assertEqual(stats["r23_unverified"], 0)

    def test_unverified_target_is_left_untouched(self):
        text = "  (*(code *)((in_r23 + -0xffb5) * 4))();\n"
        annotated, stats = annotate_packed_c.annotate(text, set())
        self.assertEqual(annotated, text)
        self.assertEqual(stats["r23_resolved"], 0)
        self.assertEqual(stats["r23_unverified"], 1)

    def test_link_return_becomes_return(self):
        text = "  (*(code *)(in_r31 << 2))();\n  return;\n"
        annotated, stats = annotate_packed_c.annotate(text, set())
        self.assertEqual(stats["returns"], 1)
        self.assertNotIn("in_r31 << 2", annotated)
        self.assertIn("return", annotated)

    def test_both_signs_of_displacement(self):
        pos = 0x2803
        target = ((annotate_packed_c.R23_ANCHOR_WORD + pos) * 4) & 0xFFFFFFFF
        text = f"  (*(code *)((in_r23 + 0x{pos:x}) * 4))();\n"
        annotated, stats = annotate_packed_c.annotate(text, {target})
        self.assertIn(
            f"sub_{annotate_packed_c.CODE_START + target:08x}()", annotated)
        self.assertEqual(stats["r23_resolved"], 1)


if __name__ == "__main__":
    unittest.main()
