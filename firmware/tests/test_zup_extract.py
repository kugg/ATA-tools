"""Offline synthetic and pinned tests for package decomposition/recomposition."""

import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from firmware import zup_bank
from firmware import zup_extract
from firmware import zup_rebuild


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
ATA_ZUP = ARTIFACT_DIR / "ATA030100SIP040211A.zup"
TRANSITION_ZUP = ARTIFACT_DIR / "transition.zup"
ATA_BANK_SHA256 = "ee2247ad3b9cbd5d711f4985cbdce220359e6edff6555d8486e119e767c8f8c6"

TYPE8_OFF = 0x1000
NESTED_OFF = 0x3000


def raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    stream = compressor.compress(data) + compressor.flush()
    return stream + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF,
                                  len(data))


def _read_payload(out_dir: str, entry: dict) -> bytes:
    with open(os.path.join(out_dir, entry["file"]), "rb") as f:
        return f.read()


def synthetic_bank() -> bytes:
    bank = bytearray(b"\xff" * zup_bank.BANK_BYTES)
    struct.pack_into(">IIII", bank, 0, 0,
                     zup_bank.RUNTIME_BANK_BASE + 0x10, 3, 0)
    struct.pack_into(">IIII", bank, 0x10, 8,
                     zup_bank.RUNTIME_BANK_BASE + 0x1000, 0, 0)
    struct.pack_into(">IIII", bank, 0x20, 2, 0, 0, 0)
    struct.pack_into(">IIII", bank, 0x30, 3, 0x40000000, 0, 0)
    struct.pack_into(">II", bank, 0x1000, 0, 0)
    plain = b"editable-payload-content"
    stored = raw_deflate(plain)
    bank[0x1008:0x1008 + len(stored)] = stored
    nested_plain = b"nested-editable"
    nested_stored = raw_deflate(nested_plain)
    header = struct.pack(">4sIIIII", b"+kbz", 2,
                         sum(nested_stored) & 0xFFFFFFFF, len(nested_stored),
                         sum(nested_plain) & 0xFFFFFFFF, len(nested_plain))
    bank[NESTED_OFF:NESTED_OFF + len(header)] = header
    bank[NESTED_OFF + 24:NESTED_OFF + 24 + len(nested_stored)] = nested_stored
    return bytes(bank)


def synthetic_package(bank: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    stream = compressor.compress(bank) + compressor.flush()
    stored = stream + struct.pack("<II", zlib.crc32(bank) & 0xFFFFFFFF,
                                  len(bank))
    table_offset = zup_bank.INNER_HEADER_BYTES + len(stored)
    table = struct.pack(">HHIII", 0, 1, 0, len(bank), len(stored))
    table += struct.pack(">I", 2)
    inner_size = table_offset + len(table)
    inner = bytearray(
        b"+kxz" + struct.pack(">II", 0, inner_size)
        + struct.pack(">I", table_offset) + stored + table)
    struct.pack_into(">I", inner, 4, sum(inner[12:]) & 0xFFFFFFFF)
    outer = (b"kup1" + b"\x00" * 12
             + struct.pack("<IHH", 0x301, 0x400, 0x301))
    return outer + inner


class ExtractTest(unittest.TestCase):
    def test_roundtrip_synthetic_is_identical(self):
        bank = synthetic_bank()
        package = synthetic_package(bank)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            self.assertIsNone(manifest["section"])
            self.assertEqual(len(manifest["launch_headers"]), 1)
            self.assertEqual(
                sorted(p["kind"] for p in manifest["payloads"]),
                ["nested", "type8"])
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            composed = zup_extract.compose_bank(
                manifest, bank_data,
                lambda entry: _read_payload(out, entry))
            self.assertEqual(composed, bank)

    def test_compose_applies_record_edit(self):
        bank = synthetic_bank()
        package = synthetic_package(bank)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            original = manifest["launch_headers"][0]["records"][0]["field1"]
            manifest["launch_headers"][0]["records"][0]["field1"] ^= 0xFF
            with open(os.path.join(out, "manifest.json"), "w",
                      encoding="utf-8") as f:
                json.dump(manifest, f)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            composed = zup_extract.compose_bank(
                manifest, bank_data,
                lambda entry: _read_payload(out, entry))
            self.assertEqual(
                struct.unpack_from(">I", composed, 0x10 + 4)[0],
                original ^ 0xFF)

    def test_compose_rejects_unknown_record_type(self):
        bank = synthetic_bank()
        package = synthetic_package(bank)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["launch_headers"][0]["records"][0]["type"] = 0xE
            with open(os.path.join(out, "manifest.json"), "w",
                      encoding="utf-8") as f:
                json.dump(manifest, f)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            with self.assertRaises(ValueError):
                zup_extract.compose_bank(
                    manifest, bank_data,
                    lambda entry: _read_payload(out, entry))

    def test_compose_rejects_wrong_record_count(self):
        bank = synthetic_bank()
        package = synthetic_package(bank)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["launch_headers"][0]["records"].pop()
            with open(os.path.join(out, "manifest.json"), "w",
                      encoding="utf-8") as f:
                json.dump(manifest, f)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            with self.assertRaises(ValueError):
                zup_extract.compose_bank(
                    manifest, bank_data,
                    lambda entry: _read_payload(out, entry))

    def test_compose_rejects_nonterminal_type3(self):
        bank = synthetic_bank()
        package = synthetic_package(bank)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["launch_headers"][0]["records"][1]["type"] = 3
            with open(os.path.join(out, "manifest.json"), "w",
                      encoding="utf-8") as f:
                json.dump(manifest, f)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            with self.assertRaises(ValueError):
                zup_extract.compose_bank(
                    manifest, bank_data,
                    lambda entry: _read_payload(out, entry))

    def test_compose_repacks_smaller_payload(self):
        bank = synthetic_bank()
        package = synthetic_package(bank)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            target = os.path.join(out, "payloads", "type8_0x1000.bin")
            with open(target, "wb") as f:
                f.write(b"tiny")
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            composed = zup_extract.compose_bank(
                manifest, bank_data,
                lambda entry: _read_payload(out, entry))
            payload = zup_bank.parse_type8_payload(composed, TYPE8_OFF)
            self.assertEqual(payload.data, b"tiny")

    def test_compose_rejects_oversize_payload(self):
        bank = synthetic_bank()
        package = synthetic_package(bank)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            big = os.urandom(0x10000)
            with self.assertRaises(ValueError):
                zup_extract.compose_bank(
                    manifest, bank_data,
                    lambda entry: big if entry["kind"] == "type8"
                    else _read_payload(out, entry))

    def test_extract_refuses_existing_directory(self):
        package = synthetic_package(synthetic_bank())
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            os.mkdir(out)
            with self.assertRaises(ValueError, msg="existing"):
                zup_extract.extract_package(package, out)

    def test_cli_extract_and_compose(self):
        package = synthetic_package(synthetic_bank())
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = os.path.join(tmpdir, "test.zup")
            with open(package_path, "wb") as f:
                f.write(package)
            out = os.path.join(tmpdir, "decomp")
            self.assertEqual(
                zup_extract.main([package_path, "--out", out]), 0)
            bank_path = os.path.join(tmpdir, "recomposed.bin")
            self.assertEqual(
                zup_extract.main(["--compose", out, "--bank", bank_path]), 0)
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                self.assertEqual(open(bank_path, "rb").read(), f.read())
            self.assertEqual(
                zup_extract.main([package_path, "--out", out]), 1)
            with self.assertRaises(SystemExit) as exited:
                zup_extract.main(["--bogus"])
            self.assertEqual(exited.exception.code, 2)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA .zup")
    def test_pinned_sip_decomposes_with_known_hashes(self):
        package = zup_bank.read_package(str(ATA_ZUP))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            self.assertEqual(manifest["bank_sha256"], ATA_BANK_SHA256)
            self.assertEqual(
                [(h["header_offset"], h["record_count"])
                 for h in manifest["launch_headers"]],
                [(0, 27), (0x40100, 27), (0x70000, 18)])
            by_offset = {p["offset"]: p for p in manifest["payloads"]}
            self.assertEqual(
                by_offset[0x479BC]["sha256"],
                "7b1770759a2f1849aef92d7b434b001c55925432cbf0eb24cc31bbff1ae85df9")
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            composed = zup_extract.compose_bank(
                manifest, bank_data,
                lambda entry: _read_payload(out, entry))
            self.assertEqual(composed, bank_data)

    @unittest.skipUnless(ATA_ZUP.exists(), "needs pinned ATA .zup")
    def test_pinned_edit_rebuilds_to_edited_bank(self):
        package = zup_bank.read_package(str(ATA_ZUP))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            original_field = None
            for header in manifest["launch_headers"]:
                if header["header_offset"] == 0x70000:
                    original_field = header["records"][13]["field1"]
                    header["records"][13]["field1"] ^= 0x04
            with open(os.path.join(out, "manifest.json"), "w",
                      encoding="utf-8") as f:
                json.dump(manifest, f)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            target = os.path.join(out, "payloads", "nested_0x78390.bin")
            with open(target, "rb") as f:
                shrunk = f.read()[:0x100]
            with open(target, "wb") as f:
                f.write(shrunk)
            composed = zup_extract.compose_bank(
                manifest, bank_data,
                lambda entry: _read_payload(out, entry))
            rebuilt = zup_rebuild.rebuild_package(package, composed)
            self.assertEqual(
                zup_bank.build_bank(rebuilt.data).data, composed)
            table = zup_bank.parse_launch_table(composed, 0x70000)
            self.assertEqual(table.records[13].field1,
                             original_field ^ 0x04)
            nested = zup_bank.parse_nested_payload(composed, 0x78390)
            self.assertEqual(nested.data, shrunk)

    @unittest.skipUnless(TRANSITION_ZUP.exists(), "needs transition .zup")
    def test_pinned_transition_roundtrip(self):
        package = zup_bank.read_package(str(TRANSITION_ZUP))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "decomp")
            manifest = zup_extract.extract_package(package, out)
            with open(os.path.join(out, "manifest.json"),
                      encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertEqual(
                [(h["header_offset"], h["record_count"])
                 for h in manifest["launch_headers"]],
                [(0, 15), (0x40000, 15)])
            with open(os.path.join(out, "bank.bin"), "rb") as f:
                bank_data = f.read()
            self.assertEqual(
                zup_extract.compose_bank(
                    manifest, bank_data,
                    lambda entry: _read_payload(out, entry)),
                bank_data)


if __name__ == "__main__":
    unittest.main()
