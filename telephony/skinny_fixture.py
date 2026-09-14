"""Bounded Skinny/SCCP framing for the local Cisco ATA186 fixture.

This is a protocol fixture, not a call server, media stack, or provisioning
service. It does not open sockets or interact with devices by itself.
"""

from dataclasses import dataclass, field
import struct


SCCP_PORT = 2000
ATA186_DEVICE_TYPE = 12

KEEP_ALIVE_MESSAGE = 0x0000
REGISTER_MESSAGE = 0x0001
REGISTER_ACK_MESSAGE = 0x0081
SET_RINGER_MESSAGE = 0x0085
KEEP_ALIVE_ACK_MESSAGE = 0x0100

RINGER_OFF = 1
RINGER_INSIDE = 2
RINGER_OUTSIDE = 3

MAX_BODY_BYTES = 2048
MAX_BUFFER_BYTES = 8192
MAX_FRAMES_PER_FEED = 16

_HEADER = struct.Struct("<III")
_REGISTER = struct.Struct("<16s6IB3x")
_REGISTER_ACK = struct.Struct("<I6s2xI4x")
_RINGER = struct.Struct("<5I")


class ProtocolError(ValueError):
    """A bounded fixture input violates the supported Skinny contract."""


@dataclass(frozen=True)
class Frame:
    message_id: int
    body: bytes = b""
    reserved: int = 0


@dataclass(frozen=True)
class Registration:
    device_name: str
    device_type: int
    protocol_version: int


def _uint32(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise ProtocolError("invalid %s" % field_name)
    return value


def _uint8(value, field_name):
    value = _uint32(value, field_name)
    if value > 0xFF:
        raise ProtocolError("invalid %s" % field_name)
    return value


def _fixed_ascii(value, width, field_name):
    if not isinstance(value, str):
        raise ProtocolError("invalid %s" % field_name)
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as error:
        raise ProtocolError("invalid %s" % field_name) from error
    if not encoded or len(encoded) > width or any(byte <= 0x20 or byte > 0x7E for byte in encoded):
        raise ProtocolError("invalid %s" % field_name)
    return encoded.ljust(width, b"\0")


def _validate_frame(frame):
    if not isinstance(frame, Frame):
        raise TypeError("frame must be a Frame")
    message_id = _uint32(frame.message_id, "message id")
    reserved = _uint32(frame.reserved, "reserved header")
    if not isinstance(frame.body, bytes) or len(frame.body) > MAX_BODY_BYTES:
        raise ProtocolError("invalid frame body")
    return message_id, reserved


def encode_frame(frame):
    message_id, reserved = _validate_frame(frame)
    # Skinny length excludes the length and reserved words, but includes message id.
    return _HEADER.pack(len(frame.body) + 4, reserved, message_id) + frame.body


class FrameDecoder:
    """Incrementally decode a bounded number of little-endian Skinny frames."""

    def __init__(self):
        self._buffer = bytearray()
        self._failed = False

    @property
    def buffered_bytes(self):
        return len(self._buffer)

    @property
    def failed(self):
        return self._failed

    def reset(self):
        """Explicitly discard a failed connection's decoder state."""
        self._buffer.clear()
        self._failed = False

    def _fail(self):
        self._buffer.clear()
        self._failed = True

    def feed(self, data):
        if self._failed:
            raise ProtocolError("decoder is in an error state; reset required")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("frame input must be bytes")
        try:
            if len(data) + len(self._buffer) > MAX_BUFFER_BYTES:
                raise ProtocolError("fixture input exceeds buffer limit")
            self._buffer.extend(data)
            frames = []
            while len(frames) < MAX_FRAMES_PER_FEED and len(self._buffer) >= 8:
                length, reserved = struct.unpack_from("<II", self._buffer)
                if length < 4 or length - 4 > MAX_BODY_BYTES:
                    raise ProtocolError("unsupported Skinny frame length")
                wire_size = length + 8
                if len(self._buffer) < wire_size:
                    break
                message_id = struct.unpack_from("<I", self._buffer, 8)[0]
                body = bytes(self._buffer[12:wire_size])
                del self._buffer[:wire_size]
                frames.append(Frame(message_id, body, reserved))
            if len(frames) == MAX_FRAMES_PER_FEED and len(self._buffer) >= 8:
                length = struct.unpack_from("<I", self._buffer)[0]
                if length < 4 or length - 4 > MAX_BODY_BYTES:
                    raise ProtocolError("unsupported Skinny frame length")
                if len(self._buffer) >= length + 8:
                    raise ProtocolError("too many Skinny frames in one feed")
            return tuple(frames)
        except ProtocolError:
            self._fail()
            raise

    def finish(self):
        """Fail a connection closed with an incomplete Skinny frame."""
        if self._failed:
            raise ProtocolError("decoder is in an error state; reset required")
        if self._buffer:
            self._fail()
            raise ProtocolError("truncated Skinny frame at end of input")


def build_register_body(
    device_name,
    device_type=ATA186_DEVICE_TYPE,
    protocol_version=3,
    user_id=0,
    instance=1,
    ip_address=0,
    max_streams=1,
):
    return _REGISTER.pack(
        _fixed_ascii(device_name, 16, "device name"),
        _uint32(user_id, "user id"),
        _uint32(instance, "instance"),
        _uint32(ip_address, "IP address"),
        _uint32(device_type, "device type"),
        _uint32(max_streams, "maximum streams"),
        0,
        _uint8(protocol_version, "protocol version"),
    )


def parse_register_body(body):
    if not isinstance(body, bytes) or len(body) < _REGISTER.size:
        raise ProtocolError("short register message")
    if len(body) > MAX_BODY_BYTES:
        raise ProtocolError("invalid register message length")
    name, _user_id, _instance, _ip_address, device_type, _max_streams, _space, protocol_version = (
        _REGISTER.unpack_from(body)
    )
    terminator = name.find(b"\0")
    if terminator >= 0:
        if any(name[terminator + 1:]):
            raise ProtocolError("invalid register identity")
        name = name[:terminator]
    try:
        device_name = name.decode("ascii")
    except UnicodeDecodeError as error:
        raise ProtocolError("invalid register identity") from error
    _fixed_ascii(device_name, 16, "device name")
    return Registration(device_name, device_type, protocol_version)


def build_register_ack_body(keepalive_seconds=30):
    keepalive_seconds = _uint32(keepalive_seconds, "keepalive interval")
    if not 1 <= keepalive_seconds <= 3600:
        raise ProtocolError("invalid keepalive interval")
    return _REGISTER_ACK.pack(keepalive_seconds, b"D-M-Y\0", keepalive_seconds)


def build_ringer_body(mode):
    mode = _uint32(mode, "ringer mode")
    if mode not in (RINGER_OFF, RINGER_INSIDE, RINGER_OUTSIDE):
        raise ProtocolError("invalid ringer mode")
    return _RINGER.pack(mode, 0, 0, 0, 0)


@dataclass
class FixtureSession:
    """A narrow ATA186 registration/keepalive/ringer state machine."""

    expected_device_name: str = "ATA186-TEST"
    keepalive_seconds: int = 30
    _registered: bool = field(default=False, init=False, repr=False)
    _failed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        _fixed_ascii(self.expected_device_name, 16, "device name")
        build_register_ack_body(self.keepalive_seconds)

    @property
    def registered(self):
        return self._registered

    @property
    def failed(self):
        return self._failed

    def reset(self):
        """Explicitly discard a failed connection's registration state."""
        self._registered = False
        self._failed = False

    def _fail(self):
        self._registered = False
        self._failed = True

    def _ensure_active(self):
        if self._failed:
            raise ProtocolError("session is in an error state; reset required")

    def receive(self, frame):
        self._ensure_active()
        try:
            _validate_frame(frame)
            if not self._registered:
                if frame.message_id != REGISTER_MESSAGE:
                    raise ProtocolError("register required before other SCCP messages")
                registration = parse_register_body(frame.body)
                if registration.device_name != self.expected_device_name:
                    raise ProtocolError("unexpected SCCP identity")
                if registration.device_type != ATA186_DEVICE_TYPE:
                    raise ProtocolError("unexpected SCCP device type")
                self._registered = True
                return Frame(REGISTER_ACK_MESSAGE, build_register_ack_body(self.keepalive_seconds))
            if frame.message_id == KEEP_ALIVE_MESSAGE and not frame.body:
                return Frame(KEEP_ALIVE_ACK_MESSAGE)
            raise ProtocolError("unsupported SCCP message after registration")
        except ProtocolError:
            self._fail()
            raise

    def ringer(self, mode):
        self._ensure_active()
        try:
            if not self._registered:
                raise ProtocolError("cannot ring an unregistered SCCP device")
            return Frame(SET_RINGER_MESSAGE, build_ringer_body(mode))
        except ProtocolError:
            self._fail()
            raise


@dataclass
class FixtureEndpoint:
    """Byte-oriented adapter for a later loopback TCP fixture runner."""

    session: FixtureSession = field(default_factory=FixtureSession)
    decoder: FrameDecoder = field(default_factory=FrameDecoder)

    @property
    def failed(self):
        return self.session.failed or self.decoder.failed

    def reset(self):
        """Explicitly prepare this endpoint for a new synthetic connection."""
        self.session.reset()
        self.decoder.reset()

    def _fail(self):
        self.session._fail()
        self.decoder._fail()

    def receive(self, data):
        if self.failed:
            raise ProtocolError("fixture is in an error state; reset required")
        try:
            replies = [self.session.receive(frame) for frame in self.decoder.feed(data)]
            return b"".join(encode_frame(reply) for reply in replies)
        except ProtocolError:
            self._fail()
            raise

    def ringer(self, mode):
        if self.failed:
            raise ProtocolError("fixture is in an error state; reset required")
        try:
            return encode_frame(self.session.ringer(mode))
        except ProtocolError:
            self._fail()
            raise

    def finish(self):
        """Mark an input stream complete and reject an incomplete final frame."""
        if self.failed:
            raise ProtocolError("fixture is in an error state; reset required")
        try:
            self.decoder.finish()
        except ProtocolError:
            self._fail()
            raise
