#!/usr/bin/env python3
"""Tests for firmware/cfgfmt.py.

Expected byte vectors were captured from the original ``cfgfmt.linux``
running under ``docker run --platform linux/386 i386/ubuntu:20.04``.
"""

import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from firmware import cfgfmt


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(
    os.environ.get("ATA186_TEST_ARTIFACT_DIR", ROOT / "vendor")).resolve()
PTAG = str(Path(os.environ.get(
    "ATA186_TEST_PTAG", ARTIFACT_DIR / "ptag.dat")).resolve())


def run_main(args):
    """Run cfgfmt.main capturing stdout/stderr; returns (code, out, err)."""
    import contextlib
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cfgfmt.main(args)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def _key_option(directory, value, strong=False):
    path = os.path.join(directory, "strong.key" if strong else "key")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as file:
        file.write(value + "\n")
    return f"--{'xkey' if strong else 'key'}-file={path}"


def convert_text(text, extra=(), ptag=PTAG, key=None, xkey=None):
    """Write text profile, convert, return (code, out, err, bin_bytes)."""
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "in.txt")
    dst = os.path.join(tmp, "out.bin")
    with open(src, "w") as fh:
        fh.write(text)
    options = list(extra)
    if key is not None:
        options.append(_key_option(tmp, key))
    if xkey is not None:
        options.append(_key_option(tmp, xkey, strong=True))
    code, out, err = run_main(["cfgfmt", f"-t{ptag}", *options, src, dst])
    data = b""
    if os.path.exists(dst):
        with open(dst, "rb") as fh:
            data = fh.read()
    return code, out, err, data


def convert_bin(data, extra=(), ptag=PTAG, key=None, xkey=None):
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "in.bin")
    dst = os.path.join(tmp, "out.txt")
    with open(src, "wb") as fh:
        fh.write(data)
    options = list(extra)
    if key is not None:
        options.append(_key_option(tmp, key))
    if xkey is not None:
        options.append(_key_option(tmp, xkey, strong=True))
    code, out, err = run_main(["cfgfmt", f"-t{ptag}", *options, src, dst])
    text = ""
    if os.path.exists(dst):
        with open(dst, "r") as fh:
            text = fh.read()
    return code, out, err, text


class VarintTest(unittest.TestCase):
    def test_vectors(self):
        self.assertEqual(cfgfmt.encode_varint(0x14), b"\x14")
        self.assertEqual(cfgfmt.encode_varint(0x7FFE), b"\xff\xfe")
        self.assertEqual(cfgfmt.encode_varint(0x1102), b"\x91\x02")
        self.assertEqual(cfgfmt.encode_varint(0x4000), b"\xc0\x00")
        self.assertEqual(cfgfmt.encode_varint(0x7FFF), b"\xff\xff")
        self.assertEqual(cfgfmt.encode_varint(0x80), b"\x80\x80")

    def test_roundtrip(self):
        for v in (0, 1, 0x7F, 0x80, 0x14, 0x1100, 0x2001, 0x4000, 0x7FFE):
            v2, pos = cfgfmt.decode_varint(cfgfmt.encode_varint(v), 0)
            self.assertEqual((v2, pos), (v, len(cfgfmt.encode_varint(v))))

    def test_too_big(self):
        with self.assertRaises(ValueError):
            cfgfmt.encode_varint(0x8000)


class ChecksumTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(cfgfmt.checksum_simple(b"\x14\x01\x01"), 0x16)
        self.assertEqual(
            cfgfmt.checksum_simple(bytes.fromhex("0304c0a802aa")), 0x21B)

    def test_internet_empty(self):
        self.assertEqual(cfgfmt.checksum_internet(b""), 0xFFFF)


class RC4Test(unittest.TestCase):
    def test_known_answer_from_original(self):
        # 'UseTftp:1' -> binary (14 bytes) encrypted with -eabcd by the
        # original yields these exact bytes.
        plain = bytes.fromhex("23617461fffe0400160003140101")
        rc = cfgfmt.RC4.from_hex_string("abcd")
        self.assertEqual(
            rc.crypt(plain).hex(), "27fcf464801f178a96fb373a7ae0")
        rc2 = cfgfmt.RC4.from_hex_string("abcd")
        self.assertEqual(rc2.crypt(bytes.fromhex(
            "27fcf464801f178a96fb373a7ae0")), plain)

    def test_odd_key_padding(self):
        rc = cfgfmt.RC4.from_hex_string("abc")  # -> "abc0"
        rc2 = cfgfmt.RC4.from_hex_string("abc0")
        self.assertEqual(rc.crypt(b"hello"), rc2.crypt(b"hello"))

    def test_hex_pair_matches_strtoul_0xaa_trick(self):
        # The original builds "0xAA" + pair and keeps the low byte.
        self.assertEqual(cfgfmt._hex_pair_byte("12"), 0x12)
        self.assertEqual(cfgfmt._hex_pair_byte("ab"), 0xAB)
        self.assertEqual(cfgfmt._hex_pair_byte("1g"), 0xA1)  # parse stops at 'g'
        self.assertEqual(cfgfmt._hex_pair_byte("g1"), 0xAA)  # stops immediately


class SecurityOptionsTest(unittest.TestCase):
    def test_inline_keys_are_rejected_without_echoing_them(self):
        for option in ("-e", "-x"):
            with self.subTest(option=option):
                secret = "SecretValue123"
                code, _out, error = run_main(["cfgfmt", option + secret])
                self.assertEqual(code, 1)
                self.assertIn("inline encryption keys are not accepted", error)
                self.assertNotIn(secret, error)

    def test_key_file_requires_exact_mode_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "key")
            with open(path, "w", encoding="ascii") as file:
                file.write("abcd\n")
            os.chmod(path, 0o600)
            self.assertEqual(cfgfmt._read_private_key(path, "key file"), "abcd")
            for mode in (0o400, 0o644, 0o700):
                with self.subTest(mode=oct(mode)):
                    os.chmod(path, mode)
                    with self.assertRaisesRegex(ValueError, "mode-0600"):
                        cfgfmt._read_private_key(path, "key file")

    def test_key_file_rejects_wrong_owner_symlink_and_invalid_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "key")
            with open(path, "w", encoding="ascii") as file:
                file.write("abcd\n")
            os.chmod(path, 0o600)
            real_fstat = os.fstat

            def wrong_owner(fd):
                values = list(real_fstat(fd))
                values[4] += 1
                return os.stat_result(values)

            with patch.object(cfgfmt.os, "fstat", side_effect=wrong_owner), \
                    self.assertRaisesRegex(ValueError, "mode-0600"):
                cfgfmt._read_private_key(path, "key file")
            link = os.path.join(directory, "key-link")
            os.symlink(path, link)
            with self.assertRaisesRegex(ValueError, "cannot open key file"):
                cfgfmt._read_private_key(link, "key file")
            for content in (b"abcg\n", b"\xff\n"):
                with self.subTest(content=content):
                    with open(path, "wb") as file:
                        file.write(content)
                    os.chmod(path, 0o600)
                    with self.assertRaisesRegex(ValueError, "hexadecimal"):
                        cfgfmt._read_private_key(path, "key file")

    def test_key_file_checks_actual_read_length_after_fstat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "key")
            with open(path, "wb") as file:
                file.write(b"a" * (cfgfmt.MAX_KEY_FILE_BYTES + 1))
            os.chmod(path, 0o600)
            real_fstat = os.fstat

            def stale_size(fd):
                values = list(real_fstat(fd))
                values[6] = 4
                return os.stat_result(values)

            with patch.object(cfgfmt.os, "fstat", side_effect=stale_size), \
                    self.assertRaisesRegex(ValueError, "exceeds the safe limit"):
                cfgfmt._read_private_key(path, "key file")

    def test_unknown_key_option_fails_instead_of_emitting_plaintext(self):
        code, _out, error = run_main(["cfgfmt", "--key-fil=missing"])
        self.assertEqual(code, 1)
        self.assertEqual(error, "error: unknown switch\n")

    def test_profile_keys_never_select_output_encryption_without_local_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ptag = root / "ptag.dat"
            ptag.write_text(
                "20,0x0028,UseTftp,1,0xF\n"
                "61,0x0010,EncryptKey,9,0xF\n")
            source = root / "input.txt"
            source.write_text(
                "#txt\nEncryptKey:abcd\n"
                "EncryptKeyEx:0011223344556677/020000000001\nUseTftp:1\n")
            output = root / "plain.bin"
            code, _out, error = run_main([
                "cfgfmt", f"-t{ptag}", "-E", "-X", str(source), str(output)])
            self.assertEqual(code, 0, error)
            self.assertTrue(output.read_bytes().startswith(b"#ata"))
            self.assertFalse((root / "plain.bin.x").exists())

            key = root / "key"
            key.write_text("abcd\n")
            key.chmod(0o600)
            encrypted = root / "encrypted.bin"
            code, _out, error = run_main([
                "cfgfmt", f"-t{ptag}", f"--key-file={key}",
                str(source), str(encrypted)])
            self.assertEqual(code, 0, error)
            self.assertFalse(encrypted.read_bytes().startswith(b"#ata"))

    def test_ptag_size_is_bounded_before_value_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ptag.dat")
            with open(path, "w", encoding="ascii") as file:
                file.write("1 0x400 Huge 999999999\n2 0x400 Negative -1\n")
            error = io.StringIO()
            import contextlib
            with contextlib.redirect_stderr(error):
                entries = cfgfmt.load_ptag(path)
        self.assertEqual(entries, [])
        self.assertEqual(error.getvalue().count("invalid ptag entry"), 2)

    def test_output_payload_cannot_wrap_the_format_length(self):
        with self.assertRaisesRegex(ValueError, "format limit"):
            cfgfmt._header_block(
                b"x" * (cfgfmt.MAX_FORMAT_PAYLOAD_BYTES + 1), False)
        profile = cfgfmt.ParsedProfile()
        for tag in range(1, 256):
            profile.small[tag] = (0, b"x" * cfgfmt.MAX_PTAG_VALUE_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "format limit"):
                cfgfmt.text_to_files(
                    profile, os.path.join(directory, "output"), None, False,
                    None, "", False, False, False)
            self.assertEqual(os.listdir(directory), [])

    def test_publication_rolls_back_current_link_on_validation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "first")
            second = os.path.join(directory, "second")
            real_lstat = os.lstat
            changed = False

            def changed_identity(path):
                nonlocal changed
                details = real_lstat(path)
                if path == second and not changed:
                    changed = True
                    values = list(details)
                    values[1] += 1
                    return os.stat_result(values)
                return details

            with patch.object(cfgfmt.os, "lstat", side_effect=changed_identity), \
                    self.assertRaisesRegex(ValueError, "identity changed"):
                cfgfmt._publish_private_outputs([
                    (first, b"first"), (second, b"second")])
            self.assertFalse(os.path.lexists(first))
            self.assertFalse(os.path.lexists(second))

    def test_publication_removes_a_replaced_staged_source(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "output")
            real_link = os.link

            def replace_then_link(source, destination):
                os.unlink(source)
                with open(source, "wb") as file:
                    file.write(b"replacement")
                os.chmod(source, 0o600)
                real_link(source, destination)

            with patch.object(cfgfmt.os, "link", side_effect=replace_then_link), \
                    self.assertRaisesRegex(ValueError, "identity changed"):
                cfgfmt._publish_private_outputs([(target, b"expected")])
            self.assertFalse(os.path.lexists(target))
            self.assertEqual(os.listdir(directory), [])

    def test_publication_rolls_back_base_exceptions_and_staging_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "output")
            real_link = os.link

            def link_then_interrupt(source, destination):
                real_link(source, destination)
                raise KeyboardInterrupt

            with patch.object(cfgfmt.os, "link", side_effect=link_then_interrupt), \
                    self.assertRaises(KeyboardInterrupt):
                cfgfmt._publish_private_outputs([(target, b"expected")])
            self.assertEqual(os.listdir(directory), [])

            with patch.object(cfgfmt.os, "fchmod", side_effect=KeyboardInterrupt), \
                    self.assertRaises(KeyboardInterrupt):
                cfgfmt._publish_private_outputs([(target, b"expected")])
            self.assertEqual(os.listdir(directory), [])

    def test_publication_rejects_a_group_writable_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o770)
            with self.assertRaisesRegex(ValueError, "output directory is invalid"):
                cfgfmt._publish_private_outputs([
                    (os.path.join(directory, "output"), b"expected")])

    def test_invalid_ptag_diagnostic_omits_untrusted_text(self):
        import contextlib
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ptag.dat")
            marker = "Injected\x1b[31mValue"
            with open(path, "w", encoding="latin-1") as file:
                file.write(marker + "\n")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(cfgfmt.load_ptag(path), [])
        self.assertIn("invalid ptag entry at line 1", error.getvalue())
        self.assertNotIn(marker, error.getvalue())
        self.assertNotIn("\x1b", error.getvalue())


SWEDISH = str(Path(os.environ.get(
    "ATA186_TEST_SWEDISH_PROFILE", ARTIFACT_DIR / "swedish")).resolve())


@unittest.skipUnless(os.path.exists(PTAG), "needs ptag.dat")
class EncodeVectorsTest(unittest.TestCase):
    def test_use_tftp(self):
        code, _o, e, data = convert_text("#txt\nUseTftp:1\n")
        self.assertEqual(code, 0)
        self.assertEqual(e, "")
        self.assertEqual(data.hex(), "23617461fffe0400160003140101")

    def test_static_ip(self):
        _c, _o, _e, data = convert_text("#txt\nStaticIP:192.0.2.170\n")
        self.assertEqual(
            data.hex(), "23617461fffe04017300060304c00002aa")

    def test_sip_port(self):
        _c, _o, _e, data = convert_text("#txt\nSIPPort:5060\n")
        self.assertEqual(
            data.hex(), "23617461fffe04012000064504000013c4")

    def test_tftpurl2_nul_terminated(self):
        _c, _o, _e, data = convert_text("#txt\ntftpurl2:hello\nUseTftp:1\n")
        self.assertEqual(
            data.hex(),
            "23617461fffe0402c3000c91020668656c6c6f00140101")

    def test_g_omits_sensitive(self):
        _c, _o, _e, data = convert_text(
            "#txt\nUIPassword:secret\nUseTftp:1\nUID0:1234\n", ["-g"])
        self.assertEqual(data.hex(), "23617461fffe0400160003140101")

    def test_sip_filter_drops_gateway(self):
        code, _o, e, data = convert_text(
            "#txt\nUseTftp:1\nGateway:10.0.0.1\nGkOrProxy:10.0.0.2\n",
            ["-sip"])
        self.assertEqual(code, 0)
        self.assertIn("warning: unknown attribute at line", e)
        self.assertEqual(
            data.hex(), "23617461fffe0401b8000d1401011d0831302e302e302e32")

    def test_plain_tone_exact(self):
        _c, _o, _e, data = convert_text(
            "#txt\nDialTone:2,31538,30831,1380,1740,1,0,0,1000\n")
        self.assertEqual(
            data.hex(),
            "23617461fffe0403f70018241600027b32786f056406cc000100000000"
            "03e800000000")

    def test_tone_tail_is_zeroed_after_previous_value(self):
        _c, _o, _e, data = convert_text(
            "#txt\nCallCmd:AAAAAAAAAAAAAAAAAAZZZZBBBB\n"
            "DialTone:2,31538,30831,1380,1740,1,0,0,1000\n")
        self.assertEqual(
            data.hex(),
            "23617461fffe04"
            "0b520034"
            "2416" "00027b32786f056406cc00010000000003e8" "00000000"
            "3f1a" "4141414141414141414141414141414141415a5a5a5a42424242")

    def test_omitted_sensitive_value_cannot_leak_through_a_tone_tail(self):
        _c, _o, _e, data = convert_text(
            "#txt\nUIPassword:SensitiveTailValue\n"
            "DialTone:2,31538,30831,1380,1740,1,0,0,1000\n", ["-g"])
        self.assertNotIn(b"SensitiveTailValue", data)
        self.assertIn(
            bytes.fromhex(
                "2416" "00027b32786f056406cc00010000000003e8" "00000000"),
            data)

    def test_tone_alone_zero_padded(self):
        # No previous long value: fresh (zero) scratch tail.
        _c, _o, _e, data = convert_text(
            "#txt\nDialTone:2,31538,30831,1380,1740,1,0,0,1000\n")
        self.assertTrue(data.hex().endswith(
            "2416" "00027b32786f056406cc00010000000003e8" "00000000"))

    def test_boolean_forms(self):
        _c, _o, _e, data = convert_text(
            "#txt\nUseTftp:false\nUseLoginID:False\nDhcp:0\n")
        self.assertEqual(
            data.hex(), "23617461fffe04003b00090f0100140100150100")

    def test_profile_key_is_configuration_data_not_output_encryption(self):
        code, _o, _e, data = convert_text(
            "#txt\nEncryptKey:abcd\nUseTftp:1\n")
        self.assertEqual(code, 0)
        self.assertTrue(data.startswith(b"#ata"))
        _c2, _o2, _e2, text = convert_bin(data)
        self.assertIn("UseTftp:1", text)
        self.assertIn("EncryptKey:abcd", text)

    def test_private_key_file_is_not_overridden_by_profile_key(self):
        code, _o, _e, data = convert_text(
            "#txt\nEncryptKey:ffff\nUseTftp:1\n", key="abcd")
        self.assertEqual(code, 0)
        self.assertFalse(data.startswith(b"#ata"))
        _c2, _o2, _e2, text = convert_bin(data, key="abcd")
        self.assertIn("EncryptKey:ffff", text)

    def test_profile_strong_key_does_not_create_encrypted_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "input.txt")
            output = os.path.join(directory, "output.bin")
            with open(source, "w", encoding="ascii") as file:
                file.write(
                    "#txt\nEncryptKeyEx:0011223344556677/020000000001\n"
                    "UseTftp:1\n")
            code, _out, _error = run_main([
                "cfgfmt", f"-t{PTAG}", source, output])
            self.assertEqual(code, 0)
            self.assertTrue(Path(output).read_bytes().startswith(b"#ata"))
            self.assertFalse(os.path.exists(output + ".x"))

    def test_no_profile_key_flag(self):
        _c, _o, _e, data = convert_text(
            "#txt\nEncryptKey:abcd\nUseTftp:1\n", ["-E"])
        self.assertEqual(
            data.hex(), "23617461fffe0401e100091401013d0461626364")

    def test_key_file_vector(self):
        _c, _o, _e, data = convert_text("#txt\nUseTftp:1\n", key="abcd")
        self.assertEqual(data.hex(), "27fcf464801f178a96fb373a7ae0")

    def test_upgradecode_binary(self):
        _c, _o, _e, data = convert_text(
            "#txt\nupgradecode:3,0x301,0x0400,0x0200,192.0.2.170,69,"
            "0x020514a,ata18x-v2-15-020927a.zup\n")
        self.assertEqual(
            data.hex(),
            "23617461fffe040a04002f91002c"
            "03"
            "00000301"
            "0400"
            "0200"
            "c00002aa"
            "0045"
            "0020514a"
            "6174613138782d76322d31352d303230393237612e7a7570"
            "00")

    def test_upgradecode_decode_quirk(self):
        # Original prints the IP in little-endian memory order.
        _c, _o, _e, data = convert_text(
            "#txt\nupgradecode:3,0x301,0x0400,0x0200,192.0.2.170,69,"
            "0x020514a,ata18x-v2-15-020927a.zup\n")
        _c2, _o2, _e2, text = convert_bin(data)
        self.assertIn(
            "upgradecode:3,0x00000301,0x0400,0x0200,"
            "170.2.0.192,0x0045,0x0020514a,"
            "ata18x-v2-15-020927a.zup", text)

    def test_obsolete_freq_error_path(self):
        code, _o, e, data = convert_text("#txt\nDialToneFreq:350,440\n")
        self.assertEqual(code, 0)
        self.assertIn("error: invalid tone specification", e)
        self.assertEqual(
            data.hex(),
            "23617461fffe04" "0036" "0014" "2412" + "00" * 18)

    def test_include_depth(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "a0.txt"), "w") as fh:
            fh.write("#txt\ninclude b1.txt\n")
        for i in range(1, 4):
            with open(os.path.join(tmp, f"b{i}.txt"), "w") as fh:
                fh.write(f"include b{i + 1}.txt\n")
        with open(os.path.join(tmp, "b4.txt"), "w") as fh:
            fh.write("#txt\nUseTftp:1\n")
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            code, _o, e = run_main(
                ["cfgfmt", f"-t{PTAG}",
                 os.path.join(tmp, "a0.txt"), os.path.join(tmp, "a.bin")])
        finally:
            os.chdir(old_cwd)
        self.assertEqual(code, 0)
        self.assertIn("error: include nested too deep", e)

    def test_case_insensitive(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "inc.txt"), "w") as fh:
            fh.write("#txt\nDhcp:1\n")
        src = os.path.join(tmp, "cs.txt")
        with open(src, "w") as fh:
            fh.write("#txt\nusetftp:1\nUSETFTP:1\nUseTftp:1\n"
                     "INCLUDE inc.txt\n".replace("INCLUDE inc.txt",
                                                 "INCLUDE " + os.path.join(tmp, "inc.txt")))
        dst = os.path.join(tmp, "cs.bin")
        code, _o, e = run_main(["cfgfmt", f"-t{PTAG}", src, dst])
        self.assertEqual(code, 0)
        self.assertEqual(e, "")
        with open(dst, "rb") as fh:
            _c2, _o2, _e2, text = convert_bin(fh.read())
        self.assertEqual(text, "#txt\n\nDhcp:1\nUseTftp:1\n")

    def test_unknown_binary_input(self):
        code, _o, e, _t = convert_bin(b"garbage-data-payload-12345")
        self.assertEqual(code, 1)
        self.assertIn("error: unknown or encrypted input file", e)

    def test_corrupted(self):
        _c, _o, _e, data = convert_text("#txt\nUseTftp:1\n")
        for cut in (8, 12):
            code, _o2, e2, _t2 = convert_bin(data[:cut])
            self.assertEqual(code, 1)
            self.assertIn("corrupted profile", e2)

    def test_bad_size(self):
        code, _o, e, _t = convert_bin(b"#tx")
        self.assertEqual(code, 1)
        self.assertIn("error: bad input size 3", e)

    def test_missing_ptag(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "a.txt")
        with open(src, "w") as fh:
            fh.write("#txt\nUseTftp:1\n")
        code, _o, e = run_main(
            ["cfgfmt", "-tnonexist.dat", src, os.path.join(tmp, "o.bin")])
        self.assertEqual(code, 1)
        self.assertIn("error: cannot open ptag file", e)

    def test_strong_files_created(self):
        code, _o, e, data = convert_text(
            "#txt\nUseTftp:1\n",
            xkey=("00112233445566778899aabbccddeeff"
                  "00112233445566778899aabbccddeeff"))
        self.assertEqual(code, 0)
        self.assertEqual(data.hex(), "23617461fffe0400160003140101")

    def test_strong_decrypt_roundtrip(self):
        xkey = ("00112233445566778899aabbccddeeff"
                "00112233445566778899aabbccddeeff")
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "a.txt")
        dst = os.path.join(tmp, "a.bin")
        with open(src, "w") as fh:
            fh.write("#txt\nUseTftp:1\n")
        key_option = _key_option(tmp, xkey, strong=True)
        code, _o, _e = run_main(
            ["cfgfmt", f"-t{PTAG}", key_option, src, dst])
        self.assertEqual(code, 0)
        sidecar = dst + ".x"
        self.assertTrue(os.path.exists(sidecar))
        self.assertEqual(os.path.getsize(sidecar), 18)
        with open(sidecar, "rb") as fh:
            code2, _o2, _e2, text = convert_bin(fh.read(), xkey=xkey)
        self.assertEqual(code2, 0)
        self.assertIn("UseTftp:1", text)

    def test_decode_unknown_tag(self):
        import struct as _st
        payload = bytes([0x89, 0x99, 0x01, 0xAA])
        blob = (b"#ata" + cfgfmt.encode_varint(0x7FFE)
                + cfgfmt.encode_varint(4) + _st.pack(">HH", 0, len(payload))
                + payload)
        _c, _o, _e, text = convert_bin(blob)
        self.assertEqual(text, "#txt\n\n#unknownTag: 0x999\n")

    def test_ptag_alias_decode(self):
        import struct as _st
        payload = b"\x15\x01\x01"
        blob = (b"#ata" + cfgfmt.encode_varint(0x7FFE)
                + cfgfmt.encode_varint(4)
                + _st.pack(">HH", cfgfmt.checksum_simple(payload),
                           len(payload)) + payload)
        _c, _o, _e, text = convert_bin(blob)
        self.assertIn("UseH323ID:1", text)
        _c2, _o2, _e2, text2 = convert_bin(blob, ["-sip"])
        self.assertIn("UseLoginID:1", text2)

    def test_decode_truncates_long_value(self):
        import struct as _st
        payload = b"\x1d\x28" + b"A" * 40
        blob = (b"#ata" + cfgfmt.encode_varint(0x7FFE)
                + cfgfmt.encode_varint(4)
                + _st.pack(">HH", cfgfmt.checksum_simple(payload),
                           len(payload)) + payload)
        _c, _o, e, text = convert_bin(blob)
        self.assertIn("warning: input len > known len (40>32)", e)
        # Tag 29 with no protocol filter resolves to the last ptag alias.
        self.assertIn("CA0orCM0:" + "A" * 32, text)

    def test_verbose_sum_line(self):
        _c, _o, _e, data = convert_text("#txt\nUseTftp:1\n")
        _c2, _o2, _e2, text = convert_bin(data, ["-v"])
        self.assertEqual(text, "#txt\n#sum_len:22,3\nUseTftp:1\n")

    @unittest.skipUnless(os.path.exists(SWEDISH), "needs swedish vector")
    def test_swedish_space_separated_tones(self):
        # User-supplied vector: space (not colon) separators, including an
        # unknown SITTone entry.  Byte-identical to the original.
        with open(SWEDISH) as fh:
            body = fh.read()
        code, _o, e, data = convert_text("#txt\n" + body)
        self.assertEqual(code, 0)
        self.assertIn("warning: unknown attribute at line", e)
        self.assertEqual(
            data.hex(),
            "23617461fffe041515009c2416000178ee00000f31000000010000000000"
            "00000000002516000178ee000006dd0000000007d007d000000000000026"
            "22000178ee000006dd0000000007d0177000000000000000000000000000"
            "00000000002716000178ee00000787000000001f409c4000000000000028"
            "16000178ee000006dd0000000006400fa02bc0000000002f16000177030"
            "00011210000000001e001e0078000000000")

    def test_split_files(self):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "s.txt")
        dst = os.path.join(tmp, "s.bin")
        with open(src, "w") as fh:
            fh.write("#txt\nUseTftp:1\nDisplayName0:hi\n")
        code, _o, e = run_main(
            ["cfgfmt", f"-t{PTAG}", "-split", src, dst])
        self.assertEqual(code, 0)
        self.assertIn("#i: force output binary file splitting", e)
        with open(dst, "rb") as file:
            base = file.read()
        with open(dst + ".ex", "rb") as file:
            ext = file.read()
        # Base keeps UseTftp + 0x4000 pointer; .ex holds DisplayName0.
        _c2, _o2, _e2, base_text = convert_bin(base)
        self.assertIn("UseTftp:1", base_text)
        self.assertIn("#extended:", base_text)
        _c3, _o3, _e3, ext_text = convert_bin(ext)
        self.assertIn("DisplayName0:hi", ext_text)
        self.assertNotIn("UseTftp", ext_text)

    def test_include_cannot_escape_source_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            source_dir = os.path.join(directory, "source")
            os.mkdir(source_dir)
            source = os.path.join(source_dir, "input.txt")
            escape = os.path.join(directory, "outside.txt")
            output = os.path.join(source_dir, "output.bin")
            with open(source, "w") as file:
                file.write("#txt\ninclude ../outside.txt\n")
            with open(escape, "w") as file:
                file.write("UseTftp:1\n")
            code, _out, err = run_main(["cfgfmt", f"-t{PTAG}", source, output])
            self.assertEqual(code, 1)
            self.assertIn("refused by safety checks", err)
            self.assertFalse(os.path.exists(output))

    def test_outputs_are_private_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "input.txt")
            output = os.path.join(directory, "output.bin")
            with open(source, "w") as file:
                file.write("#txt\nEncryptKey:abcd\nUseTftp:1\n")
            code, _out, err = run_main(["cfgfmt", f"-t{PTAG}", "-v", source, output])
            self.assertEqual(code, 0)
            self.assertNotIn("abcd", err)
            self.assertNotIn(output, err)
            self.assertNotIn(source, err)
            self.assertEqual(stat.S_IMODE(os.stat(output).st_mode), 0o600)
            with open(output, "rb") as file:
                original = file.read()
            code, _out, err = run_main(["cfgfmt", f"-t{PTAG}", source, output])
            self.assertEqual(code, 1)
            self.assertIn("refused by safety checks", err)
            with open(output, "rb") as file:
                self.assertEqual(file.read(), original)

    def test_rejects_an_overlong_custom_ptag_line(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "input.txt")
            ptag = os.path.join(directory, "ptag.dat")
            output = os.path.join(directory, "output.bin")
            with open(source, "w") as file:
                file.write("#txt\nUseTftp:1\n")
            with open(ptag, "w") as file:
                file.write("x" * (cfgfmt.PTAG_LINE_MAX + 1))
            code, _out, _err = run_main(["cfgfmt", f"-t{ptag}", source, output])
            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()
