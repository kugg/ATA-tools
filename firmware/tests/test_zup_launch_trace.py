#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Offline synthetic and pinned tests for the C launch-trace model.

The C tool reads one exact 512 KiB bank from stdin and emits fixed
numeric trace lines. It never executes firmware or touches the network.
Pinned vectors use only hashes, offsets, counts, and decoded register
relationships through zup_bank; no proprietary bytes enter the repo.
"""

import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from firmware import zup_bank
from firmware import zup_extract


ROOT = Path(__file__).resolve().parents[2]
C_SOURCE = ROOT / "firmware" / "zup_launch_trace.c"
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"
TRANSITION_ZUP = ARTIFACT_DIR / "transition.zup"

BANK_BYTES = 0x80000
RUNTIME_BASE = 0x0CF80000
SECTION_OFFSET = 0x40000
SECTION_MAGIC = 0x12340004
SEED = 0xDEADBEEF


def find_cc():
    override = os.environ.get("CC")
    if override:
        # Allow exactly one executable path; never a shell string.
        if any(c in override for c in (" ", ";", "&", "|", "$", "`", "\n")):
            raise ValueError("CC must be one executable path")
        path = Path(override)
        if not path.is_file():
            return None
        return str(path)
    found = shutil.which("cc")
    if found:
        return found
    found = shutil.which("clang")
    if found:
        return found
    found = shutil.which("gcc")
    return found


def compile_trace(tmpdir):
    cc = find_cc()
    if cc is None:
        return None
    out = os.path.join(tmpdir, "zup_launch_trace")
    cmd = [cc, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror",
           str(C_SOURCE), "-o", out]
    proc = subprocess.run(cmd, capture_output=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(
            "C11 strict compile failed: " + proc.stderr.decode(
                "utf-8", "replace")[:2000])
    return out


def run_trace(binary, bank, *args):
    return subprocess.run(
        [binary, *args], input=bank, capture_output=True, timeout=5)


def synthetic_bank():
    return bytearray(b"\xff" * BANK_BYTES)


def write_header(bank, header_offset, field0, table_offset, count, field3):
    table_address = RUNTIME_BASE + table_offset
    struct.pack_into(">IIII", bank, header_offset, field0, table_address,
                     count, field3)


def write_record(bank, table_offset, index, rtype, f1, f2, f3):
    struct.pack_into(">IIII", bank, table_offset + index * 16, rtype, f1, f2,
                     f3)


def write_section(bank, descriptors, stored=None, magic=SECTION_MAGIC):
    struct.pack_into(">I", bank, SECTION_OFFSET, magic)
    calc = SEED
    for desc in descriptors:
        start = (desc >> 16) << 8
        size = (desc & 0xFFFF) << 8
        for off in range(start, start + size, 4):
            calc ^= struct.unpack_from(">I", bank, off)[0]
    if stored is None:
        stored = calc
    struct.pack_into(">I", bank, SECTION_OFFSET + 4, stored)
    for i, desc in enumerate(descriptors):
        struct.pack_into(">I", bank, SECTION_OFFSET + 8 + i * 4, desc)
    return calc, stored


def minimal_table(bank, table_offset, types_fields):
    for i, (t, f1, f2, f3) in enumerate(types_fields):
        write_record(bank, table_offset, i, t, f1, f2, f3)


def parse_stdout(text):
    lines = text.splitlines()
    recs = []
    events = []
    validator = None
    header = None
    for line in lines:
        if line.startswith("validator "):
            validator = line
        elif line.startswith("header "):
            header = line
        elif line.startswith("copy ") or line.startswith("zero ") or \
                line.startswith("reg ") or line.startswith("call ") or \
                line.startswith("type_d ") or line.startswith("terminal "):
            events.append(line)
        else:
            recs.append(line)
    return validator, header, events, lines


class TraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        try:
            cls.binary = compile_trace(cls._tmp.name)
        except Exception as exc:
            raise
        if cls.binary is None:
            raise unittest.SkipTest("needs C11 compiler")

    def test_source_exists(self):
        self.assertTrue(C_SOURCE.is_file())

    def test_all_record_types_trace(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 13, 0)
        rows = [
            (1, RUNTIME_BASE + 0x3000, 0x4000, 4),
            (8, 0x11111111, 0, 0),
            (9, 0x22222222, 0, 0),
            (6, 0x0007FC00, 0, 0),
            (0xB, 0x0007F800, 0, 0),
            (0xC, 0x00001000, 0, 0),
            (5, 0x033F0280, 0, 0),
            (4, 0x033FF400, 0, 0),
            (0xA, 0xAAAAAAAA, 0, 0),
            (2, 0x5000, 8, 0),
            (7, 0x000131D3, 0, 0),
            (0xD, 0x6000, 0x40, 0),
            (3, 0x400031D3, 0, 0),
        ]
        minimal_table(bank, to, rows)
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:1000])
        out = proc.stdout.decode()
        validator, header, events, lines = parse_stdout(out)
        self.assertIsNone(validator)
        self.assertIsNotNone(header)
        self.assertEqual(len(events), 13)
        self.assertTrue(events[0].startswith("copy index=0 "))
        self.assertIn("word_count=4", events[0])
        self.assertIn("byte_count=16", events[0])
        self.assertTrue(events[1].startswith("reg index=1 "))
        self.assertIn("reg=r4", events[1])
        self.assertIn("value=0x11111111", events[1])
        self.assertIn("reg=r5", events[2])
        self.assertIn("reg=r25", events[3])
        self.assertIn("reg=r29", events[4])
        self.assertIn("reg=r19", events[5])
        self.assertIn("reg=r24", events[6])
        self.assertTrue(events[7].startswith("call index=7 "))
        self.assertIn("target=0x033ff400", events[7].lower())
        self.assertIn("reg=r28", events[8])
        self.assertTrue(events[9].startswith("zero index=9 "))
        self.assertIn("word_count=8", events[9])
        self.assertIn("reg=r23", events[10])
        self.assertTrue(events[11].startswith("type_d index=11 "))
        self.assertIn("blocks=4", events[11])
        self.assertTrue(events[12].startswith("terminal index=12 "))
        self.assertIn("target=0x400031d3", events[12].lower())

    def test_type_d_blocks_and_bounds(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 2, 0)
        minimal_table(bank, to, [(0xD, 0x10000, 0x30, 0),
                                 (3, 0x40000000, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertEqual(proc.returncode, 0)
        _, _, events, _ = parse_stdout(proc.stdout.decode())
        self.assertEqual(len(events), 2)
        self.assertIn("base=0x00010000", events[0])
        self.assertIn("length=0x00000030", events[0])
        self.assertIn("blocks=3", events[0])

    def test_rejects_unknown_type(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 2, 0)
        minimal_table(bank, to, [(0xE, 0, 0, 0), (3, 0x40000000, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")
        self.assertIn(b"failed closed", proc.stderr)

    def test_rejects_missing_terminal(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 2, 0)
        minimal_table(bank, to, [(5, 1, 0, 0), (6, 2, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_rejects_nonterminal_type3(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 3, 0)
        minimal_table(bank, to, [(5, 1, 0, 0), (3, 0x40000000, 0, 0),
                                 (5, 2, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_rejects_copy_overflow(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 2, 0)
        minimal_table(bank, to, [(1, RUNTIME_BASE, 0xFFFFFFFC, 2),
                                 (3, 0x40000000, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_rejects_zero_overflow(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 2, 0)
        minimal_table(bank, to, [(2, 0xFFFFFFF0, 0x40000000, 0),
                                 (3, 0x40000000, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_rejects_type_d_overflow(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 2, 0)
        minimal_table(bank, to, [(0xD, 0xFFFFFF00, 0xFFFFFFFF, 0),
                                 (3, 0x40000000, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_rejects_bad_header_and_table(self):
        for ho, to, count, table_addr_override in [
                (0x1001, 0x2000, 1, None),
                (0x80000, 0x2000, 1, None),
                (0x1000, 0x2001, 1, None),
                (0x1000, 0x2000, 0, None),
                (0x1000, 0x2000, 257, None),
        ]:
            bank = synthetic_bank()
            if ho + 16 <= BANK_BYTES:
                if table_addr_override is None:
                    write_header(bank, ho if ho < BANK_BYTES else 0, 0, to,
                                 count, 0)
                else:
                    struct.pack_into(">IIII", bank, ho, 0,
                                     table_addr_override, count, 0)
                if to + count * 16 <= BANK_BYTES and count <= 256 and count > 0:
                    for i in range(count):
                        t = 3 if i == count - 1 else 5
                        write_record(bank, to, i, t, 1, 0, 0)
            arg = "0x%x" % ho if ho < 0x100000 else str(ho)
            proc = run_trace(self.binary, bytes(bank), "--header-offset", arg)
            self.assertNotEqual(proc.returncode, 0, f"ho={ho:#x}")
            self.assertEqual(proc.stdout, b"")
        # Table address outside mapped bank.
        bank = synthetic_bank()
        struct.pack_into(">IIII", bank, 0x1000, 0, 0x00000000, 1, 0)
        write_record(bank, 0x2000, 0, 3, 0x40000000, 0, 0)
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_rejects_truncated_and_extra_input(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 1, 0)
        write_record(bank, to, 0, 3, 0x40000000, 0, 0)
        proc = run_trace(self.binary, bytes(bank)[:100],
                         "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")
        proc = run_trace(self.binary, bytes(bank) + b"\x00",
                         "--header-offset", "0x1000")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_rejects_invalid_args(self):
        bank = synthetic_bank()
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "nope")
        self.assertEqual(proc.returncode, 2)
        proc = run_trace(self.binary, bytes(bank), "--bogus")
        self.assertEqual(proc.returncode, 2)

    def test_output_is_bounded(self):
        bank = synthetic_bank()
        ho, to = 0x1000, 0x2000
        write_header(bank, ho, 0, to, 2, 0)
        minimal_table(bank, to, [(5, 1, 0, 0), (3, 0x40000000, 0, 0)])
        proc = run_trace(self.binary, bytes(bank), "--header-offset", "0x1000")
        self.assertEqual(proc.returncode, 0)
        self.assertLess(len(proc.stdout), 100 * 1024)
        self.assertLess(len(proc.stdout.splitlines()), 600)

    def _validator_bank(self, mode):
        bank = synthetic_bank()
        # Main table: 27 records, aux table: 18 records.
        main_to, aux_to = 0x40110, 0x76EE0
        main_rows = [(5, 0x100 + i, 0, 0) for i in range(26)]
        main_rows.append((3, 0x400031D3, 0, 0))
        aux_rows = [(5, 0x200 + i, 0, 0) for i in range(17)]
        aux_rows.append((3, 0x40000C00, 0, 0))
        minimal_table(bank, main_to, main_rows)
        minimal_table(bank, aux_to, aux_rows)
        write_header(bank, 0x40100, 0, main_to, 27, 0xD)
        write_header(bank, 0x70000, 0x00012102, aux_to, 18, 0x06)
        descriptors = [0x00000001, 0x00100001, 0x00200001, 0x00300001]
        calc, _ = write_section(bank, descriptors)
        if mode == "match":
            struct.pack_into(">I", bank, SECTION_OFFSET + 4, calc)
        elif mode == "mismatch":
            struct.pack_into(">I", bank, SECTION_OFFSET + 4, calc ^ 1)
        elif mode == "marker":
            struct.pack_into(">I", bank, SECTION_OFFSET, 0xDEADBEEF)
        elif mode == "descriptor":
            struct.pack_into(">I", bank, SECTION_OFFSET + 8, 0x7FF007FF)
        return bank

    def test_validator_selects_main_on_match(self):
        bank = self._validator_bank("match")
        proc = run_trace(self.binary, bytes(bank))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:1000])
        out = proc.stdout.decode()
        self.assertIn("selection=main", out)
        self.assertIn("header_bank_offset=0x40100", out)
        self.assertIn("records=27", out)

    def test_validator_selects_aux_on_mismatch(self):
        bank = self._validator_bank("mismatch")
        proc = run_trace(self.binary, bytes(bank))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:1000])
        out = proc.stdout.decode()
        self.assertIn("selection=auxiliary", out)
        self.assertIn("header_bank_offset=0x70000", out)
        self.assertIn("records=18", out)

    def test_validator_rejects_marker_mismatch(self):
        bank = self._validator_bank("marker")
        proc = run_trace(self.binary, bytes(bank))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")
        self.assertIn(b"unsupported marker mismatch", proc.stderr)

    def test_validator_rejects_bad_descriptor(self):
        bank = self._validator_bank("descriptor")
        proc = run_trace(self.binary, bytes(bank))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_callback_failure_propagates(self):
        # Build a tiny harness that links the model with NO_MAIN and uses
        # a callback that always fails. Generated only in a temp dir.
        harness_c = os.path.join(self._tmp.name, "cb_harness.c")
        harness_bin = os.path.join(self._tmp.name, "cb_harness")
        cc = find_cc()
        self.assertIsNotNone(cc)
        with open(harness_c, "w", encoding="utf-8") as f:
            f.write('#define ZUP_LAUNCH_TRACE_NO_MAIN\n'
                    '#include "%s"\n'
                    '#include <stdio.h>\n'
                    '#include <string.h>\n'
                    'static int fail_cb(const zlt_event *ev, void *ctx)\n'
                    '{ (void)ev; (void)ctx; return 1; }\n'
                    'int main(void)\n'
                    '{\n'
                    ' static unsigned char bank[0x80000];\n'
                    ' uint32_t ho=0x1000u, to=0x2000u;\n'
                    ' memset(bank, 0xFF, sizeof(bank));\n'
                    ' bank[ho]=0; bank[ho+1]=0; bank[ho+2]=0; bank[ho+3]=0;\n'
                    ' bank[ho+4]=0x0C; bank[ho+5]=0xF8; bank[ho+6]=0x20;'
                    ' bank[ho+7]=0x00;\n'
                    ' bank[ho+8]=0; bank[ho+9]=0; bank[ho+10]=0; bank[ho+11]=1;\n'
                    ' bank[ho+12]=0; bank[ho+13]=0; bank[ho+14]=0; bank[ho+15]=0;\n'
                    ' bank[to]=0; bank[to+1]=0; bank[to+2]=0; bank[to+3]=3;\n'
                    ' bank[to+4]=0x40; bank[to+5]=0; bank[to+6]=0; bank[to+7]=0;\n'
                    ' bank[to+8]=0; bank[to+9]=0; bank[to+10]=0; bank[to+11]=0;\n'
                    ' bank[to+12]=0; bank[to+13]=0; bank[to+14]=0; bank[to+15]=0;\n'
                    ' if (zlt_trace_bank(bank, sizeof(bank), ho, 0x0CF80000u,'
                    ' 0, NULL, fail_cb, NULL) == ZLT_ERR_CALLBACK) {\n'
                    '  printf("CALLBACK_PROPAGATED\\n"); return 0; }\n'
                    ' printf("CALLBACK_NOT_PROPAGATED\\n"); return 1; }\n'
                    % str(C_SOURCE))
        cmd = [cc, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra",
               "-Werror", harness_c, "-o", harness_bin]
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0,
                         proc.stderr.decode("utf-8", "replace")[:2000])
        proc = subprocess.run([harness_bin], capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"CALLBACK_PROPAGATED", proc.stdout)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA .zup")
    def test_pinned_sip_main_matches_python(self):
        bank = zup_bank.build_bank(
            zup_bank.read_package(str(ATA_ZUP))).data
        table = zup_bank.parse_launch_table(bank, 0x40100)
        self.assertEqual((table.table_offset, table.record_count),
                         (0x40110, 27))
        proc = run_trace(self.binary, bank, "--header-offset", "0x40100")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:1000])
        out = proc.stdout.decode()
        for rec in table.records:
            token = "bank_offset=0x%x" % rec.offset
            self.assertIn(token, out)
            self.assertIn("value=0x%08x" % rec.field1
                          if rec.record_type not in (1, 2, 3, 4, 0xD)
                          else "index=%u" % table.records.index(rec), out)
        self.assertIn("terminal index=26", out)
        self.assertIn("target=0x400031d3", out.lower())
        # Validator default must select the same main table.
        proc = run_trace(self.binary, bank)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("selection=main", proc.stdout.decode())
        self.assertIn("records=27", proc.stdout.decode())

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA .zup")
    def test_pinned_sip_aux_matches_python(self):
        bank = zup_bank.build_bank(
            zup_bank.read_package(str(ATA_ZUP))).data
        table = zup_bank.parse_launch_table(bank, 0x70000)
        self.assertEqual((table.table_offset, table.record_count),
                         (0x76EE0, 18))
        proc = run_trace(self.binary, bank, "--header-offset", "0x70000")
        self.assertEqual(proc.returncode, 0)
        out = proc.stdout.decode()
        self.assertIn("terminal index=17", out)
        self.assertIn("target=0x40000c00", out.lower())
        self.assertEqual(
            [r.record_type for r in table.records],
            [0x1, 0x8, 0x9, 0x6, 0xB, 0xC, 0x5, 0x4,
             0x1, 0x8, 0x6, 0xB, 0xC, 0x5, 0x4, 0x2, 0x7, 0x3])

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA .zup")
    def test_pinned_composed_edit_still_selects_main(self):
        package = zup_bank.read_package(str(ATA_ZUP))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            for header in manifest["launch_headers"]:
                if header["header_offset"] == 0x70000:
                    header["records"][13]["field1"] ^= 4

            def read_payload(entry):
                with open(os.path.join(out, entry["file"]), "rb") as f:
                    return f.read()

            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank = f.read()
            composed = zup_extract.compose_bank(
                manifest, bank, read_payload)
            proc = run_trace(self.binary, composed)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:1000])
            self.assertIn("selection=main", proc.stdout.decode())
            self.assertIn("header_bank_offset=0x40100", proc.stdout.decode())

    @unittest.skipUnless(TRANSITION_ZUP.exists(), "needs transition .zup")
    def test_pinned_transition_matches_python(self):
        bank = zup_bank.build_bank(
            zup_bank.read_package(str(TRANSITION_ZUP))).data
        table = zup_bank.parse_launch_table(bank, 0)
        self.assertEqual((table.table_offset, table.record_count),
                         (0x7B620, 15))
        proc = run_trace(self.binary, bank, "--header-offset", "0x0")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:1000])
        out = proc.stdout.decode()
        self.assertIn("terminal index=14", out)
        self.assertIn("target=0x40003d07", out.lower())
        # Transition has no SIP section header; validator must report the
        # explicit unsupported marker path rather than guessing.
        proc = run_trace(self.binary, bank)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(b"unsupported marker mismatch", proc.stderr)


if __name__ == "__main__":
    unittest.main()
