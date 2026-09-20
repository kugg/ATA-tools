"""Offline synthetic and optional pinned-artifact tests for bank reconstruction."""

import contextlib
import hashlib
import io
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from firmware import zup_bank


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"
TRANSITION_ZUP = ARTIFACT_DIR / "transition.zup"
ATA_BANK_SHA256 = "ee2247ad3b9cbd5d711f4985cbdce220359e6edff6555d8486e119e767c8f8c6"
TRANSITION_BANK_SHA256 = (
    "ad7abb7575a14885c171f4cf6a630f60547d2ccd03b47b55c04a279278332eee"
)


def raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    stream = compressor.compress(data) + compressor.flush()
    return stream + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


def synthetic_package(
        compressed_destination: int = 8, map_gap: bytes = b"ATA4",
        format_version: int = 2) -> bytes:
    raw = b"RAW!"
    plain = b"compressed-test"
    stored = raw_deflate(plain)
    content = raw + stored
    table_offset = zup_bank.INNER_HEADER_BYTES + len(content) + len(map_gap)
    table = struct.pack(">HHIIIII", 1, 1, 0, len(raw),
                        compressed_destination, len(plain), len(stored))
    table += struct.pack(">I", format_version)
    inner_size = (zup_bank.INNER_HEADER_BYTES + len(content)
                  + len(map_gap) + len(table))
    inner = bytearray(b"+kxz" + b"\x00" * 4
                      + struct.pack(">II", inner_size, table_offset)
                      + content + map_gap + table)
    struct.pack_into(">I", inner, 4, sum(inner[12:]) & 0xFFFFFFFF)
    outer = (b"kup1" + b"00000000" + b"\x00" * 4
             + struct.pack(">IHH", 0x301, 0x400, 0x301))
    return outer + inner


def synthetic_nested_payload(data: bytes) -> bytes:
    stored = raw_deflate(data)
    return struct.pack(
        ">4sIIIII", b"+kbz", 2, sum(stored) & 0xFFFFFFFF, len(stored),
        sum(data) & 0xFFFFFFFF, len(data)) + stored


class ReconstructionTest(unittest.TestCase):
    def test_synthetic_map_reconstructs_ff_filled_bank(self):
        result = zup_bank.build_bank(synthetic_package())
        self.assertEqual(len(result.data), zup_bank.BANK_BYTES)
        self.assertEqual(result.data[:4], b"RAW!")
        self.assertEqual(result.data[4:8], b"\xff" * 4)
        self.assertEqual(result.data[8:23], b"compressed-test")
        self.assertEqual(result.data[23:32], b"\xff" * 9)
        self.assertEqual((len(result.raw_regions), len(result.compressed_regions)),
                         (1, 1))

    def test_corrupt_crc_is_rejected_after_envelope_checksum_update(self):
        package = bytearray(synthetic_package())
        result = zup_bank.build_bank(package)
        compressed = result.compressed_regions[0]
        package[compressed.source + compressed.stored_size - 8] ^= 1
        struct.pack_into(">I", package, 28, sum(package[36:]) & 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "trailer"):
            zup_bank.build_bank(package)

    def test_truncated_and_concatenated_streams_are_rejected(self):
        stored = raw_deflate(b"bounded output")
        with self.assertRaises(ValueError):
            zup_bank._inflate_region(stored[:-9], len(b"bounded output"))
        with self.assertRaisesRegex(ValueError, "trailer"):
            zup_bank._inflate_region(stored + raw_deflate(b"second"),
                                     len(b"bounded output"))

    def test_map_without_gap_is_supported(self):
        result = zup_bank.build_bank(synthetic_package(map_gap=b""))
        self.assertEqual(result.data[:4], b"RAW!")
        self.assertEqual(result.data[8:23], b"compressed-test")

    def test_unknown_map_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "map version"):
            zup_bank.build_bank(synthetic_package(format_version=3))

    def test_overlapping_destinations_are_rejected(self):
        with mock.patch.object(zup_bank, "_inflate_region") as inflate:
            with self.assertRaisesRegex(ValueError, "overlap"):
                zup_bank.build_bank(synthetic_package(compressed_destination=2))
        inflate.assert_not_called()

    def test_private_output_is_mode_0600_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bank.bin"
            zup_bank.publish_private(str(target), b"complete")
            self.assertEqual(target.read_bytes(), b"complete")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                zup_bank.publish_private(str(target), b"replacement")
            self.assertEqual(target.read_bytes(), b"complete")

    def test_private_output_rejects_a_symlink_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            real_parent = Path(directory) / "real"
            real_parent.mkdir(mode=0o700)
            linked_parent = Path(directory) / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                zup_bank.publish_private(str(linked_parent / "bank.bin"), b"data")
            self.assertFalse((real_parent / "bank.bin").exists())

    def test_private_output_rolls_back_if_parent_path_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "output"
            moved = Path(directory) / "moved"
            parent.mkdir(mode=0o700)
            real_link = os.link

            def swap_parent(source, target, **kwargs):
                parent.rename(moved)
                parent.mkdir(mode=0o700)
                real_link(source, target, **kwargs)

            with mock.patch.object(os, "link", side_effect=swap_parent):
                with self.assertRaisesRegex(ValueError, "directory changed"):
                    zup_bank.publish_private(str(parent / "bank.bin"), b"data")
            self.assertFalse((parent / "bank.bin").exists())
            self.assertFalse((moved / "bank.bin").exists())

    def test_private_output_does_not_unlink_replaced_staging_name(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            temporary_name = ".bank.bin.fixed"

            def replace_staging(source, _target, **kwargs):
                os.unlink(source, dir_fd=kwargs["src_dir_fd"])
                descriptor = os.open(
                    source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                    dir_fd=kwargs["src_dir_fd"])
                try:
                    os.write(descriptor, b"replacement")
                finally:
                    os.close(descriptor)
                raise OSError("simulated publication failure")

            with mock.patch.object(zup_bank.secrets, "token_hex",
                                   return_value="fixed"), \
                    mock.patch.object(os, "link", side_effect=replace_staging):
                with self.assertRaises(OSError):
                    zup_bank.publish_private(str(parent / "bank.bin"), b"data")
            self.assertEqual((parent / temporary_name).read_bytes(), b"replacement")

    def test_reader_rejects_fifo_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "package.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "regular file"):
                zup_bank.read_package(str(fifo))

    def test_reader_rejects_metadata_change_during_read(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package.zup"
            package.write_bytes(synthetic_package())
            real_fstat = os.fstat
            calls = 0

            def changing_fstat(descriptor):
                nonlocal calls
                calls += 1
                result = real_fstat(descriptor)
                if calls == 1:
                    return result
                changed = mock.Mock(wraps=result)
                changed.st_ctime_ns = result.st_ctime_ns + 1
                return changed

            with mock.patch.object(os, "fstat", side_effect=changing_fstat):
                with self.assertRaisesRegex(ValueError, "changed"):
                    zup_bank.read_package(str(package))

    def test_cli_diagnostic_does_not_reflect_control_characters(self):
        error = io.StringIO()
        with mock.patch.object(sys, "argv", ["bad\nPROGRAM"]), \
                contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            zup_bank.main(["--bad\nARGUMENT"])
        self.assertNotIn("PROGRAM", error.getvalue())
        self.assertNotIn("ARGUMENT", error.getvalue())
        self.assertIn("error: invalid arguments", error.getvalue())

    def test_launch_table_maps_counted_records(self):
        bank = bytearray(b"\xff" * zup_bank.BANK_BYTES)
        table_offset = 0x100
        struct.pack_into(">IIII", bank, 0, 0x1234,
                         zup_bank.RUNTIME_BANK_BASE + table_offset, 2, 7)
        struct.pack_into(">IIII", bank, table_offset, 1,
                         zup_bank.RUNTIME_BANK_BASE + 0x200, 0x100, 4)
        struct.pack_into(">IIII", bank, table_offset + 16, 2, 0x110, 2, 0)

        table = zup_bank.parse_launch_table(bytes(bank), 0)
        self.assertEqual((table.table_offset, table.record_count, table.field3),
                         (0x100, 2, 7))
        self.assertEqual(table.records[0], zup_bank.LaunchRecord(
            0x100, 1, zup_bank.RUNTIME_BANK_BASE + 0x200, 0x100, 4))
        self.assertEqual(table.records[1], zup_bank.LaunchRecord(
            0x110, 2, 0x110, 2, 0))

    def test_launch_table_rejects_unmapped_pointer(self):
        bank = bytearray(b"\xff" * zup_bank.BANK_BYTES)
        struct.pack_into(">IIII", bank, 0, 0, 0x100, 1, 0)
        with self.assertRaisesRegex(ValueError, "outside"):
            zup_bank.parse_launch_table(bytes(bank), 0)

    def test_nested_payload_validates_stream_and_both_byte_sums(self):
        plain = b"nested payload"
        encoded = synthetic_nested_payload(plain)
        bank = encoded + b"\xff" * (zup_bank.BANK_BYTES - len(encoded))
        payload = zup_bank.parse_nested_payload(bank, 0)
        self.assertEqual(payload.data, plain)
        self.assertEqual(payload.stored_size, len(encoded) - 24)
        self.assertEqual(payload.output_checksum, sum(plain))
        self.assertEqual(payload.crc32, zlib.crc32(plain) & 0xFFFFFFFF)

    def test_nested_payload_rejects_stored_sum_before_inflating(self):
        bank = bytearray(b"\xff" * zup_bank.BANK_BYTES)
        encoded = bytearray(synthetic_nested_payload(b"nested payload"))
        encoded[8] ^= 1
        bank[:len(encoded)] = encoded
        with mock.patch.object(zup_bank, "_inflate_region") as inflate:
            with self.assertRaisesRegex(ValueError, "stored checksum"):
                zup_bank.parse_nested_payload(bytes(bank), 0)
        inflate.assert_not_called()

    def test_nested_payload_rejects_aggregate_budget_before_inflating(self):
        plain = b"nested payload"
        encoded = synthetic_nested_payload(plain)
        bank = encoded + b"\xff" * (zup_bank.BANK_BYTES - len(encoded))
        with mock.patch.object(zup_bank, "_inflate_region") as inflate:
            with self.assertRaisesRegex(ValueError, "aggregate"):
                zup_bank.parse_nested_payload(bank, 0, len(plain) - 1)
        inflate.assert_not_called()

    def test_type8_payload_validates_crc_and_mode1_destination(self):
        plain = b"initialized data"
        encoded = struct.pack(">II", 1, 0x100) + raw_deflate(plain)
        bank = encoded + b"\xff" * (zup_bank.BANK_BYTES - len(encoded))
        payload = zup_bank.parse_type8_payload(bank, 0)
        self.assertEqual(payload.data, plain)
        self.assertEqual((payload.mode, payload.field), (1, 0x100))
        self.assertEqual(payload.compressed_size, len(encoded) - 16)
        self.assertEqual(payload.crc32, zlib.crc32(plain) & 0xFFFFFFFF)

    def test_type8_payload_rejects_bad_crc_and_excessive_output(self):
        plain = b"bounded type-8 output"
        encoded = bytearray(struct.pack(">II", 0, 0x483BD241)
                            + raw_deflate(plain))
        encoded[-8] ^= 1
        bank = bytes(encoded) + b"\xff" * (zup_bank.BANK_BYTES - len(encoded))
        with self.assertRaisesRegex(ValueError, "CRC-32"):
            zup_bank.parse_type8_payload(bank, 0)

        encoded = struct.pack(">II", 0, 0x483BD241) + raw_deflate(plain)
        bank = encoded + b"\xff" * (zup_bank.BANK_BYTES - len(encoded))
        with self.assertRaisesRegex(ValueError, "output budget"):
            zup_bank.parse_type8_payload(bank, 0, len(plain) - 1)

    def test_type8_payload_rejects_mode_and_destination_bounds(self):
        stored = raw_deflate(b"data")
        bad_mode = struct.pack(">II", 2, 0) + stored
        bank = bad_mode + b"\xff" * (zup_bank.BANK_BYTES - len(bad_mode))
        with self.assertRaisesRegex(ValueError, "mode"):
            zup_bank.parse_type8_payload(bank, 0)

        bad_destination = struct.pack(">II", 1, zup_bank.BANK_BYTES) + stored
        bank = bad_destination + b"\xff" * (
            zup_bank.BANK_BYTES - len(bad_destination))
        with mock.patch.object(zup_bank.zlib, "decompressobj") as decompress:
            with self.assertRaisesRegex(ValueError, "destination"):
                zup_bank.parse_type8_payload(bank, 0)
        decompress.assert_not_called()

        exact_destination = struct.pack(
            ">II", 1, zup_bank.BANK_BYTES - 4) + stored
        bank = exact_destination + b"\xff" * (
            zup_bank.BANK_BYTES - len(exact_destination))
        self.assertEqual(zup_bank.parse_type8_payload(bank, 0).data, b"data")

        crossing_destination = struct.pack(
            ">II", 1, zup_bank.BANK_BYTES - 3) + stored
        bank = crossing_destination + b"\xff" * (
            zup_bank.BANK_BYTES - len(crossing_destination))
        with self.assertRaisesRegex(ValueError, "output budget"):
            zup_bank.parse_type8_payload(bank, 0)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA .zup")
    def test_pinned_package_reconstructs_known_bank(self):
        result = zup_bank.build_bank(zup_bank.read_package(str(ATA_ZUP)))
        self.assertEqual(hashlib.sha256(result.data).hexdigest(), ATA_BANK_SHA256)
        self.assertEqual((len(result.raw_regions), len(result.compressed_regions)),
                         (4, 7))
        main = zup_bank.parse_launch_table(result.data, 0)
        staged_main = zup_bank.parse_launch_table(result.data, 0x40100)
        auxiliary = zup_bank.parse_launch_table(result.data, 0x70000)
        self.assertEqual((main.table_offset, main.record_count), (0x40110, 27))
        self.assertEqual(staged_main.records, main.records)
        self.assertEqual((auxiliary.table_offset, auxiliary.record_count),
                         (0x76EE0, 18))
        magic, stored_checksum = struct.unpack_from(">II", result.data, 0x40000)
        descriptors = struct.unpack_from(">4I", result.data, 0x40008)
        calculated_checksum = 0xDEADBEEF
        for descriptor in descriptors:
            start = (descriptor >> 16) << 8
            size = (descriptor & 0xFFFF) << 8
            for offset in range(start, start + size, 4):
                calculated_checksum ^= struct.unpack_from(">I", result.data, offset)[0]
        self.assertEqual((magic, stored_checksum, calculated_checksum),
                         (0x12340004, 0x61F0752A, 0x61F0752A))
        self.assertEqual(zup_bank.RUNTIME_BANK_BASE + staged_main.header_offset,
                         0x0CFC0100)
        self.assertEqual(zup_bank.RUNTIME_BANK_BASE + auxiliary.header_offset,
                         0x0CFF0000)
        expected_nested = {
            0x2C9D4: (0x201F, 0x282C,
                      "03fcc7acca9747279297d8b5bc05ebe909f628b178733447b7e407a781136a00"),
            0x402C0: (0x76E4, 0xC4A0,
                      "38166aad0a0bccb347d9f0246a4c0efd0fa8239ef2d187ccfaf0615c95d52251"),
            0x77000: (0x1378, 0x14A4,
                      "4662618a0ac730e8ff8c0c53104197425684be10540def69b18c8a6c7f812a6a"),
            0x78390: (0x1FE0, 0x24A4,
                      "d73cd25c5d4ad6e5e5b062dba4cdd1bdc5bb55fd2303f4357ce75d9cdb96076b"),
        }
        for offset, (stored_size, output_size, digest) in expected_nested.items():
            payload = zup_bank.parse_nested_payload(result.data, offset)
            self.assertEqual(
                (payload.stored_size, payload.output_size),
                (stored_size, output_size))
            self.assertEqual(hashlib.sha256(payload.data).hexdigest(), digest)
        expected_type8 = {
            0x479BC: (0, 0x483BD241, 0x5BF54,
                      "7b1770759a2f1849aef92d7b434b001c55925432cbf0eb24cc31bbff1ae85df9"),
            0x6BB60: (1, 0x100, 0x25D0,
                      "e26fbef2176d195b2abb3aae028f60a6d503dfb2b4f517ea6831cfe17a9911be"),
            0x6CBCC: (1, 0x2FBC, 0x4BC8,
                      "a91e14977a36f8d167003028a43b5cd8bdb64d8043035a1af4570785bd4797f8"),
            0x70010: (0, 0x483BD241, 0x10DEC,
                      "fd180b04f2a81a2bac363a8aff8f0eb2324d70750e9f3af562050865603c783f"),
            0x76C20: (1, 0x100, 0x590,
                      "6edec1b620431c99cc69c23b79f273c1b92c47db3c5df48a3acdb57d1bacf5e8"),
        }
        type8_payloads = {}
        for offset, (mode, field, output_size, digest) in expected_type8.items():
            payload = zup_bank.parse_type8_payload(result.data, offset)
            type8_payloads[offset] = payload
            self.assertEqual(
                (payload.mode, payload.field, payload.output_size),
                (mode, field, output_size))
            self.assertEqual(hashlib.sha256(payload.data).hexdigest(), digest)
            if mode == 0:
                self.assertEqual(payload.field,
                                 int.from_bytes(payload.data[4:8], "big"))
        initialized_spans = {
            (payload.field, payload.field + payload.output_size)
            for payload in type8_payloads.values() if payload.mode == 1
        }
        main_zero_spans = {
            (record.field1, record.field1 + record.field2 * 4)
            for record in main.records if record.record_type == 2
        }
        auxiliary_zero_spans = {
            (record.field1, record.field1 + record.field2 * 4)
            for record in auxiliary.records if record.record_type == 2
        }
        self.assertTrue({(0x100, 0x26D0), (0x2FBC, 0x7B84)}
                        <= initialized_spans)
        self.assertEqual(main_zero_spans,
                         {(0x26D0, 0x2FBC), (0x7B84, 0xC74C)})
        self.assertIn((0x100, 0x690), initialized_spans)
        self.assertEqual(auxiliary_zero_spans, {(0x690, 0x1C28)})
        for table, payload, type7_index, type3_index, code_end in (
                (main, type8_payloads[0x479BC], 24, 26, 0x686A0),
                (auxiliary, type8_payloads[0x70010], 16, 17, 0x13DEC)):
            code_start = table.records[2]
            type7 = table.records[type7_index]
            type3 = table.records[type3_index]
            self.assertEqual(
                (code_start.record_type, type7.record_type, type3.record_type),
                (9, 7, 3))
            self.assertEqual(type7.field1,
                             0x10000 + code_start.field1 // 4)
            self.assertEqual(type3.field1,
                             0x40000000 | code_start.field1 // 4)
            self.assertEqual(code_start.field1 + payload.output_size, code_end)
            self.assertLess(code_end, 0x70000)
            self.assertEqual(
                [index for index, record in enumerate(table.records)
                 if record.record_type == 3],
                [len(table.records) - 1])
        for table, pairs in ((main, ((6, 7), (13, 14), (20, 21))),
                             (auxiliary, ((6, 7), (13, 14)))):
            for type5_index, type4_index in pairs:
                type5 = table.records[type5_index]
                type4 = table.records[type4_index]
                self.assertEqual((type5.record_type, type4.record_type), (5, 4))
                self.assertEqual(type5.field1 - type4.field1, 0x10000)
        self.assertEqual(
            main.records[25].field1 * 4 - zup_bank.RUNTIME_BANK_BASE,
            0x40A00)

    @unittest.skipUnless(TRANSITION_ZUP.exists(), "needs transition .zup")
    def test_transition_package_uses_supported_map(self):
        result = zup_bank.build_bank(zup_bank.read_package(str(TRANSITION_ZUP)))
        self.assertEqual(
            hashlib.sha256(result.data).hexdigest(), TRANSITION_BANK_SHA256)
        self.assertEqual((len(result.raw_regions), len(result.compressed_regions)),
                         (1, 4))
        launch = zup_bank.parse_launch_table(result.data, 0)
        staged_launch = zup_bank.parse_launch_table(result.data, 0x40000)
        self.assertEqual((launch.table_offset, launch.record_count), (0x7B620, 15))
        self.assertEqual(staged_launch.records, launch.records)
        payload = zup_bank.parse_type8_payload(result.data, 0x4F368)
        self.assertEqual(
            (payload.mode, payload.field, payload.output_size, payload.crc32),
            (0, 0x483BD241, 0x58E68, 0x613CD603))
        self.assertEqual(
            hashlib.sha256(payload.data).hexdigest(),
            "b928d27d00fcda84769ce7dcb21e07ba3142c3cdee4da1c49ec3685cdf01c270")
        self.assertEqual(
            launch.records[6].field1 - launch.records[7].field1,
            0x10000)
        self.assertEqual(
            launch.records[13].field1 * 4 - zup_bank.RUNTIME_BANK_BASE,
            0x40020)
        self.assertEqual(
            (launch.records[2].record_type, launch.records[12].record_type,
             launch.records[14].record_type),
            (9, 7, 3))
        self.assertEqual(launch.records[12].field1,
                         0x10000 + launch.records[2].field1 // 4)
        self.assertEqual(launch.records[14].field1,
                         0x40000000 | launch.records[2].field1 // 4)
        self.assertEqual(launch.records[2].field1 + payload.output_size,
                         0x68284)
        self.assertLess(0x68284, 0x70000)
        self.assertEqual(
            [index for index, record in enumerate(launch.records)
             if record.record_type == 3],
            [len(launch.records) - 1])
        self.assertEqual(set(result.data[0x7FED4:]), {0xFF})

    @unittest.skipUnless(ATA_ZUP.exists() and TRANSITION_ZUP.exists(),
                         "needs pinned ATA packages")
    def test_packages_share_the_type8_inflate_helper_and_tables(self):
        sip = zup_bank.build_bank(zup_bank.read_package(str(ATA_ZUP))).data
        transition = zup_bank.build_bank(
            zup_bank.read_package(str(TRANSITION_ZUP))).data
        sip_launch = zup_bank.parse_launch_table(sip, 0)
        transition_launch = zup_bank.parse_launch_table(transition, 0)

        modules = []
        for bank, launch, expected_start, expected_anchor in (
                (sip, sip_launch, 0x7D000, 0xBD000),
                (transition, transition_launch, 0x79AF8, 0xB9AF8)):
            data_copy = launch.records[0]
            type5 = launch.records[6]
            type4 = launch.records[7]
            code_start = type4.field1 * 4 - zup_bank.RUNTIME_BANK_BASE
            call_anchor = type5.field1 * 4 - zup_bank.RUNTIME_BANK_BASE
            data_start = data_copy.field1 - zup_bank.RUNTIME_BANK_BASE
            data_size = data_copy.field3 * 4
            self.assertEqual((code_start, call_anchor),
                             (expected_start, expected_anchor))
            self.assertEqual((data_start - code_start, data_size),
                             (0x1968, 0x1C0))
            self.assertEqual(data_copy.field2, launch.records[3].field1)
            self.assertEqual(data_copy.field2, 0x7FC00)
            modules.append(bank[code_start:data_start + data_size])

        self.assertEqual(modules[0], modules[1])
        self.assertEqual(len(modules[0]), 0x1B28)
        self.assertEqual(
            hashlib.sha256(modules[0]).hexdigest(),
            "89f5a4005ecd81b46e66e1c9192efc451af2c963481ac7d84fe80276b02a9c40")
        helper_code = modules[0][:0x1968]
        helper_data = modules[0][0x1968:]
        self.assertEqual(
            hashlib.sha256(helper_code).hexdigest(),
            "fa18fed20b1904f8c26c1758cfb303e6d6bfc9ee2097979cda07847c11566221")
        self.assertEqual(
            hashlib.sha256(helper_data).hexdigest(),
            "be2bca1bec4b43f1fa729e77af4f0abd8912b64803f87a7b39e7c9c5323103b3")


if __name__ == "__main__":
    unittest.main()
