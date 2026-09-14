"""Bounded RTP/PCMU contract for a future external-media engine adapter.

The profile is one 20 ms PCMU packet at a time. It deliberately excludes RTP
header extensions, CSRC lists, padding, RTCP, jitter buffering and audio capture.
"""

from dataclasses import dataclass, field
import struct

from telephony.iax2_fixture import PCMU_PACKET_BYTES, PCMU_SILENCE


RTP_HEADER_BYTES = 12
RTP_VERSION = 2
PCMU_PAYLOAD_TYPE = 0
RTP_TIMESTAMP_STEP = PCMU_PACKET_BYTES


class ProtocolError(ValueError):
    """An RTP packet violates the narrow host external-media profile."""


@dataclass(frozen=True)
class RtpPacket:
    sequence: int
    timestamp: int
    ssrc: int
    payload: bytes
    marker: bool = False
    payload_type: int = PCMU_PAYLOAD_TYPE


def _uint(value, maximum, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ProtocolError("invalid %s" % field_name)
    return value


def _payload(value):
    if not isinstance(value, bytes) or len(value) != PCMU_PACKET_BYTES:
        raise ProtocolError("RTP fixture requires one 20ms PCMU payload")
    return value


def _validate_packet(packet):
    if not isinstance(packet, RtpPacket):
        raise TypeError("packet must be an RtpPacket")
    sequence = _uint(packet.sequence, 0xFFFF, "sequence")
    timestamp = _uint(packet.timestamp, 0xFFFFFFFF, "timestamp")
    ssrc = _uint(packet.ssrc, 0xFFFFFFFF, "SSRC")
    if packet.payload_type != PCMU_PAYLOAD_TYPE:
        raise ProtocolError("RTP fixture accepts PCMU payload type 0 only")
    if not isinstance(packet.marker, bool):
        raise ProtocolError("invalid RTP marker")
    return sequence, timestamp, ssrc, _payload(packet.payload)


def encode_rtp_packet(packet):
    sequence, timestamp, ssrc, payload = _validate_packet(packet)
    first = RTP_VERSION << 6
    second = (0x80 if packet.marker else 0) | PCMU_PAYLOAD_TYPE
    return struct.pack("!BBHII", first, second, sequence, timestamp, ssrc) + payload


def decode_rtp_packet(wire):
    if not isinstance(wire, bytes) or len(wire) != RTP_HEADER_BYTES + PCMU_PACKET_BYTES:
        raise ProtocolError("invalid RTP packet length")
    first, second, sequence, timestamp, ssrc = struct.unpack_from("!BBHII", wire)
    if first >> 6 != RTP_VERSION:
        raise ProtocolError("unsupported RTP version")
    if first & 0x3F:
        raise ProtocolError("RTP extensions, CSRCs and padding are outside this fixture")
    payload_type = second & 0x7F
    if payload_type != PCMU_PAYLOAD_TYPE:
        raise ProtocolError("RTP fixture accepts PCMU payload type 0 only")
    return RtpPacket(sequence, timestamp, ssrc, _payload(wire[RTP_HEADER_BYTES:]), bool(second & 0x80))


@dataclass
class PcmuMediaSession:
    """One sequential inbound and outbound PCMU RTP stream."""

    inbound_ssrc: int
    outbound_ssrc: int
    initial_inbound_sequence: int = 100
    initial_outbound_sequence: int = 500
    initial_timestamp: int = 0
    _next_inbound_sequence: int = field(default=0, init=False, repr=False)
    _next_outbound_sequence: int = field(default=0, init=False, repr=False)
    _next_inbound_timestamp: int = field(default=0, init=False, repr=False)
    _next_outbound_timestamp: int = field(default=0, init=False, repr=False)
    _failed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        self.inbound_ssrc = _uint(self.inbound_ssrc, 0xFFFFFFFF, "inbound SSRC")
        self.outbound_ssrc = _uint(self.outbound_ssrc, 0xFFFFFFFF, "outbound SSRC")
        if self.inbound_ssrc == self.outbound_ssrc:
            raise ProtocolError("fixture SSRCs must differ")
        self.initial_inbound_sequence = _uint(
            self.initial_inbound_sequence, 0xFFFF, "initial inbound sequence"
        )
        self.initial_outbound_sequence = _uint(
            self.initial_outbound_sequence, 0xFFFF, "initial outbound sequence"
        )
        self.initial_timestamp = _uint(self.initial_timestamp, 0xFFFFFFFF, "initial timestamp")
        self.reset()

    @property
    def failed(self):
        return self._failed

    def reset(self):
        """Explicitly begin a new synthetic external-media stream."""
        self._next_inbound_sequence = self.initial_inbound_sequence
        self._next_outbound_sequence = self.initial_outbound_sequence
        self._next_inbound_timestamp = self.initial_timestamp
        self._next_outbound_timestamp = self.initial_timestamp
        self._failed = False

    def _fail(self):
        self._failed = True

    def _ensure_active(self):
        if self._failed:
            raise ProtocolError("RTP session is in an error state; reset required")

    def receive(self, wire):
        self._ensure_active()
        try:
            packet = decode_rtp_packet(wire)
            if packet.ssrc != self.inbound_ssrc:
                raise ProtocolError("unexpected RTP SSRC")
            if packet.sequence != self._next_inbound_sequence:
                raise ProtocolError("unexpected RTP sequence")
            if packet.timestamp != self._next_inbound_timestamp:
                raise ProtocolError("unexpected RTP timestamp")
            self._next_inbound_sequence = (packet.sequence + 1) & 0xFFFF
            self._next_inbound_timestamp = (packet.timestamp + RTP_TIMESTAMP_STEP) & 0xFFFFFFFF
            return packet
        except ProtocolError:
            self._fail()
            raise

    def build_outbound(self, payload=PCMU_SILENCE):
        self._ensure_active()
        try:
            packet = RtpPacket(
                self._next_outbound_sequence,
                self._next_outbound_timestamp,
                self.outbound_ssrc,
                _payload(payload),
            )
            self._next_outbound_sequence = (packet.sequence + 1) & 0xFFFF
            self._next_outbound_timestamp = (packet.timestamp + RTP_TIMESTAMP_STEP) & 0xFFFFFFFF
            return packet
        except ProtocolError:
            self._fail()
            raise
