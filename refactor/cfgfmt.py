#!/usr/bin/env python3
"""Bounded offline converter for legacy Cisco ATA profile formats.

The retained parser supports historical ``#txt``/``#ata`` records and RC4
compatibility for migration analysis. It intentionally fails closed where the
vintage converter truncated outputs, followed arbitrary includes, or exposed
keys in verbose output. Generated files are new, private, and atomic; existing
paths are never overwritten.
"""

from __future__ import annotations

import math
import io
import os
import stat
import struct
import sys
import tempfile

VERSION = "2.3"

USAGE = """cfgfmt version 2.3
usage: cfgfmt [options] input output
options:
\t--key-file=PATH -- read Rc4Passwd from a private file
\t-E -- retained compatibility no-op; profile keys never encrypt output
\t--xkey-file=PATH -- read stronger hexadecimal Rc4Passwd from a private file
\t-X -- retained compatibility no-op; profile keys never encrypt output
\t-tPtagFile -- specify an alternate PtagFile path
\t-sip -- limit to sip protocol parameters
\t-h323 -- limit to h323 protocol parameters
\t-mgcp -- limit to mgcp procotol parameters
\t-sccp -- limit to sccp protocol parameters
\t-g -- omit sensitive parameters in old ata<mac> file
"""

MAX_INPUT = 120000
MIN_INPUT = 5
SPLIT_THRESHOLD = 0x7D1  # 2001
MAX_OUTPUT_FILES = 4
MAX_KEY_FILE_BYTES = 512
MAX_PTAG_VALUE_BYTES = 512
MAX_FORMAT_PAYLOAD_BYTES = 0xFFFF

# Slice of ptag.dat lines to fgets() width (original reads max 80 bytes).
PTAG_LINE_MAX = 0x50
# Slice of profile text lines (original fgets 0x3ff).
TEXT_LINE_MAX = 0x3FF


def _read_private_regular(path: str, maximum: int, label: str) -> bytes:
    """Read one bounded regular file without following a final symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"cannot open {label}") from error
    with os.fdopen(fd, "rb") as file:
        details = os.fstat(file.fileno())
        if not stat.S_ISREG(details.st_mode):
            raise ValueError(f"{label} is not a regular file")
        data = file.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"{label} exceeds the safe limit")
    return data


def _read_private_key(path: str, label: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        path_details = os.lstat(path)
        if not stat.S_ISREG(path_details.st_mode):
            raise OSError
        fd = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"cannot open {label}") from error
    with os.fdopen(fd, "rb") as file:
        details = os.fstat(file.fileno())
        if (details.st_dev, details.st_ino) != (path_details.st_dev,
                                                path_details.st_ino) \
                or not stat.S_ISREG(details.st_mode) \
                or details.st_uid != os.getuid() \
                or stat.S_IMODE(details.st_mode) != 0o600 \
                or details.st_size > MAX_KEY_FILE_BYTES:
            raise ValueError(f"{label} must be a bounded mode-0600 regular file")
        raw = file.read(MAX_KEY_FILE_BYTES + 1)
    if len(raw) > MAX_KEY_FILE_BYTES:
        raise ValueError(f"{label} exceeds the safe limit")
    try:
        value = raw.decode("ascii").rstrip("\r\n")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} must contain hexadecimal text") from error
    if not _is_hex_string(value):
        raise ValueError(f"{label} must contain hexadecimal text")
    return value


def _publish_private_outputs(outputs: list[tuple[str, bytes]]) -> None:
    """Publish complete, mode-0600 output files without overwriting paths."""
    if not outputs or len(outputs) > MAX_OUTPUT_FILES:
        raise ValueError("invalid output set")
    staged: list[tuple[str, str, tuple[int, int]]] = []
    temporaries: list[str] = []
    published: list[tuple[str, str, tuple[int, int]]] = []
    targets: set[str] = set()
    try:
        for path, content in outputs:
            target = os.path.abspath(path)
            if target in targets:
                raise ValueError("output paths must be distinct")
            targets.add(target)
            parent = os.path.dirname(target)
            parent_details = os.lstat(parent)
            if not stat.S_ISDIR(parent_details.st_mode) \
                    or parent_details.st_uid != os.getuid() \
                    or stat.S_IMODE(parent_details.st_mode) & 0o022:
                raise ValueError("output directory is invalid")
            if os.path.lexists(target):
                raise ValueError("refusing to overwrite an existing output")
            fd, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(target)}.", dir=parent)
            temporaries.append(temporary)
            try:
                try:
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "wb") as file:
                        fd = -1
                        file.write(content)
                        file.flush()
                        os.fsync(file.fileno())
                finally:
                    if fd != -1:
                        os.close(fd)
            except BaseException:
                raise
            details = os.lstat(temporary)
            staged.append((temporary, target, (details.st_dev, details.st_ino)))
        for temporary, target, identity in staged:
            source = os.lstat(temporary)
            if (source.st_dev, source.st_ino) != identity:
                raise ValueError("staged output identity changed")
            published.append((target, temporary, identity))
            os.link(temporary, target)
            details = os.lstat(target)
            if (details.st_dev, details.st_ino) != identity:
                raise ValueError("output publication identity changed")
    except BaseException:
        for target, temporary, identity in reversed(published):
            try:
                details = os.lstat(target)
                owned_identities = {identity}
                try:
                    source = os.lstat(temporary)
                    owned_identities.add((source.st_dev, source.st_ino))
                except OSError:
                    pass
                if (details.st_dev, details.st_ino) in owned_identities:
                    os.unlink(target)
            except OSError:
                pass
        raise
    finally:
        for temporary in temporaries:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# RC4 (FUN_08048d08 KSA + FUN_08048be4 PRGA)

def _ksa_from_key_bytes(key: bytes | bytearray) -> bytearray:
    s = bytearray(range(256))
    j = 0
    ki = 0
    n = len(key) or 1
    if not key:
        key = b"\x00"
    for i in range(256):
        j = (int(key[ki]) + int(s[i]) + j) & 0xFF
        s[i], s[j] = s[j], s[i]
        ki = (ki + 1) % n
    return s


def _ksa_from_hex_string(key_str: str) -> bytearray:
    """KSA for ``-e`` / profile ``EncryptKey`` hex-string keys.

    The original pads an odd-length key with ``'0'`` and converts each
    pair as ``strtoul("0x"+pair, 0)`` (non-hex pairs yield 0).
    """
    s = key_str
    if len(s) & 1:
        s = s + "0"
    key = bytearray()
    for i in range(0, len(s), 2):
        pair = s[i:i + 2]
        try:
            key.append(int(pair, 16))
        except ValueError:
            v = 0
            for ch in pair:
                if ch in "0123456789abcdefABCDEF":
                    v = v * 16 + int(ch, 16)
                else:
                    break
            key.append(v & 0xFF)
    if not key:
        key = bytearray(b"\x00")
    return _ksa_from_key_bytes(key)


class RC4:
    """Stateful RC4 stream matching FUN_08048be4."""

    def __init__(self, sbox: bytearray):
        self.s = bytearray(sbox)
        self.i = 0
        self.j = 0

    @classmethod
    def from_hex_string(cls, key_str: str) -> "RC4":
        return cls(_ksa_from_hex_string(key_str))

    @classmethod
    def from_bytes(cls, key: bytes | bytearray) -> "RC4":
        return cls(_ksa_from_key_bytes(bytearray(key)))

    def crypt(self, data: bytes | bytearray) -> bytes:
        s = self.s
        i = self.i
        j = self.j
        out = bytearray(len(data))
        for k, b in enumerate(data):
            i = (i + 1) & 0xFF
            j = (int(s[i]) + j) & 0xFF
            s[i], s[j] = s[j], s[i]
            out[k] = int(b) ^ int(s[(int(s[i]) + int(s[j])) & 0xFF])
        self.i = i
        self.j = j
        return bytes(out)


# ---------------------------------------------------------------------------
# varint tag/len (FUN_08049184 / FUN_080491f0)

def encode_varint(v: int) -> bytes:
    if v < 0 or v > 0x7FFF:
        raise ValueError(f"value too big: 0x{v & 0xFFFF:x}")
    if v < 0x80:
        return bytes([v])
    return bytes([((v >> 8) & 0xFF) | 0x80, v & 0xFF])


def decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    if pos >= len(buf):
        raise ValueError("truncated")
    b = buf[pos]
    pos += 1
    if b & 0x80:
        if pos >= len(buf):
            raise ValueError("truncated")
        return (((b & 0x7F) << 8) | buf[pos]), pos + 1
    return b, pos


# ---------------------------------------------------------------------------
# checksums (FUN_08049274 / FUN_080492b4)

def checksum_simple(data: bytes | bytearray) -> int:
    return sum(data) & 0xFFFF


def checksum_internet(data: bytes | bytearray) -> int:
    s = 0
    n = len(data)
    i = 0
    while i + 1 < n:
        s += (data[i] << 8) | data[i + 1]
        i += 2
    if i < n:
        s += data[i]
    while s >> 16:
        s = (s >> 16) + (s & 0xFFFF)
    return (~s) & 0xFFFF


# ---------------------------------------------------------------------------
# Fixed obfuscated constants for tag 0x1105 (FUN_0804a60c).
# .data blob at 0x0804ed60 (60 bytes): first 40 RC4'd with the last 20 as
# key, then first 20 XORed with the next 20.  Result: 4-byte plaintext
# prefix + 16-byte RC4 key guarding the inner checksum+value.

def _fixed_1105_material() -> tuple[bytes, bytes]:
    blob = bytes.fromhex(
        "b81b4566016b8ae4a3dcff80e1cf3cf16aefd381e359b255295a666f72b48cd7"
        "aaf5e0b5976df7ab37596596f43da74ab0c22faeccd4073739ad5408"
    )
    key = blob[0x28:0x28 + 0x14]
    rc = RC4(_ksa_from_key_bytes(key))
    dec = rc.crypt(blob[:0x28])
    buf = bytearray(dec + key)
    for i in range(0x14):
        buf[i] ^= buf[i + 0x14]
    return bytes(buf[:4]), bytes(buf[4:20])


_FIXED_1105_PREFIX, _FIXED_1105_RC4KEY = _fixed_1105_material()


# ---------------------------------------------------------------------------
# ptag.dat

class PtagEntry:
    __slots__ = ("tag", "fmt", "name", "size", "context")

    def __init__(self, tag: int, fmt: int, name: str, size: int, context: int):
        self.tag = tag
        self.fmt = fmt
        self.name = name
        self.size = size
        self.context = context


def _split_ptag_tokens(line: str) -> list[str]:
    """Split on comma/space/tab (original delimiters ``, \\t``)."""
    toks: list[str] = []
    cur: list[str] = []
    in_tok = False
    for ch in line:
        if ch in ", \t":
            if in_tok:
                toks.append("".join(cur))
                cur = []
                in_tok = False
        elif ch in "\r\n":
            break
        else:
            cur.append(ch)
            in_tok = True
    if in_tok:
        toks.append("".join(cur))
    return toks


def load_ptag(path: str) -> list[PtagEntry]:
    try:
        raw = _read_private_regular(path, MAX_INPUT, "ptag file")
    except ValueError:
        sys.stderr.write("error: cannot open ptag file\n")
        raise
    entries: list[PtagEntry] = []
    lineno = 0
    fp = io.StringIO(raw.decode("latin-1"))
    while True:
        chunk = fp.readline(PTAG_LINE_MAX + 1)
        if chunk == "":
            break
        lineno += 1
        if len(chunk) > PTAG_LINE_MAX:
            raise ValueError("ptag line exceeds the safe limit")
        if not chunk or chunk[0] in "#\n\r":
            continue
        toks = _split_ptag_tokens(chunk)
        ok = False
        if len(toks) >= 4:
            try:
                tag = int(toks[0], 0)
                fmt = int(toks[1], 0)
                name = toks[2][:0x1F]
                size = int(toks[3], 0)
                ctx = int(toks[4], 0) if len(toks) >= 5 else 0xFFFF
                if name and 1 <= size <= MAX_PTAG_VALUE_BYTES:
                    entries.append(PtagEntry(tag, fmt, name, size, ctx))
                    ok = True
            except ValueError:
                ok = False
        if not ok:
            sys.stderr.write(f"warning: invalid ptag entry at line {lineno}\n")
    return entries


# ---------------------------------------------------------------------------
# value codecs

def _is_hex_string(s: str) -> bool:
    return len(s) > 0 and all(c in "0123456789abcdefABCDEF" for c in s)


def warn_nonhex(msg: str) -> None:
    sys.stderr.write(
        f"WARNING: {msg}!\n"
        " !!! Using non-Hex characters will reduce the strength of profile encryption !!!\n"
    )


def hex_decode_even(s: str, nbytes: int) -> bytes:
    """FUN_08049670: hex chars to bytes, odd tail pads the low nibble."""
    out = bytearray(nbytes)
    pos = 0
    high = True
    for ch in s:
        if pos >= nbytes:
            break
        if ch == "\x00":
            break
        if "0" <= ch <= "9":
            v = ord(ch) - 0x30
        elif "a" <= ch <= "f":
            v = ord(ch) - ord("a") + 10
        elif "A" <= ch <= "F":
            v = ord(ch) - ord("A") + 10
        else:
            v = 0
        if high:
            out[pos] = (v << 4) & 0xF0
        else:
            out[pos] |= v & 0x0F
            pos += 1
        high = not high
    if not high:
        pos += 1
    return bytes(out)


def bytes_to_hex(b: bytes | bytearray) -> str:
    return "".join(f"{x:02x}" for x in b)


def parse_ipv4(s: str) -> bytes | None:
    if s == "0":
        return b"\x00\x00\x00\x00"
    parts = s.split(".")
    if len(parts) != 4:
        return None
    try:
        vals = [int(p, 0) for p in parts]
    except ValueError:
        return None
    if any(v < 0 or v > 255 for v in vals):
        return None
    return bytes(vals)


def format_ipv4(b: bytes | bytearray) -> str:
    return ".".join(str(x) for x in bytes(b[:4]))


def parse_extended_ip(s: str, want: int) -> bytes | None:
    if s == "0":
        if want == 5:
            want = 6
        return b"\x00" * want
    head, sep, tail = s.rpartition(".")
    if not sep:
        return None
    hparts = head.split(".")
    if len(hparts) != 4:
        return None
    try:
        octs = [int(p, 0) for p in hparts]
        port = int(tail, 0)
    except ValueError:
        return None
    if any(o < 0 or o > 255 for o in octs) or port < 0 or port > 65535:
        return None
    return bytes(octs) + struct.pack(">H", port)


def format_extended_ip(b: bytes | bytearray) -> str:
    b = bytes(b)
    if len(b) < 6:
        return ".".join(str(x) for x in b)
    return ".".join(str(x) for x in b[:4]) + f".{(b[4] << 8) | b[5]}"


def c_round_half_away(x: float) -> int:
    if x >= 0:
        return int(math.floor(x + 0.5))
    return int(math.ceil(x - 0.5))


def tone_pair(freq_s: str, gain_s: str) -> tuple[int, int]:
    """FUN_08049abc: (freq, gain) strings to an (I, Q) int16 pair.

    Constants from .rodata: gain clamped to [-60, 10], freq to [0, 4000],
    ``w = 2*PI*freq/8000``, ``amp = 10^(0.05*(gain-10))``,
    ``I = 32768*cos(w)``, ``Q = 32768*amp*sin(w)``.
    """
    try:
        freq = float(freq_s)
    except ValueError:
        freq = 0.0
    try:
        gain = float(gain_s)
    except ValueError:
        gain = 0.0
    if math.isnan(freq) or freq > 4000.0:
        freq = 4000.0
    elif freq < 0.0:
        freq = 0.0
    if math.isnan(gain) or gain > 10.0:
        gain = 10.0
    elif gain < -60.0:
        gain = -60.0
    w = (6.28318530717958 * freq) / 8000.0
    amp = pow(10.0, 0.05 * (gain - 10.0))
    i_val = c_round_half_away(32768.0 * math.cos(w))
    q_val = c_round_half_away(32768.0 * amp * math.sin(w))
    return max(-0x8000, min(0x7FFF, i_val)), max(-0x8000, min(0x7FFF, q_val))


def _split_value_list(s: str) -> list[str]:
    """Split a value on comma/space (original delimiters ``, ``)."""
    toks: list[str] = []
    cur: list[str] = []
    in_tok = False
    for ch in s:
        if ch in ", ":
            if in_tok:
                toks.append("".join(cur))
                cur = []
                in_tok = False
        elif ch in "\r\n":
            break
        else:
            cur.append(ch)
            in_tok = True
    if in_tok:
        toks.append("".join(cur))
    return toks


def encode_value(entry: PtagEntry, value: str, scratch: bytearray) -> bytes | None:
    """Encode one text value without retaining data from earlier fields."""
    fmt = entry.fmt
    want = entry.size
    if fmt & 0x20:  # boolean (case-insensitive "false"/"0" -> 0)
        scratch[0] = 0 if (value.lower() == "false" or value == "0") else 1
        return bytes(scratch[:1])
    if fmt & 0x02:  # IPv4
        b = parse_ipv4(value)
        if b is None:
            return None
        scratch[:4] = b
        return bytes(scratch[:4])
    if fmt & 0x400:  # hex-decoded fixed bytes
        scratch[:want] = hex_decode_even(value, want)
        return bytes(scratch[:want])
    if fmt & 0x80:  # extended IP
        b = parse_extended_ip(value, want)
        if b is None:
            return None
        if len(b) < want:
            b = b + b"\x00" * (want - len(b))
        b = b[:want]
        scratch[: len(b)] = b
        return bytes(scratch[: len(b)])
    if fmt & 0x04:  # 32-bit integer
        try:
            v = int(value, 0)
        except ValueError:
            return None
        if fmt & 0x200:
            scratch[:4] = struct.pack(">I", v & 0xFFFFFFFF)
        else:
            try:
                scratch[:4] = struct.pack(">i", v)
            except struct.error:
                return None
        return bytes(scratch[:4])
    if fmt & 0x100:  # obsolete tone-frequency form (float DSP)
        return _encode_obsolete_tone(value, want, scratch)
    if fmt & 0x40:  # zero-padded fixed array of shorts
        scratch[:want] = b"\x00" * want
        toks = _split_value_list(value)
        pos = 0
        for t in toks:
            if pos + 2 > want:
                break
            try:
                v = int(t, 0) & 0xFFFF
            except ValueError:
                return None
            scratch[pos:pos + 2] = struct.pack(">H", v)
            pos += 2
        return bytes(scratch[:want])
    if fmt & 0x18:  # alphanumeric string (strcpy + NUL, length w/o NUL)
        raw = value.encode("latin-1")
        if len(raw) + 1 > len(scratch):
            # Divergence: the original smashes its 512-byte stack buffer
            # here (observed SIGSEGV); store the value safely instead.
            return raw
        scratch[: len(raw)] = raw
        scratch[len(raw):len(raw) + 1] = b"\x00"
        return bytes(scratch[: len(raw)])
    raw = value.encode("latin-1")
    if len(raw) > len(scratch):
        return raw
    scratch[: len(raw)] = raw
    return bytes(scratch[: len(raw)])


def _encode_obsolete_tone(value: str, want: int,
                          scratch: bytearray) -> bytes | None:
    """Float tone form for obsolete ``*Freq`` aliases.

    Grammar: ``count,freq,gain,...(2 per segment, max 2 segments),
    t1,t2,t3,t4``.  Failures print the original error and store zeros.
    """
    toks = _split_value_list(value)

    def fail() -> bytes:
        sys.stderr.write("error: invalid tone specification\n")
        scratch[:want] = b"\x00" * want
        return bytes(scratch[:want])

    if not toks:
        return fail()
    try:
        nseg = int(toks[0], 0)
    except ValueError:
        return fail()
    if nseg < 0:
        return fail()
    if nseg > 2:
        nseg = 2
    if len(toks) < 1 + nseg * 2 + 4:
        return fail()
    out = bytearray()
    out += struct.pack(">H", nseg & 0xFFFF)
    idx = 1
    for _ in range(nseg):
        i_val, q_val = tone_pair(toks[idx], toks[idx + 1])
        out += struct.pack(">h", i_val)
        out += struct.pack(">h", q_val)
        idx += 2
    while len(out) < want and idx < len(toks):
        try:
            v = int(toks[idx], 0) & 0xFFFF
        except ValueError:
            return fail()
        out += struct.pack(">H", v)
        idx += 1
    if len(out) < want:
        out += b"\x00" * (want - len(out))
    out = out[:want]
    scratch[:want] = out
    return bytes(scratch[:want])


def decode_value(fmt: int, data: bytes) -> str:
    """FUN_0804c4b4: binary value to text."""
    if fmt & 0x20:
        if not data or data[0] == 0:
            return "0"
        return "1"
    if fmt & 0x02:
        return format_ipv4(data[:4])
    if fmt & 0x80:
        return format_extended_ip(data[:6] if len(data) >= 6 else data)
    if fmt & 0x04:
        if len(data) < 4:
            return "uimp"
        if fmt & 0x200:
            return f"0x{struct.unpack('>I', data[:4])[0]:08x}"
        return str(struct.unpack(">i", data[:4])[0])
    if fmt & 0x400:
        return bytes_to_hex(data)
    if fmt & 0x40:
        return ",".join(
            str((data[i] << 8) | data[i + 1]) for i in range(0, len(data) - 1, 2)
        )
    if fmt & 0x18:
        return data.split(b"\x00", 1)[0].decode("latin-1")
    return "uimp"


# ---------------------------------------------------------------------------
# text profile parsing (FUN_0804ab4c)

class ParsedProfile:
    def __init__(self) -> None:
        # small tags (<0xff): tag -> (fmt, value)
        self.small: dict[int, tuple[int, bytes]] = {}
        # pseudo tags: insertion-ordered (tag, fmt, value)
        self.pseudo: list[tuple[int, int, bytes]] = []
        # Shared bounded value scratch; fixed-size encoders clear their output.
        self.scratch = bytearray(512)


def _find_ptag_by_name(
    entries: list[PtagEntry], name: str, filt: int
) -> PtagEntry | None:
    lname = name.lower()
    for e in entries:
        if e.name.lower() == lname and (e.context & filt):
            return e
    return None


def _split_name_value(line: str) -> tuple[str, str] | None:
    """Split ``Name[: ]Value`` on delimiter runs (``:``/space/tab).

    The original tokenizer treats ``:``, space and tab uniformly, so
    ``include file`` (no colon) works like ``include: file`` and
    attribute values keep trailing spaces (only CR/LF terminate).
    """
    body = line.rstrip("\r\n")
    i, n = 0, len(body)
    while i < n and body[i] in ": \t":
        i += 1
    j = i
    while j < n and body[j] not in ": \t\r\n":
        j += 1
    name = body[i:j]
    if not name:
        return None
    k = j
    while k < n and body[k] in ": \t":
        k += 1
    return name, body[k:]


def _safe_include_path(root_dir: str, current_path: str, token: str) -> str:
    candidate = token if os.path.isabs(token) else os.path.join(
        os.path.dirname(current_path), token)
    candidate = os.path.abspath(candidate)
    root_real = os.path.realpath(root_dir)
    candidate_real = os.path.realpath(candidate)
    try:
        inside_root = os.path.commonpath((root_real, candidate_real)) == root_real
    except ValueError:
        inside_root = False
    if not inside_root:
        raise ValueError("included profile escapes the source directory")
    try:
        details = os.lstat(candidate)
    except OSError as error:
        raise ValueError("cannot open included profile") from error
    if not stat.S_ISREG(details.st_mode):
        raise ValueError("included profile is not a regular file")
    return candidate


def parse_text_profile(
    text_path: str,
    fp,
    entries: list[PtagEntry],
    filt: int,
    depth: int = 0,
    profile: ParsedProfile | None = None,
    root_dir: str | None = None,
    budget: list[int] | None = None,
) -> ParsedProfile:
    if profile is None:
        profile = ParsedProfile()
    if root_dir is None:
        root_dir = os.path.dirname(os.path.abspath(text_path))
    if budget is None:
        budget = [0]
    lineno = 0
    while True:
        line = fp.readline(TEXT_LINE_MAX + 1)
        if line == "":
            break
        lineno += 1
        budget[0] += len(line)
        if budget[0] > MAX_INPUT:
            raise ValueError("profile input exceeds the safe limit")
        if len(line) > TEXT_LINE_MAX:
            raise ValueError("profile line exceeds the safe limit")
        if not line or line[0] == "#":
            continue
        nv = _split_name_value(line)
        if nv is None:
            continue
        name, value = nv
        lname = name.lower()
        if lname == "include":
            if depth >= 3:
                sys.stderr.write("error: include nested too deep\n")
                continue
            inc_tok = value.split()[0] if value.split() else ""
            if not inc_tok:
                continue
            try:
                include_path = _safe_include_path(root_dir, text_path, inc_tok)
                with open(include_path, "r", encoding="latin-1", newline=None) as inc_fp:
                    parse_text_profile(
                        include_path, inc_fp, entries, filt, depth + 1, profile,
                        root_dir, budget,
                    )
            except OSError as error:
                raise ValueError("cannot open included profile") from error
            continue
        if lname in ("upgradecode", "upgradelang"):
            _parse_upgrade_code(profile, name, value)
            continue
        if lname in ("upgradelogo", "upgradexml"):
            _parse_upgrade_logo(profile, name, value)
            continue
        if lname == "tftpurl2":
            _store_pseudo(profile, 0x1102, 0, value.encode("latin-1") + b"\x00")
            continue
        if lname == "encryptkeyex":
            _parse_encrypt_key_ex(profile, value)
            continue
        entry = _find_ptag_by_name(entries, name, filt)
        if entry is None:
            sys.stderr.write(f"warning: unknown attribute at line {lineno}\n")
            continue
        if value == "":
            sys.stderr.write(f"warning: empty attribute value at line {lineno}\n")
            continue
        enc = encode_value(entry, value, profile.scratch)
        if enc is None:
            sys.stderr.write(f"warning: unknown attribute at line {lineno}\n")
            continue
        if entry.tag < 0xFF:
            profile.small[entry.tag] = (entry.fmt, enc)
        else:
            _store_pseudo(profile, entry.tag, entry.fmt, enc)
    return profile


def _store_pseudo(profile: ParsedProfile, tag: int, fmt: int, value: bytes) -> None:
    for i, (t, _f, _) in enumerate(profile.pseudo):
        if t == tag:
            profile.pseudo[i] = (tag, fmt, bytes(value))
            return
    if len(profile.pseudo) >= 0xFF:
        sys.stderr.write("warning: too many pseudo parameter.\n")
        return
    profile.pseudo.append((tag, fmt, bytes(value)))


def _parse_upgrade_code(profile: ParsedProfile, name: str, value: str) -> None:
    toks = [t for t in _split_value_list(value) if t != ""]
    if len(toks) != 8:
        sys.stderr.write("error: bad argument for upgrade tag\n")
        return
    try:
        n = int(toks[0], 0) & 0xFF
        a = int(toks[1], 0) & 0xFFFFFFFF
        b = int(toks[2], 0) & 0xFFFF
        c = int(toks[3], 0) & 0xFFFF
        port = int(toks[5], 0) & 0xFFFF
        f = int(toks[6], 0) & 0xFFFFFFFF
    except ValueError:
        sys.stderr.write("error: bad argument for upgrade tag\n")
        return
    ip = parse_ipv4(toks[4])
    if ip is None:
        sys.stderr.write("error: invalid tftp IP address\n")
        return
    tag = 0x1100 if name.lower() == "upgradecode" else 0x1101
    buf = bytearray()
    buf.append(n)
    buf += struct.pack(">I", a)
    buf += struct.pack(">H", b)
    buf += struct.pack(">H", c)
    buf += ip
    buf += struct.pack(">H", port)
    buf += struct.pack(">I", f)
    buf += toks[7].encode("latin-1")[:0x1F] + b"\x00"
    _store_pseudo(profile, tag, 0, bytes(buf))


def _parse_upgrade_logo(profile: ParsedProfile, name: str, value: str) -> None:
    toks = [t for t in _split_value_list(value) if t != ""]
    if len(toks) != 3:
        sys.stderr.write("error: bad argument for upgradelogo tag\n")
        return
    try:
        a = int(toks[0], 0) & 0xFFFFFFFF
    except ValueError:
        sys.stderr.write("error: bad argument for upgradelogo tag\n")
        return
    ip = parse_ipv4(toks[1])
    if ip is None:
        ip = toks[1].encode("latin-1")[:4].ljust(4, b"\x00")
    tag = 0x1103 if name.lower() == "upgradelogo" else 0x1104
    buf = struct.pack(">I", a) + ip + toks[2].encode("latin-1")[:0x7F] + b"\x00"
    _store_pseudo(profile, tag, 0, buf)


def _parse_encrypt_key_ex(profile: ParsedProfile, value: str) -> None:
    # Delimiters '/ \\t' (NOT comma): key[ sep]mac.
    parts: list[str] = []
    cur: list[str] = []
    in_tok = False
    for ch in value:
        if ch in "/ \t":
            if in_tok:
                parts.append("".join(cur))
                cur = []
                in_tok = False
        elif ch in "\r\n":
            break
        else:
            cur.append(ch)
            in_tok = True
    if in_tok:
        parts.append("".join(cur))
    key_s = parts[0] if parts else ""
    mac_s = parts[1] if len(parts) > 1 else ""
    if mac_s:
        mac = hex_decode_even(mac_s, 6)
    else:
        mac = b"\x00" * 6
    if not _is_hex_string(key_s):
        warn_nonhex("EncryptKeyEx in input text profile must all be Hex characters")
    key = hex_decode_even(key_s, 0x20)
    _store_pseudo(profile, 0x1105, 0, mac + key)


# ---------------------------------------------------------------------------
# binary building (FUN_0804b79c)

def _wrap_1105(value: bytes) -> bytes:
    inner = (bytes(value) + b"\x00" * 0x26)[:0x26]
    csum = checksum_internet(inner)
    plain = _FIXED_1105_PREFIX + struct.pack(">H", csum) + inner
    enc_tail = RC4.from_bytes(_FIXED_1105_RC4KEY).crypt(plain[4:])
    return plain[:4] + enc_tail


def build_records(
    profile: ParsedProfile,
    omit_sensitive: bool,
    for_extended: bool,
    is_split: bool,
) -> bytes:
    out = bytearray()
    for tag, fmt, val in profile.pseudo:
        if omit_sensitive and (fmt & 0x4000):
            continue
        if is_split:
            if not for_extended and (fmt & 0x8000):
                continue
            if for_extended and not (fmt & 0x8000):
                continue
        if tag == 0x1105:
            wrapped = _wrap_1105(val)
            out += encode_varint(tag) + encode_varint(len(wrapped)) + wrapped
        else:
            out += encode_varint(tag) + encode_varint(len(val)) + bytes(val)
    for tag in sorted(profile.small):
        fmt, val = profile.small[tag]
        if omit_sensitive and (fmt & 0x4000):
            continue
        if is_split:
            if not for_extended and (fmt & 0x8000):
                continue
            if for_extended and not (fmt & 0x8000):
                continue
        out += encode_varint(tag) + encode_varint(len(val)) + bytes(val)
    return bytes(out)


def _header_block(payload: bytes, strong: bool) -> bytes:
    if len(payload) > MAX_FORMAT_PAYLOAD_BYTES:
        raise ValueError("profile payload exceeds the format limit")
    csum = checksum_internet(payload) if strong else checksum_simple(payload)
    return (
        encode_varint(0x7FFE)
        + encode_varint(4)
        + struct.pack(">H", csum)
        + struct.pack(">H", len(payload))
    )


def _encrypted_name_line(verbose: bool, _filename: str, _keytext: str) -> None:
    if verbose:
        sys.stderr.write("i: encrypting output with <redacted>\n")


def text_to_files(
    profile: ParsedProfile,
    output: str,
    encrypt_key_text: str | None,
    encrypt_output: bool,
    strong_key: bytes | None,
    strong_key_text: str,
    omit_sensitive: bool,
    force_split: bool,
    verbose: bool,
    rand8: bytes | None = None,
) -> None:
    # Size estimate decides splitting (payload + header slop vs 2001).
    est = 8
    tmp = build_records(profile, omit_sensitive, False, False)
    est += len(tmp) + 4 * (len(profile.pseudo) + len(profile.small))
    is_split = force_split or est >= SPLIT_THRESHOLD
    out_ex = output + ".ex"
    if is_split:
        if force_split:
            sys.stderr.write("#i: force output binary file splitting\n")
        else:
            sys.stderr.write("#i: output binary file too big\n")
        sys.stderr.write("#i: splitting output binary file into 2 files\n")
    n_passes = 2 if strong_key is not None else 1
    outputs: list[tuple[str, bytes]] = []
    for pass_idx in range(n_passes):
        n_files = 2 if is_split else 1
        for file_idx in range(n_files):
            for_extended = file_idx == 1
            if pass_idx > 0:
                disk_name = output + (".x" if file_idx == 0 else ".xex")
                log_name = disk_name
                second_name = output + ".xex"
            elif is_split:
                # Original quirk: the first file is already open under
                # `output`, but the message names the `.ex` path.
                disk_name = output if file_idx == 0 else out_ex
                log_name = out_ex
                second_name = out_ex
            else:
                disk_name = log_name = output
                second_name = ""
            if verbose:
                sys.stderr.write("i: generating output file\n")
            fh = io.BytesIO()
            _write_one_file(
                fh, profile, omit_sensitive, is_split, for_extended,
                pass_idx, second_name, encrypt_key_text, encrypt_output,
                strong_key, strong_key_text, verbose, rand8, log_name,
            )
            outputs.append((disk_name, fh.getvalue()))
    _publish_private_outputs(outputs)


def _write_one_file(
    fh,
    profile: ParsedProfile,
    omit_sensitive: bool,
    is_split: bool,
    for_extended: bool,
    pass_idx: int,
    second_name: str,
    encrypt_key_text: str | None,
    encrypt_output: bool,
    strong_key: bytes | None,
    strong_key_text: str,
    verbose: bool,
    rand8: bytes | None,
    log_name: str,
) -> None:
    buf = bytearray()
    if pass_idx == 0:
        buf += b"#ata"
    payload = build_records(profile, omit_sensitive, for_extended, is_split)
    if is_split and not for_extended:
        # Extended-file pointer appended after all TLVs (tag 0x4000).
        payload += (
            encode_varint(0x4000)
            + encode_varint(len(second_name) + 1)
            + second_name.encode("latin-1")
            + b"\x00"
        )
    strong = pass_idx > 0
    buf += _header_block(payload, strong)
    buf += payload
    if pass_idx == 0:
        if encrypt_key_text is not None and encrypt_output:
            _encrypted_name_line(verbose, log_name, encrypt_key_text)
            buf = bytearray(RC4.from_hex_string(encrypt_key_text).crypt(bytes(buf)))
    else:
        assert strong_key is not None
        if rand8 is None:
            rand8 = os.urandom(8)
        else:
            rand8 = bytes(rand8[:8])
        masked = bytes(b ^ rand8[i & 7] for i, b in enumerate(bytes(buf)))
        if verbose:
            sys.stderr.write("i: encrypting output with <redacted>\n")
        buf = bytearray(
            RC4.from_bytes(strong_key).crypt(masked + rand8)
        )
    fh.write(bytes(buf))


# ---------------------------------------------------------------------------
# binary decoding (FUN_0804c70c + FUN_0804a728)

def _lookup_by_tag(
    entries: list[PtagEntry], tag: int, filt: int
) -> PtagEntry | None:
    # Original prepends each ptag line: last matching line wins.
    for e in reversed(entries):
        if e.tag == tag and (e.context & filt):
            return e
    return None


def decode_upgrade_code(value: bytes) -> str:
    if len(value) < 0x14:
        return f"#bad len: tag 0x1100, len 0x{len(value):x}"
    n = value[0]
    a = struct.unpack(">I", value[1:5])[0]
    b = struct.unpack(">H", value[5:7])[0]
    c = struct.unpack(">H", value[7:9])[0]
    ip = value[9:13]
    # Reproduces the original LE memory-order display quirk.
    ip_s = f"{ip[3]}.{ip[2]}.{ip[1]}.{ip[0]}"
    port = struct.unpack(">H", value[13:15])[0]
    f = struct.unpack(">I", value[15:19])[0]
    name = value[19:].split(b"\x00", 1)[0].decode("latin-1")
    return (
        f"upgradecode:{n},0x{a:08x},0x{b:04x},0x{c:04x},"
        f"{ip_s},0x{port:04x},0x{f:08x},{name}"
    )


def decode_upgrade_lang(value: bytes) -> str:
    s = decode_upgrade_code(value)
    if s.startswith("#bad len"):
        return s.replace("0x1100", "0x1101")
    return "upgradelang" + s[len("upgradecode"):]


def decode_upgrade_logo(value: bytes, kind: str) -> str:
    if len(value) < 9:
        return f"#bad len: tag 0x{0x1103 if kind == 'logo' else 0x1104:x}, len 0x{len(value):x}"
    a = struct.unpack(">I", value[:4])[0]
    ip = value[4:8]
    # Same LE memory-order display quirk as upgradecode.
    ip_s = f"{ip[3]}.{ip[2]}.{ip[1]}.{ip[0]}"
    name = value[8:].split(b"\x00", 1)[0].decode("latin-1")
    return f"upgrade{kind}:0x{a:08x},{ip_s},{name}"


def decode_pseudo(tag: int, value: bytes, verbose: bool) -> str:
    if tag == 0x7FFE:
        if not verbose:
            return ""
        if len(value) < 4:
            return ""
        csum = struct.unpack(">H", value[:2])[0]
        ln = struct.unpack(">H", value[2:4])[0]
        return f"#sum_len:{csum},{ln}"
    if tag in (0x1100, 0x1101):
        s = decode_upgrade_code(value) if tag == 0x1100 else decode_upgrade_lang(value)
        return s
    if tag in (0x1103, 0x1104):
        return decode_upgrade_logo(value, "logo" if tag == 0x1103 else "xml")
    if tag == 0x1102:
        return "tftpurl2:" + value.split(b"\x00", 1)[0].decode("latin-1")
    if tag == 0x1105:
        return "#EncryptKeyEx:<secret>\n"
    if tag == 0x4000:
        return "#extended:" + value.split(b"\x00", 1)[0].decode("latin-1")
    return f"#unknownTag: 0x{tag:x}"


def binary_to_text(
    payload: bytes, out_fh, entries: list[PtagEntry], filt: int, verbose: bool
) -> bool:
    out_fh.write("#txt\n")
    pos = 0
    n = len(payload)
    while True:
        if n - pos < 1:
            return True
        try:
            tag, pos = decode_varint(payload, pos)
        except ValueError:
            break
        try:
            ln, pos = decode_varint(payload, pos)
        except ValueError:
            break
        if ln < 0 or pos + ln > n:
            break
        val = payload[pos:pos + ln]
        pos += ln
        entry = _lookup_by_tag(entries, tag, filt)
        if entry is not None:
            if len(val) > entry.size:
                sys.stderr.write(
                    f"warning: input len > known len ({len(val)}>{entry.size})\n"
                )
                val = val[: entry.size]
            out_fh.write(f"{entry.name}:{decode_value(entry.fmt, val)}\n")
        else:
            out_fh.write(decode_pseudo(tag, val, verbose) + "\n")
    sys.stderr.write("corrupted profile\n")
    return False


# ---------------------------------------------------------------------------
# driver

def parse_options(argv: list[str]) -> dict:
    st: dict = {
        "cl_key": None,       # private key-file text
        "verbose": False,     # -v
        "cl_xkey": None,      # private xkey-file decoded to 32 bytes
        "omit": False,        # -g
        "ptag": "ptag.dat",   # -t
        "split": False,       # -split
        "filt": 0,            # protocol mask
        "positionals": [],
    }
    for arg in argv[1:]:
        if arg.startswith("-"):
            if arg.startswith("--key-file="):
                if st["cl_key"] is not None:
                    raise ValueError("encryption key file may be specified only once")
                st["cl_key"] = _read_private_key(
                    arg.split("=", 1)[1], "encryption key file")
            elif arg.startswith("--xkey-file="):
                if st["cl_xkey"] is not None:
                    raise ValueError("strong encryption key file may be specified only once")
                key = _read_private_key(
                    arg.split("=", 1)[1], "strong encryption key file")
                st["cl_xkey"] = hex_decode_even(key, 0x20)
            elif arg.startswith("-e") or arg.startswith("-x"):
                raise ValueError("inline encryption keys are not accepted")
            elif arg.startswith("-v"):
                st["verbose"] = True
            elif arg.startswith("-E"):
                pass
            elif arg.startswith("-X"):
                pass
            elif arg.startswith("-g"):
                st["omit"] = True
            elif arg.startswith("-t"):
                st["ptag"] = arg[2:]
            elif arg.startswith("-split"):
                st["split"] = True
            elif arg.startswith("-h323"):
                st["filt"] |= 1
            elif arg.startswith("-sip"):
                st["filt"] |= 2
            elif arg.startswith("-mgcp"):
                st["filt"] |= 4
            elif arg.startswith("-sccp"):
                st["filt"] |= 8
            else:
                raise ValueError("unknown switch")
        else:
            st["positionals"].append(arg)
    return st


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    try:
        st = parse_options(argv)
    except ValueError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    if len(st["positionals"]) != 2:
        sys.stdout.write(USAGE)
        return 1
    filt = st["filt"] or 0xFFFF
    try:
        entries = load_ptag(st["ptag"])
    except ValueError:
        return 1
    in_path, out_path = st["positionals"]
    try:
        raw = _read_private_regular(in_path, MAX_INPUT, "input profile")
    except ValueError:
        sys.stderr.write("error: cannot open input profile\n")
        return 1
    if len(raw) < MIN_INPUT:
        sys.stderr.write(f"error: bad input size {len(raw)}\n")
        return 1
    magic = raw[:4]
    if magic == b"#txt":
        try:
            profile = parse_text_profile(
                os.path.abspath(in_path), io.StringIO(raw.decode("latin-1")),
                entries, filt,
            )
            enc_text = st["cl_key"]
            # Profile key fields remain configuration data; only a private key
            # file may select converter-side encryption.
            strong = st["cl_xkey"]
            text_to_files(
                profile, out_path, enc_text, enc_text is not None,
                strong, "", st["omit"], st["split"], st["verbose"])
        except (OSError, ValueError):
            sys.stderr.write("error: profile conversion refused by safety checks\n")
            return 1
        return 0
    if st["cl_xkey"] is not None:
        if len(raw) < 9:
            sys.stderr.write("error: input too small\n")
            return 1
        body = RC4.from_bytes(st["cl_xkey"]).crypt(raw)
        mask = body[-8:]
        body = bytes(b ^ mask[i & 7] for i, b in enumerate(body[:-8]))
    else:
        body = raw
        if st["cl_key"] is not None:
            body = RC4.from_hex_string(st["cl_key"]).crypt(body)
        if body[:4] != b"#ata":
            sys.stderr.write("error: unknown or encrypted input file\n")
            return 1
        body = body[4:]
    out_fh = io.StringIO()
    ok = binary_to_text(body, out_fh, entries, filt, st["verbose"])
    if not ok:
        return 1
    try:
        _publish_private_outputs([(out_path, out_fh.getvalue().encode("latin-1"))])
    except (OSError, ValueError):
        sys.stderr.write("error: profile conversion refused by safety checks\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
