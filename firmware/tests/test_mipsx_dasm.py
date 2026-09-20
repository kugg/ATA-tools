"""Synthetic, offline tests for the bounded MIPS-X analysis helper."""

import contextlib
import hashlib
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from firmware import compare_function_hashes, ghidra_decompile_packed
from firmware import mipsx_dasm, zup_bank


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"
TRANSITION_ZUP = ARTIFACT_DIR / "transition.zup"


def jspci(source: int, displacement: int, link: int) -> int:
    assert displacement % 4 == 0
    return ((3 << 30) | (source << 22) | (link << 17)
            | ((displacement // 4) & 0x1FFFF))


class DecodeTest(unittest.TestCase):
    def test_primary_manual_nop_encoding(self):
        instruction = mipsx_dasm.decode(0x60000019, 0x100)
        self.assertEqual((instruction.text, instruction.kind), ("nop", "nop"))

    def test_branch_target_uses_pc_plus_eight_and_word_displacement(self):
        # beq r1,r2,+3 words at 0x100 targets 0x114.
        word = (1 << 27) | (1 << 22) | (2 << 17) | 3
        instruction = mipsx_dasm.decode(word, 0x100)
        self.assertEqual(instruction.target, 0x114)
        self.assertEqual(instruction.role, "branch")

    def test_jspci_uses_signed_word_displacement_and_supplied_base(self):
        word = jspci(24, -0x78, 31)
        instruction = mipsx_dasm.decode(word, 0x200, {24: 0x40A00})
        self.assertEqual(instruction.target, 0x40988)
        self.assertEqual((instruction.role, instruction.base_register), ("call", 24))

    def test_tentative_variant_forms_remain_marked(self):
        word = (2 << 30) | (5 << 27) | (3 << 22) | (4 << 17) | 8
        self.assertTrue(mipsx_dasm.decode(word, 0).text.startswith("movfrc?"))


class InferenceTest(unittest.TestCase):
    def test_call_base_is_ranked_by_stack_prologue_references(self):
        words = [0x60000019] * 32
        words[0] = jspci(24, -0xC0, 31)
        words[1] = jspci(24, -0xC0, 31)
        words[2] = ((3 << 30) | (4 << 27) | (24 << 22) | (2 << 17)
                    | ((-0x30) & 0x1FFFF))
        words[0x40 // 4] = 0xE77BFFE0  # addi r29,-0x20,r29
        data = b"".join(struct.pack(">I", word) for word in words)
        calls, offsets, candidates = mipsx_dasm.infer_base_candidates(
            data, [(0, len(data))], 24)
        self.assertEqual((calls, offsets), (2, 1))
        self.assertEqual(candidates[0], mipsx_dasm.BaseCandidate(
            base=0x100,
            prologue_references=2,
            prologue_targets=1,
            in_range_references=2,
            in_range_targets=1,
            addi_prologue_references=1,
            addi_prologue_targets=1,
        ))

    def test_known_base_resolves_xref_role(self):
        words = [jspci(24, 8, 31), jspci(24, 12, 0), 0x60000019,
                 0x60000019]
        data = b"".join(struct.pack(">I", word) for word in words)
        kinds, ranges, xrefs = mipsx_dasm.collect_xrefs(
            data, [(0, len(data))], "big", {24: 0})
        self.assertEqual(kinds["jump"], 2)
        self.assertEqual(ranges["jump_in_range"], 2)
        self.assertEqual(xrefs[(8, "jump", "call")], 1)
        self.assertEqual(xrefs[(12, "jump", "tail")], 1)

    def test_xref_details_are_bounded_but_stats_do_not_retain_them(self):
        branch = (1 << 27) | (1 << 22) | (2 << 17)
        data = struct.pack(">II", branch, branch)
        with mock.patch.object(mipsx_dasm, "MAX_XREF_RECORDS", 1):
            with self.assertRaisesRegex(ValueError, "too many"):
                mipsx_dasm.collect_xrefs(
                    data, [(0, len(data))], "big", {})
            kinds, _, xrefs = mipsx_dasm.collect_xrefs(
                data, [(0, len(data))], "big", {}, include_details=False)
        self.assertEqual(kinds["branch"], 2)
        self.assertEqual(xrefs, {})

    def test_shared_call_targets_rank_relative_base_delta(self):
        first_words = [
            jspci(23, 0x20, 31), jspci(23, 0x20, 31),
            jspci(23, 0x20, 31), jspci(23, 0x40, 31),
            jspci(23, 0x80, 31),
        ]
        second_words = [
            jspci(23, 0x30, 31), jspci(23, 0x30, 31),
            jspci(23, 0x50, 31), jspci(23, 0x90, 31),
        ]
        first = b"".join(struct.pack(">I", word) for word in first_words)
        second = b"".join(struct.pack(">I", word) for word in second_words)
        counts = mipsx_dasm.infer_shared_base_deltas(
            first, [(0, len(first))], second, [(0, len(second))], 23)
        self.assertEqual(counts[:4], (5, 3, 4, 3))
        self.assertEqual(counts[4][0], mipsx_dasm.SharedDelta(
            delta=-0x10, shared_targets=3, weighted_references=4))

    def test_base_inference_rejects_excessive_pair_work(self):
        words = [jspci(24, 4, 31), 0xE77BFFE0]
        data = b"".join(struct.pack(">I", word) for word in words)
        with mock.patch.object(mipsx_dasm, "MAX_INFERENCE_PAIRS", 0):
            with self.assertRaisesRegex(ValueError, "bounded work"):
                mipsx_dasm.infer_base_candidates(
                    data, [(0, len(data))], 24)

    def test_shared_delta_rejects_excessive_displacement_sets(self):
        first = struct.pack(">II", jspci(23, 4, 31), jspci(23, 8, 31))
        second = struct.pack(">I", jspci(23, 12, 31))
        with mock.patch.object(mipsx_dasm, "MAX_SHARED_DISPLACEMENTS", 1):
            with self.assertRaisesRegex(ValueError, "too many"):
                mipsx_dasm.infer_shared_base_deltas(
                    first, [(0, len(first))], second, [(0, len(second))], 23)


class ControlFlowTest(unittest.TestCase):
    def test_flow_records_two_slots_and_squash_policy(self):
        branch = ((1 << 27) | (1 << 22) | (2 << 17) | 2)
        squash_branch = branch | (1 << 16)
        words = [branch, squash_branch, jspci(24, 0x20, 31),
                 jspci(24, 0x24, 0), (3 << 30) | (5 << 27) | 3]
        data = b"".join(struct.pack(">I", word) for word in words)
        transfers, transfer_count, call_targets = mipsx_dasm.collect_control_flow(
            data, [(0, len(data))], "big", {24: 0})

        self.assertEqual(transfers[0], mipsx_dasm.FlowTransfer(
            0, "branch", 0x10, 0xC, (4, 8), 2, "always"))
        self.assertEqual(transfers[1], mipsx_dasm.FlowTransfer(
            4, "branch", 0x14, 0x10, (8, 12), 2, "taken_only"))
        self.assertEqual(transfers[2], mipsx_dasm.FlowTransfer(
            8, "call", 0x20, 0x14, (12, 16), 2, "always"))
        self.assertEqual(transfers[3], mipsx_dasm.FlowTransfer(
            12, "tail", 0x24, None, (16, 20), 1, "always"))
        self.assertEqual(transfers[4], mipsx_dasm.FlowTransfer(
            16, "jpc", None, None, (20, 24), 0, "always"))
        self.assertEqual(transfer_count, 5)
        self.assertEqual(call_targets, {})

    def test_resolved_local_calls_receive_deterministic_labels(self):
        words = [jspci(24, 8, 31), 0x60000019, 0xE77BFFE0]
        data = b"".join(struct.pack(">I", word) for word in words)
        _, transfer_count, call_targets = mipsx_dasm.collect_control_flow(
            data, [(0, len(data))], "big", {24: 0})
        self.assertEqual(transfer_count, 1)
        self.assertEqual(call_targets, {8: 1})

    def test_flow_retention_is_bounded_while_total_remains_exact(self):
        branch = (1 << 27) | (1 << 22) | (2 << 17)
        data = b"".join(struct.pack(">I", branch) for _ in range(3))
        transfers, transfer_count, _ = mipsx_dasm.collect_control_flow(
            data, [(0, len(data))], "big", {}, limit=1)
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfer_count, 3)

    def test_flow_rejects_excessive_local_call_target_set(self):
        words = [jspci(24, 4, 31), jspci(24, 8, 31), 0x60000019]
        data = b"".join(struct.pack(">I", word) for word in words)
        with mock.patch.object(mipsx_dasm, "MAX_CFG_LOCAL_TARGETS", 1):
            with self.assertRaisesRegex(ValueError, "too many"):
                mipsx_dasm.collect_control_flow(
                    data, [(0, len(data))], "big", {24: 0})


class FunctionHashTest(unittest.TestCase):
    def test_compare_requires_unique_size_and_digest(self):
        left = [(0x100, 8, "a" * 64), (0x200, 8, "b" * 64),
                (0x300, 8, "b" * 64)]
        right = [(0x120, 8, "a" * 64), (0x220, 8, "b" * 64)]
        matches, deltas = compare_function_hashes.compare(left, right)
        self.assertEqual(matches, [(0x100, 0x120, 8)])
        self.assertEqual(deltas, {0x20: 1})

    def test_reader_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "hashes.tsv")
            link = os.path.join(directory, "link.tsv")
            with open(target, "w", encoding="ascii") as output:
                output.write("100\t8\t" + "a" * 64 + "\n")
            os.symlink(target, link)
            with self.assertRaisesRegex(ValueError, "regular file"):
                compare_function_hashes.read_hashes(link)

    def test_reader_rejects_invalid_numeric_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            hashes = os.path.join(directory, "hashes.tsv")
            with open(hashes, "w", encoding="ascii") as output:
                output.write("100\t0\t" + "a" * 64 + "\n")
            with self.assertRaisesRegex(ValueError, "row is invalid"):
                compare_function_hashes.read_hashes(hashes)


class PackedProgramTest(unittest.TestCase):
    def test_naming_rows_reject_control_characters_and_out_of_range_addresses(self):
        with self.assertRaisesRegex(ValueError, "evidence"):
            ghidra_decompile_packed._metadata_text(
                "trusted line\nforged row", "evidence")
        with self.assertRaisesRegex(ValueError, "outside mapped memory"):
            ghidra_decompile_packed._hex_address(
                "0x100", "function address", 0, 0x100)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_sip_main_runtime_layout_and_addresses(self):
        bank = zup_bank.build_bank(zup_bank.read_package(str(ATA_ZUP))).data
        layout = ghidra_decompile_packed.build_runtime_layout(
            bank, 0, 0x479BC)
        self.assertEqual(
            [(region.kind, region.start, region.end) for region in layout],
            [("data", 0x100, 0x26D0),
             ("zero", 0x26D0, 0x2FBC),
             ("data", 0x2FBC, 0x7B84),
             ("zero", 0x7B84, 0xC74C),
             ("code", 0xC74C, 0x686A0)])
        data = b"".join(
            region.data for region in layout
            if region.kind == "data")
        self.assertIn(b"ATA Config Update OK", data)

        code = layout[-1]
        self.assertEqual(code.start + 0x27508, 0x33C54)
        self.assertEqual(
            mipsx_dasm.decode(
                int.from_bytes(code.data[0x27508:0x2750C], "big"),
                0x33C54).text,
            "addi r0,+0x534c,r6")

        sites = ghidra_decompile_packed.resolve_call_sites(
            code.data, "big", {23: code.start + 0x40000}, code.start)
        calls = [(source, target) for source, target, kind in sites
                 if kind == "call"]
        self.assertEqual((len(sites), len(calls),
                          len({target for _, target in calls})),
                         (5823, 3466, 806))
        self.assertIn(code.start + 0x10268,
                      {target for _, target in calls})
        self.assertEqual(sum(
            target == code.start + 0x10268 for _, target in calls), 108)
        starts = ghidra_decompile_packed.resolve_function_starts(
            code.data, "big", {23: code.start + 0x40000}, code.start)
        self.assertEqual(len(starts), 807)
        self.assertEqual((starts[0], starts[-1]), (0x68380, code.start))
        self.assertEqual(starts, sorted(starts, reverse=True))

    @unittest.skipUnless(TRANSITION_ZUP.exists(), "needs transition package")
    def test_transition_runtime_layout(self):
        bank = zup_bank.build_bank(
            zup_bank.read_package(str(TRANSITION_ZUP))).data
        layout = ghidra_decompile_packed.build_runtime_layout(
            bank, 0, 0x4F368)
        self.assertEqual(
            [(region.kind, region.start, region.end) for region in layout],
            [("data", 0x100, 0x2568),
             ("zero", 0x2568, 0x3CE4),
             ("data", 0x3CE4, 0xB514),
             ("zero", 0xB514, 0xF41C),
             ("code", 0xF41C, 0x68284)])

    @unittest.skipUnless(ATA_ZUP.exists() and TRANSITION_ZUP.exists(),
                         "needs pinned ATA packages")
    def test_launch_dispatcher_has_recorded_operations(self):
        sip = zup_bank.build_bank(zup_bank.read_package(str(ATA_ZUP))).data
        transition = zup_bank.build_bank(
            zup_bank.read_package(str(TRANSITION_ZUP))).data
        shared = sip[0x7FD20:0x7FED4]
        self.assertEqual(shared, transition[0x7FD20:0x7FED4])
        self.assertEqual(
            hashlib.sha256(shared).hexdigest(),
            "80d37f8c13ffdd054562b8106419445c3df9cf439c28d5428e88d708127b50bd")

        def decoded_at(offset):
            return mipsx_dasm.decode(
                int.from_bytes(sip[offset:offset + 4], "big"), offset)

        selector_targets = {
            0x7FD2C: 0x7FDDC, 0x7FD38: 0x7FE30, 0x7FD44: 0x7FED0,
            0x7FD50: 0x7FF50, 0x7FD5C: 0x7FE7C, 0x7FD68: 0x7FE70,
            0x7FD74: 0x7FEAC, 0x7FD80: 0x7FEB8, 0x7FD8C: 0x7FEC4,
            0x7FD98: 0x7FE88, 0x7FDA4: 0x7FE94, 0x7FDB0: 0x7FEA0,
            0x7FDBC: 0x7FEE4,
        }
        self.assertEqual(
            {offset: decoded_at(offset).target for offset in selector_targets},
            selector_targets)
        direct_loads = {
            0x7FE74: "ld +0x4[r10],r25",
            0x7FE80: "ld +0x4[r10],r24",
            0x7FE8C: "ld +0x4[r10],r28",
            0x7FE98: "ld +0x4[r10],r29",
            0x7FEA4: "ld +0x4[r10],r19",
            0x7FEB0: "ld +0x4[r10],r23",
            0x7FEBC: "ld +0x4[r10],r4",
            0x7FEC8: "ld +0x4[r10],r5",
        }
        self.assertEqual(
            {offset: decoded_at(offset).text for offset in direct_loads},
            direct_loads)
        terminal = decoded_at(0x7FED8)
        linked_call = decoded_at(0x7FF60)
        self.assertEqual(
            (terminal.text, terminal.role, terminal.base_register),
            ("jspci r13,+0x0,r0", "tail", 13))
        self.assertEqual(
            (linked_call.text, linked_call.role, linked_call.base_register),
            ("jspci r13,+0x0,r31", "call", 13))
        self.assertEqual(
            tuple(decoded_at(offset).text for offset in
                  (0x7FDDC, 0x7FDE0, 0x7FDE4, 0x7FE30, 0x7FE34)),
            ("ld +0x4[r10],r13", "ld +0x8[r10],r12",
             "ld +0xc[r10],r6", "ld +0x4[r10],r13",
             "ld +0x8[r10],r6"))
        self.assertEqual(
            tuple(decoded_at(offset).text for offset in
                  (0x7FF14, 0x7FF1C, 0x7FF24, 0x7FF2C)),
            ("ld +0x0[r20],r0", "ld +0x0[r4],r0",
             "ld +0x0[r13],r0", "ld +0x0[r9],r0"))

    @unittest.skipUnless(ATA_ZUP.exists() and TRANSITION_ZUP.exists(),
                         "needs pinned ATA packages")
    def test_shared_inflate_helper_has_recorded_r24_anchor(self):
        sip = zup_bank.build_bank(zup_bank.read_package(str(ATA_ZUP))).data
        transition = zup_bank.build_bank(
            zup_bank.read_package(str(TRANSITION_ZUP))).data
        for bank, header_offset in ((sip, 0), (transition, 0)):
            launch = zup_bank.parse_launch_table(bank, header_offset)
            code_start = (launch.records[7].field1 * 4
                          - zup_bank.RUNTIME_BANK_BASE)
            code_end = launch.records[0].field1 - zup_bank.RUNTIME_BANK_BASE
            recorded_anchor = (launch.records[6].field1 * 4
                               - zup_bank.RUNTIME_BANK_BASE)
            regions = [(code_start, code_end)]
            kinds, ranges, _ = mipsx_dasm.collect_xrefs(
                bank, regions, "big", {}, include_details=False)
            calls, displacements, candidates = \
                mipsx_dasm.infer_base_candidates(
                    bank, regions, 24, "big", 1)
            self.assertEqual(code_end - code_start, 0x1968)
            self.assertEqual(
                (sum(kinds.values()), kinds["unknown"], kinds["nop"],
                 ranges["branch_in_range"]),
                (1626, 0, 280, 93))
            self.assertEqual((calls, displacements), (45, 9))
            self.assertEqual(recorded_anchor, code_start + 0x40000)
            self.assertEqual(
                (candidates[0].base, candidates[0].prologue_references,
                 candidates[0].prologue_targets,
                 candidates[0].in_range_references,
                 candidates[0].in_range_targets),
                (recorded_anchor, 45, 9, 45, 9))

            def text_at(relative_offset):
                address = code_start + relative_offset
                word = int.from_bytes(bank[address:address + 4], "big")
                return mipsx_dasm.decode(word, address).text

            self.assertEqual(
                tuple(text_at(offset) for offset in
                      (0x14, 0x18, 0x24, 0x38, 0x3C, 0x1124, 0x1134)),
                ("st +0x18[r25],r19", "ld +0x0[r4],r2",
                 "ld +0x4[r4],r5", "st +0x10[r25],r4",
                 "st +0x14[r25],r5", "ld +0x18[r25],r20",
                 "st +0x18[r25],r2"))
            mode_branch = text_at(0x20)
            self.assertTrue(mode_branch.startswith("bnesq r2,r0,"))
            self.assertTrue(mode_branch.endswith(f"{code_start + 0x2C:#010x}"))

    @unittest.skipUnless(ATA_ZUP.exists() and TRANSITION_ZUP.exists(),
                         "needs pinned ATA packages")
    def test_type8_mode0_outputs_are_big_endian_mipsx_programs(self):
        sip = zup_bank.build_bank(zup_bank.read_package(str(ATA_ZUP))).data
        transition = zup_bank.build_bank(
            zup_bank.read_package(str(TRANSITION_ZUP))).data
        cases = (
            (zup_bank.parse_type8_payload(sip, 0x479BC).data,
             sip, 0x40A00, ((0xA00, 0x2C9D4),),
             94165, 44, 15354, 3466, 806, (97, 43, 97, 43)),
            (zup_bank.parse_type8_payload(sip, 0x70010).data,
             sip, 0x40A00, ((0xA00, 0x2C9D4),),
             17275, 37, 3376, 796, 202, (0, 0, 0, 0)),
            (zup_bank.parse_type8_payload(transition, 0x4F368).data,
             transition, 0x40020, ((0x20, 0x2AA60),),
             91034, 44, 15513, 3358, 757, (129, 48, 128, 47)),
        )
        for (data, resident, r24_anchor, resident_regions, words, unknown,
             nops, call_count, call_targets, r24_counts) in cases:
            regions = [(0, len(data))]
            self.assertEqual(
                tuple(mipsx_dasm.decode(
                    int.from_bytes(data[offset:offset + 4], "big"), offset).text
                      for offset in (0, 4, 8, 0x10)),
                ("addi r0,+0x7,r29", "lsl r29,r29,#16",
                 "addi r29,+0xffe0,r29", "mov r0,r25"))
            kinds, ranges, _ = mipsx_dasm.collect_xrefs(
                data, regions, "big", {}, include_details=False)
            little_kinds, _, _ = mipsx_dasm.collect_xrefs(
                data, regions, "little", {}, include_details=False)
            displacements = mipsx_dasm.collect_call_displacements(
                data, regions, 23)
            self.assertEqual(
                (sum(kinds.values()), kinds["unknown"], kinds["nop"]),
                (words, unknown, nops))
            self.assertEqual(ranges["branch_out_of_range"], 0)
            self.assertGreater(little_kinds["unknown"], unknown * 100)
            self.assertEqual(
                (sum(displacements.values()), len(displacements)),
                (call_count, call_targets))
            self.assertTrue(all(
                0 <= 0x40000 + displacement < len(data)
                for displacement in displacements))
            r24_displacements = mipsx_dasm.collect_call_displacements(
                data, regions, 24)
            r24_targets = {
                r24_anchor + displacement for displacement in r24_displacements
            }
            prologue_targets = {
                target for target in r24_targets
                if mipsx_dasm.is_stack_prologue(
                    int.from_bytes(resident[target:target + 4], "big"))
            }
            self.assertTrue(all(
                mipsx_dasm.address_in_regions(target, resident_regions)
                for target in r24_targets))
            self.assertEqual(
                (sum(r24_displacements.values()), len(r24_targets),
                 sum(references for displacement, references
                     in r24_displacements.items()
                     if r24_anchor + displacement in prologue_targets),
                 len(prologue_targets)),
                r24_counts)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_cli_analyzes_checked_type8_output_without_writing(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = mipsx_dasm.main([
                str(ATA_ZUP), "--type8-payload", "0x70010", "--stats"])
        self.assertEqual(result, 0)
        lines = output.getvalue().splitlines()
        self.assertIn("words=17275", lines)
        self.assertIn("unknown=37", lines)
        self.assertIn("nop=3376", lines)
        self.assertIn("branch_in_range=1043", lines)
        self.assertFalse(any(
            line.startswith("branch_out_of_range=") for line in lines))


class FileTest(unittest.TestCase):
    def test_reader_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.bin"
            image.write_bytes(struct.pack(">I", 0x60000019))
            link = Path(directory) / "link.bin"
            link.symlink_to(image)
            with self.assertRaises((OSError, ValueError)):
                mipsx_dasm.read_image(str(link))

    def test_reader_rejects_fifo_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "image.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "regular file"):
                mipsx_dasm.read_image(str(fifo))

    def test_reader_rejects_metadata_change_during_read(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.bin"
            image.write_bytes(struct.pack(">I", 0x60000019))
            real_fstat = os.fstat
            calls = 0

            def changing_fstat(descriptor):
                nonlocal calls
                calls += 1
                result = real_fstat(descriptor)
                if calls == 1:
                    return result
                changed = mock.Mock(wraps=result)
                changed.st_mtime_ns = result.st_mtime_ns + 1
                return changed

            with mock.patch.object(os, "fstat", side_effect=changing_fstat):
                with self.assertRaisesRegex(ValueError, "changed"):
                    mipsx_dasm.read_image(str(image))

    def test_region_count_is_bounded(self):
        regions = [(offset, offset + 4)
                   for offset in range(0, (mipsx_dasm.MAX_REGIONS + 1) * 4, 4)]
        with self.assertRaisesRegex(ValueError, "too many"):
            mipsx_dasm.validate_regions(regions, regions[-1][1])

    def test_cli_stats_are_explicit_and_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.bin"
            image.write_bytes(struct.pack(">I", 0x60000019))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = mipsx_dasm.main([str(image), "--stats"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().splitlines(), ["words=1", "nop=1"])

    def test_cli_diagnostic_does_not_reflect_control_characters(self):
        error = io.StringIO()
        with mock.patch.object(sys, "argv", ["bad\nPROGRAM"]), \
                contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            mipsx_dasm.main(["--bad\nARGUMENT"])
        self.assertNotIn("PROGRAM", error.getvalue())
        self.assertNotIn("ARGUMENT", error.getvalue())
        self.assertIn("error: invalid arguments", error.getvalue())

    def test_plain_disassembly_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.bin"
            image.write_bytes(struct.pack(">II", 0x60000019, 0x60000019))
            error = io.StringIO()
            with mock.patch.object(mipsx_dasm, "MAX_DISASSEMBLY_WORDS", 1), \
                    contextlib.redirect_stderr(error):
                result = mipsx_dasm.main([str(image)])
        self.assertEqual(result, 1)
        self.assertEqual(
            error.getvalue(), "error: disassembly output exceeds bounded limit\n")


if __name__ == "__main__":
    unittest.main()
