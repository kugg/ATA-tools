"""Offline G.711 mu-law vectors; no microphones, files or sockets."""

import struct
import unittest

from telephony import g711


class G711Tests(unittest.TestCase):
    def test_pcmu_vectors_match_known_g711_values(self):
        samples = (-32768, -30000, -10000, -1000, -1, 0, 1, 1000, 10000, 30000, 32767)
        pcm = struct.pack("<%dh" % len(samples), *samples)
        self.assertEqual(g711.pcm16le_to_pcmu(pcm).hex(), "00021c4e7effffce9c8280")
        self.assertEqual(
            struct.unpack("<%dh" % len(samples), g711.pcmu_to_pcm16le(bytes.fromhex("00021c4e7effffce9c8280"))),
            (-32124, -30076, -9852, -988, -8, 0, 0, 988, 9852, 30076, 32124),
        )

    def test_rejects_empty_odd_and_overlong_buffers(self):
        self.assertEqual(len(g711.pcm16le_to_pcmu(b"\0" * g711.MAX_PCM16_BYTES)), 160)
        self.assertEqual(len(g711.pcmu_to_pcm16le(b"\xff" * 160)), g711.MAX_PCM16_BYTES)
        for pcm in (b"", b"x", b"x" * (g711.MAX_PCM16_BYTES + 2), b"x" * 400):
            with self.subTest(pcm_length=len(pcm)):
                with self.assertRaisesRegex(g711.ProtocolError, "PCM16LE"):
                    g711.pcm16le_to_pcmu(pcm)
        for pcmu in (b"", b"x" * 161, b"x" * 200):
            with self.subTest(pcmu_length=len(pcmu)):
                with self.assertRaisesRegex(g711.ProtocolError, "PCMU"):
                    g711.pcmu_to_pcm16le(pcmu)


if __name__ == "__main__":
    unittest.main()
