"""Bounded IAX2 mini-frame media fixture for local host qualification.

This implements only unencrypted voice mini frames after an engine has already
authenticated, negotiated PCMU, and sent the initial full voice frame. It is not
an IAX2 registration, call-control, authentication, or encryption implementation.
"""

from dataclasses import dataclass, field
import struct


IAX2_MINI_HEADER_BYTES = 4
IAX2_CALL_NUMBER_MAX = 0x7FFF
IAX2_PACKETIZATION_MS = 20
PCMU_PACKET_BYTES = 160
PCMU_SILENCE = b"\xff" * PCMU_PACKET_BYTES


class ProtocolError(ValueError):
    """A mini-frame violates the narrow host-fixture profile."""


@dataclass(frozen=True)
class MiniFrame:
    source_call_number: int
    timestamp: int
    payload: bytes


def _uint16(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
        raise ProtocolError("invalid %s" % field_name)
    return value


def _call_number(value, field_name):
    value = _uint16(value, field_name)
    if not 1 <= value <= IAX2_CALL_NUMBER_MAX:
        raise ProtocolError("invalid %s" % field_name)
    return value


def _payload(value):
    if not isinstance(value, bytes) or len(value) != PCMU_PACKET_BYTES:
        raise ProtocolError("IAX2 fixture requires one 20ms PCMU payload")
    return value


def encode_mini_frame(frame):
    if not isinstance(frame, MiniFrame):
        raise TypeError("frame must be a MiniFrame")
    source_call_number = _call_number(frame.source_call_number, "source call number")
    timestamp = _uint16(frame.timestamp, "timestamp")
    payload = _payload(frame.payload)
    # A cleared high bit denotes an IAX2 mini frame; call number zero is meta-frame space.
    return struct.pack("!HH", source_call_number, timestamp) + payload


def decode_mini_frame(wire):
    if not isinstance(wire, bytes) or len(wire) != IAX2_MINI_HEADER_BYTES + PCMU_PACKET_BYTES:
        raise ProtocolError("invalid IAX2 mini-frame length")
    source_call_number, timestamp = struct.unpack_from("!HH", wire)
    if source_call_number & 0x8000:
        raise ProtocolError("full IAX2 frames are outside this fixture")
    source_call_number = _call_number(source_call_number, "source call number")
    return MiniFrame(source_call_number, timestamp, _payload(wire[IAX2_MINI_HEADER_BYTES:]))


@dataclass
class MiniMediaSession:
    """One pre-negotiated PCMU mini-frame stream in each direction."""

    inbound_call_number: int
    outbound_call_number: int
    initial_timestamp: int = IAX2_PACKETIZATION_MS
    _next_inbound_timestamp: int | None = field(default=None, init=False, repr=False)
    _next_outbound_timestamp: int | None = field(default=None, init=False, repr=False)
    _failed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        self.inbound_call_number = _call_number(self.inbound_call_number, "inbound call number")
        self.outbound_call_number = _call_number(self.outbound_call_number, "outbound call number")
        if self.inbound_call_number == self.outbound_call_number:
            raise ProtocolError("fixture call numbers must differ")
        self.initial_timestamp = _uint16(self.initial_timestamp, "initial timestamp")
        if not self.initial_timestamp or self.initial_timestamp % IAX2_PACKETIZATION_MS:
            raise ProtocolError("initial timestamp must be a nonzero 20ms boundary")
        self.reset()

    @property
    def failed(self):
        return self._failed

    def reset(self):
        """Explicitly begin a new pre-negotiated synthetic media stream."""
        self._next_inbound_timestamp = self.initial_timestamp
        self._next_outbound_timestamp = self.initial_timestamp
        self._failed = False

    def _fail(self):
        self._failed = True
        self._next_inbound_timestamp = None
        self._next_outbound_timestamp = None

    def _ensure_active(self):
        if self._failed:
            raise ProtocolError("IAX2 mini-frame session is in an error state; reset required")

    @staticmethod
    def _next_timestamp(timestamp):
        next_timestamp = timestamp + IAX2_PACKETIZATION_MS
        # A full voice frame must resynchronize before the 16-bit mini timestamp wraps.
        return next_timestamp if next_timestamp <= 0x7FFF else None

    def receive(self, wire):
        self._ensure_active()
        try:
            frame = decode_mini_frame(wire)
            if self._next_inbound_timestamp is None:
                raise ProtocolError("IAX2 full-frame resynchronization required")
            if frame.source_call_number != self.inbound_call_number:
                raise ProtocolError("unexpected IAX2 source call number")
            if frame.timestamp != self._next_inbound_timestamp:
                raise ProtocolError("unexpected IAX2 mini-frame timestamp")
            self._next_inbound_timestamp = self._next_timestamp(frame.timestamp)
            return frame
        except ProtocolError:
            self._fail()
            raise

    def build_outbound(self, payload=PCMU_SILENCE):
        self._ensure_active()
        try:
            if self._next_outbound_timestamp is None:
                raise ProtocolError("IAX2 full-frame resynchronization required")
            frame = MiniFrame(self.outbound_call_number, self._next_outbound_timestamp, _payload(payload))
            self._next_outbound_timestamp = self._next_timestamp(frame.timestamp)
            return frame
        except ProtocolError:
            self._fail()
            raise
