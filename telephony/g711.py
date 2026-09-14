"""Bounded G.711 mu-law conversion for deterministic host-fixture vectors only."""

import struct

from telephony.iax2_fixture import PCMU_PACKET_BYTES


MAX_PCM16_BYTES = PCMU_PACKET_BYTES * 2


class ProtocolError(ValueError):
    """A PCM or PCMU buffer is outside the bounded fixture profile."""


def _validate_pcm16le(pcm):
    if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > MAX_PCM16_BYTES:
        raise ProtocolError("invalid PCM16LE fixture buffer")
    return pcm


def _validate_pcmu(pcmu):
    if not isinstance(pcmu, bytes) or not pcmu or len(pcmu) > PCMU_PACKET_BYTES:
        raise ProtocolError("invalid PCMU fixture buffer")
    return pcmu


def _linear16_to_pcmu(sample):
    """Match the 14-bit mu-law mapping used by CPython's historical audioop."""
    sample >>= 2
    if sample < 0:
        sample = -sample
        mask = 0x7F
    else:
        mask = 0xFF
    sample += 0x21
    segment = 0
    for endpoint in (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF):
        if sample <= endpoint:
            break
        segment += 1
    if segment >= 8:
        return 0x7F ^ mask
    return ((segment << 4) | ((sample >> (segment + 1)) & 0x0F)) ^ mask


def _pcmu_to_linear16(value):
    value = (~value) & 0xFF
    sample = ((value & 0x0F) << 3) + 0x84
    sample <<= (value & 0x70) >> 4
    return 0x84 - sample if value & 0x80 else sample - 0x84


def pcm16le_to_pcmu(pcm):
    pcm = _validate_pcm16le(pcm)
    samples = struct.unpack("<%dh" % (len(pcm) // 2), pcm)
    return bytes(_linear16_to_pcmu(sample) for sample in samples)


def pcmu_to_pcm16le(pcmu):
    pcmu = _validate_pcmu(pcmu)
    return struct.pack("<%dh" % len(pcmu), *(_pcmu_to_linear16(value) for value in pcmu))
