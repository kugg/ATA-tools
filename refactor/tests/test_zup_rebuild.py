"""Offline tests for reversible ATA package rebuilding."""

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
import zlib


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from refactor import zup_bank, zup_rebuild


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"
TRANSITION_ZUP = ARTIFACT_DIR / "transition.zup"


def raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    stream = compressor.compress(data) + compressor.flush()
    return stream + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


def synthetic_package() -> bytes:
    raw = b"RAW!"
    plain = b"compressed-test"
    stored = raw_deflate(plain)
    streams = raw + stored
    table_offset = zup_bank.INNER_HEADER_BYTES + len(streams) + 4
    table = struct.pack(
        ">HHIIIII", 1, 1, 0, len(raw), 8, len(plain), len(stored))
    table += struct.pack(">I", 2)
    inner_size = table_offset + len(table)
    inner = bytearray(
        b"+kxz" + b"\x00" * 4 + struct.pack(">II", inner_size, table_offset)
        + streams + b"ATA4" + table)
    struct.pack_into(">I", inner, 4, sum(inner[12:]) & 0xFFFFFFFF)
    outer = (b"kup1" + b"00000000" + b"\x00" * 4
             + struct.pack(">IHH", 0x301, 0x400, 0x301))
    return outer + inner


def synthetic_two_compressed_package() -> bytes:
    raw = b"RAW!"
    plains = (b"A" * 1024, b"second-stream" * 32)
    stored = tuple(raw_deflate(plain) for plain in plains)
    streams = raw + b"".join(stored)
    table_offset = zup_bank.INNER_HEADER_BYTES + len(streams) + 4
    table = struct.pack(">HHII", 1, 2, 0, len(raw))
    table += struct.pack(">III", 0x100, len(plains[0]), len(stored[0]))
    table += struct.pack(">III", 0x1000, len(plains[1]), len(stored[1]))
    table += struct.pack(">I", 2)
    inner_size = table_offset + len(table)
    inner = bytearray(
        b"+kxz" + b"\x00" * 4 + struct.pack(">II", inner_size, table_offset)
        + streams + b"ATA4" + table)
    struct.pack_into(">I", inner, 4, sum(inner[12:]) & 0xFFFFFFFF)
    outer = (b"kup1" + b"00000000" + b"\x00" * 4
             + struct.pack(">IHH", 0x301, 0x400, 0x301))
    return outer + inner


class RebuildTest(unittest.TestCase):
    def test_unchanged_package_is_byte_identical(self):
        template = synthetic_package()
        bank = zup_bank.build_bank(template).data
        result = zup_rebuild.rebuild_package(template, bank)
        self.assertEqual(result.data, template)
        self.assertEqual(
            (result.changed_raw_regions, result.recompressed_regions,
             result.preserved_compressed_regions),
            (0, 0, 1))

    def test_raw_region_change_rebuilds_to_exact_bank(self):
        template = synthetic_package()
        bank = bytearray(zup_bank.build_bank(template).data)
        bank[0] ^= 1
        result = zup_rebuild.rebuild_package(template, bytes(bank))
        self.assertNotEqual(result.data, template)
        self.assertEqual((result.changed_raw_regions, result.recompressed_regions),
                         (1, 0))
        self.assertEqual(zup_bank.build_bank(result.data).data, bytes(bank))

    def test_compressed_region_change_is_recompressed_and_checked(self):
        template = synthetic_package()
        bank = bytearray(zup_bank.build_bank(template).data)
        bank[8] ^= 1
        result = zup_rebuild.rebuild_package(template, bytes(bank))
        self.assertNotEqual(result.data, template)
        self.assertEqual((result.recompressed_regions,
                          result.preserved_compressed_regions), (1, 0))
        self.assertEqual(zup_bank.build_bank(result.data).data, bytes(bank))

    def test_unmapped_bank_change_is_rejected(self):
        template = synthetic_package()
        bank = bytearray(zup_bank.build_bank(template).data)
        bank[4] = 0
        with self.assertRaisesRegex(ValueError, "outside mapped"):
            zup_rebuild.rebuild_package(template, bytes(bank))

    def test_wrong_bank_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "512 KiB"):
            zup_rebuild.rebuild_package(synthetic_package(), b"short")

    def test_invalid_outer_name_is_rejected(self):
        template = bytearray(synthetic_package())
        bank = zup_bank.build_bank(template).data
        template[4:12] = b"\x00" * 8
        with self.assertRaisesRegex(ValueError, "name"):
            zup_rebuild.rebuild_package(bytes(template), bank)
        template[4:12] = b"bad\nname"
        with self.assertRaisesRegex(ValueError, "name"):
            zup_rebuild.rebuild_package(bytes(template), bank)

    def test_cli_diagnostic_does_not_reflect_control_characters(self):
        diagnostic = io.StringIO()
        with contextlib.redirect_stderr(diagnostic), self.assertRaises(SystemExit):
            zup_rebuild.main(["--bad\nsecret"])
        self.assertNotIn("secret", diagnostic.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            zup_rebuild.main(["--r", "template", "bank", "output"])

    def test_shifted_unchanged_stream_is_preserved_without_pinned_artifact(self):
        template = synthetic_two_compressed_package()
        original = zup_bank.build_bank(template)
        bank = bytearray(original.data)
        first = original.compressed_regions[0]
        bank[first.destination:first.destination + first.output_size] = (
            bytes(range(256)) * 4)
        result = zup_rebuild.rebuild_package(template, bytes(bank))
        rebuilt = zup_bank.build_bank(result.data)
        self.assertEqual(rebuilt.data, bytes(bank))
        self.assertEqual((result.recompressed_regions,
                          result.preserved_compressed_regions), (1, 1))
        before = original.compressed_regions[1]
        after = rebuilt.compressed_regions[1]
        self.assertNotEqual(after.source, before.source)
        self.assertEqual(
            result.data[after.source:after.source + after.stored_size],
            template[before.source:before.source + before.stored_size])

    def test_recompress_all_produces_the_same_bank(self):
        template = synthetic_package()
        bank = zup_bank.build_bank(template).data
        result = zup_rebuild.rebuild_package(
            template, bank, preserve_unchanged=False)
        self.assertEqual(result.recompressed_regions, 1)
        self.assertEqual(result.preserved_compressed_regions, 0)
        self.assertEqual(zup_bank.build_bank(result.data).data, bank)

    def test_cli_creates_private_output_without_replacement(self):
        template = synthetic_package()
        bank = zup_bank.build_bank(template).data
        with tempfile.TemporaryDirectory() as directory:
            template_path = Path(directory) / "template.zup"
            bank_path = Path(directory) / "bank.bin"
            output_path = Path(directory) / "rebuilt.zup"
            template_path.write_bytes(template)
            bank_path.write_bytes(bank)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(zup_rebuild.main([
                    str(template_path), str(bank_path), str(output_path)]), 0)
            self.assertEqual(output_path.read_bytes(), template)
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)
            self.assertIn("byte_identical_to_template=true", output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(zup_rebuild.main([
                    str(template_path), str(bank_path), str(output_path)]), 1)
            self.assertEqual(output_path.read_bytes(), template)

    @unittest.skipUnless(ATA_ZUP.exists() and TRANSITION_ZUP.exists(),
                         "needs pinned ATA packages")
    def test_pinned_packages_rebuild_byte_identically(self):
        expected = {
            ATA_ZUP: "b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5",
            TRANSITION_ZUP: "9cf97b172f4d3422dfa54ad9708a5e110637130963d9f1bc1f1e70c1bbfcc278",
        }
        for path, digest in expected.items():
            with self.subTest(path=path.name):
                template = zup_bank.read_package(str(path))
                bank = zup_bank.build_bank(template).data
                result = zup_rebuild.rebuild_package(template, bank)
                self.assertEqual(result.data, template)
                self.assertEqual(hashlib.sha256(result.data).hexdigest(), digest)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_pinned_package_can_be_fully_recompressed(self):
        template = zup_bank.read_package(str(ATA_ZUP))
        bank = zup_bank.build_bank(template).data
        result = zup_rebuild.rebuild_package(
            template, bank, preserve_unchanged=False)
        self.assertEqual(result.recompressed_regions, 7)
        self.assertEqual(result.preserved_compressed_regions, 0)
        self.assertEqual(zup_bank.build_bank(result.data).data, bank)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA package")
    def test_one_changed_region_preserves_other_encoded_streams(self):
        template = zup_bank.read_package(str(ATA_ZUP))
        original = zup_bank.build_bank(template)
        bank = bytearray(original.data)
        changed_index = 1
        bank[original.compressed_regions[changed_index].destination] ^= 1
        result = zup_rebuild.rebuild_package(template, bytes(bank))
        rebuilt = zup_bank.build_bank(result.data)
        self.assertEqual(rebuilt.data, bytes(bank))
        self.assertEqual((result.recompressed_regions,
                          result.preserved_compressed_regions), (1, 6))
        for index, (before, after) in enumerate(zip(
                original.compressed_regions, rebuilt.compressed_regions)):
            before_bytes = template[before.source:before.source + before.stored_size]
            after_bytes = result.data[after.source:after.source + after.stored_size]
            if index == changed_index:
                self.assertNotEqual(after_bytes, before_bytes)
            else:
                self.assertEqual(after_bytes, before_bytes)


if __name__ == "__main__":
    unittest.main()
