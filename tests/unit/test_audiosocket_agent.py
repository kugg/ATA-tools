"""Offline tests for the bounded AudioSocket agent."""

import socket
import struct
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from telephony import audiosocket_agent as agent  # noqa: E402


class ToneTest(unittest.TestCase):
    def test_frame_shape(self):
        frames = agent.tone_frames(count=3)
        self.assertEqual(len(frames), 3)
        self.assertEqual({len(f) for f in frames}, {agent.FRAME_BYTES})

    def test_tone_is_audible(self):
        frame = agent.tone_frames(count=1)[0]
        samples = struct.unpack_from("<%dh" % (len(frame) // 2), frame)
        self.assertTrue(max(abs(s) for s in samples) > 1000)


class FrameTest(unittest.TestCase):
    def test_energy(self):
        quiet = struct.pack("<5h", *[0] * 5)
        self.assertEqual(agent.frame_energy(quiet), 0)
        loud = struct.pack("<2h", 0, -20000)
        self.assertEqual(agent.frame_energy(loud), 20000)


class _LocalSocket:
    def __init__(self):
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self._conn = None

    def connect(self):
        client = socket.create_connection(("127.0.0.1", self.port))
        self._conn, _ = self._listener.accept()
        return client

    def close(self):
        if self._conn:
            self._conn.close()
        self._listener.close()


def _pthread_send(sock, kind, payload=b""):
    sock.sendall(bytes([kind, len(payload) >> 8, len(payload) & 0xFF]) + payload)


def _pthread_recv(sock):
    header = sock.recv(3)
    if len(header) < 3:
        return None, b""
    kind = header[0]
    length = (header[1] << 8) | header[2]
    payload = b""
    while len(payload) < length:
        payload += sock.recv(length - len(payload))
    return kind, payload


class ServeTest(unittest.TestCase):
    def test_session_roundtrip(self):
        local = _LocalSocket()
        client = local.connect()
        result = {}

        def run():
            result.update(agent.serve(local._conn, log=lambda m: None,
                                      tone=agent.tone_frames(count=3)))

        thread = threading.Thread(target=run)
        thread.start()
        uuid = bytes(range(16))
        _pthread_send(client, agent.KIND_UUID, uuid)
        # Tone frames arrive immediately, without the client sending audio.
        for _ in range(3):
            kind, payload = _pthread_recv(client)
            self.assertEqual(kind, agent.KIND_AUDIO)
            self.assertEqual(len(payload), agent.FRAME_BYTES)
        # Inbound audio frames are still counted.
        _pthread_send(client, agent.KIND_AUDIO, b"\x00" * 320)
        _pthread_send(client, agent.KIND_AUDIO,
                      struct.pack("<320h", *([3000] * 320)))
        # Agent terminates after the post-tone window.
        thread.join(timeout=15)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("uuid"), uuid.hex())
        self.assertEqual(result.get("audio_tx"), 3)
        self.assertEqual(result.get("audio_rx"), 2)
        self.assertEqual(result.get("voiced"), 1)
        kind, payload = _pthread_recv(client)
        self.assertEqual(kind, agent.KIND_TERMINATE)
        local.close()
        client.close()

    def test_rejects_missing_uuid(self):
        result = agent.serve(_BrokenSock(), log=lambda m: None)
        self.assertEqual(result, {"ok": False})


class _BrokenSock:
    """Socket whose first read yields a non-uuid message."""

    def recv(self, _size):
        return bytes([agent.KIND_AUDIO, 0x00, 0x02, 0, 0])


if __name__ == "__main__":
    unittest.main()