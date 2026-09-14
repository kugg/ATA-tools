"""Single-shot, loopback-only host qualification for future telephony work."""

import argparse
from dataclasses import dataclass
import ipaddress
import socket
import struct
import time

from telephony.g711 import pcm16le_to_pcmu
from telephony.iax2_fixture import MiniFrame, MiniMediaSession, decode_mini_frame, encode_mini_frame
from telephony.rtp_external_media import PcmuMediaSession, RtpPacket, decode_rtp_packet, encode_rtp_packet
from telephony.skinny_fixture import (
    FixtureEndpoint,
    Frame,
    FrameDecoder,
    KEEP_ALIVE_ACK_MESSAGE,
    KEEP_ALIVE_MESSAGE,
    REGISTER_ACK_MESSAGE,
    REGISTER_MESSAGE,
    RINGER_INSIDE,
    SET_RINGER_MESSAGE,
    build_register_body,
    encode_frame,
)


LOOPBACK_ADDRESS = "127.0.0.1"
SOCKET_TIMEOUT_SECONDS = 1.0
MAX_TCP_READ_BYTES = 4096
MAX_UDP_READ_BYTES = 512


@dataclass(frozen=True)
class QualificationResult:
    sccp: bool
    iax2_mini: bool
    rtp_pcmu: bool


def _require_loopback(address):
    if not ipaddress.ip_address(address[0]).is_loopback:
        raise RuntimeError("host qualification rejected a non-loopback peer")


def _recv_tcp_until_deadline(sock, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("SCCP loopback exchange exceeded its receive deadline")
    sock.settimeout(remaining)
    try:
        return sock.recv(MAX_TCP_READ_BYTES)
    except socket.timeout as error:
        raise RuntimeError("SCCP loopback exchange timed out") from error


def _receive_sccp_response(server, endpoint):
    deadline = time.monotonic() + SOCKET_TIMEOUT_SECONDS
    while True:
        wire = _recv_tcp_until_deadline(server, deadline)
        if not wire:
            endpoint.finish()
            raise RuntimeError("SCCP peer closed before completing a frame")
        response = endpoint.receive(wire)
        if response:
            return response


def _read_one_sccp_frame(client, decoder):
    deadline = time.monotonic() + SOCKET_TIMEOUT_SECONDS
    while True:
        wire = _recv_tcp_until_deadline(client, deadline)
        if not wire:
            decoder.finish()
            raise RuntimeError("SCCP fixture closed before returning a frame")
        frames = decoder.feed(wire)
        if len(frames) == 1:
            return frames[0]
        if len(frames) > 1:
            raise RuntimeError("SCCP loopback exchange returned unexpected coalesced frames")


def _expect_sccp_eof(sock):
    deadline = time.monotonic() + SOCKET_TIMEOUT_SECONDS
    if _recv_tcp_until_deadline(sock, deadline):
        raise RuntimeError("SCCP loopback peer sent unexpected data after shutdown")


def _synthetic_pcmu_packet():
    # This deterministic waveform is test data, not captured or generated user audio.
    samples = tuple(1000 if index % 2 else -1000 for index in range(160))
    return pcm16le_to_pcmu(struct.pack("<160h", *samples))


def run_sccp_loopback():
    """Exercise register, ring and keepalive over one IPv4 loopback TCP connection."""
    endpoint = FixtureEndpoint()
    client_decoder = FrameDecoder()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.settimeout(SOCKET_TIMEOUT_SECONDS)
        listener.bind((LOOPBACK_ADDRESS, 0))
        listener.listen(1)
        with socket.create_connection(listener.getsockname(), SOCKET_TIMEOUT_SECONDS) as client:
            client.settimeout(SOCKET_TIMEOUT_SECONDS)
            server, address = listener.accept()
            with server:
                server.settimeout(SOCKET_TIMEOUT_SECONDS)
                _require_loopback(address)
                register_wire = encode_frame(
                    Frame(REGISTER_MESSAGE, build_register_body("ATA186-TEST"))
                )
                # Feed a partial header first so this exercises stream framing, not packet framing.
                client.sendall(register_wire[:8])
                if endpoint.receive(_recv_tcp_until_deadline(server, time.monotonic() + SOCKET_TIMEOUT_SECONDS)):
                    raise RuntimeError("SCCP fixture replied before a fragmented register was complete")
                client.sendall(register_wire[8:])
                response = _receive_sccp_response(server, endpoint)
                server.sendall(response)
                if _read_one_sccp_frame(client, client_decoder).message_id != REGISTER_ACK_MESSAGE:
                    raise RuntimeError("SCCP registration acknowledgement was not returned")

                ringer_wire = endpoint.ringer(RINGER_INSIDE)
                server.sendall(ringer_wire[:8])
                if client_decoder.feed(_recv_tcp_until_deadline(client, time.monotonic() + SOCKET_TIMEOUT_SECONDS)):
                    raise RuntimeError("SCCP client decoded a fragmented ringer too early")
                server.sendall(ringer_wire[8:])
                if _read_one_sccp_frame(client, client_decoder).message_id != SET_RINGER_MESSAGE:
                    raise RuntimeError("SCCP ringer frame was not returned")

                client.sendall(encode_frame(Frame(KEEP_ALIVE_MESSAGE)))
                response = _receive_sccp_response(server, endpoint)
                server.sendall(response)
                if _read_one_sccp_frame(client, client_decoder).message_id != KEEP_ALIVE_ACK_MESSAGE:
                    raise RuntimeError("SCCP keepalive acknowledgement was not returned")

                client.shutdown(socket.SHUT_WR)
                _expect_sccp_eof(server)
                endpoint.finish()
                server.shutdown(socket.SHUT_WR)
                _expect_sccp_eof(client)
                client_decoder.finish()


def run_iax2_mini_loopback():
    """Exercise two PCMU IAX2 mini frames over one IPv4 loopback UDP peer pair."""
    session = MiniMediaSession(inbound_call_number=101, outbound_call_number=202)
    payload = _synthetic_pcmu_packet()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.settimeout(SOCKET_TIMEOUT_SECONDS)
        server.bind((LOOPBACK_ADDRESS, 0))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(SOCKET_TIMEOUT_SECONDS)
            client.bind((LOOPBACK_ADDRESS, 0))
            client.connect(server.getsockname())
            for timestamp in (20, 40):
                client.send(encode_mini_frame(MiniFrame(101, timestamp, payload)))
                wire, address = server.recvfrom(MAX_UDP_READ_BYTES)
                _require_loopback(address)
                received = session.receive(wire)
                server.sendto(encode_mini_frame(session.build_outbound(received.payload)), address)
                reply = decode_mini_frame(client.recv(MAX_UDP_READ_BYTES))
                if reply.source_call_number != 202 or reply.timestamp != timestamp:
                    raise RuntimeError("IAX2 mini-frame reply did not preserve the profile sequence")
                if reply.payload != payload:
                    raise RuntimeError("IAX2 mini-frame reply did not preserve the PCMU payload")


def run_rtp_pcmu_loopback():
    """Exercise two PCMU RTP packets used by a future external-media adapter."""
    session = PcmuMediaSession(inbound_ssrc=0x11111111, outbound_ssrc=0x22222222)
    payload = _synthetic_pcmu_packet()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.settimeout(SOCKET_TIMEOUT_SECONDS)
        server.bind((LOOPBACK_ADDRESS, 0))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(SOCKET_TIMEOUT_SECONDS)
            client.bind((LOOPBACK_ADDRESS, 0))
            client.connect(server.getsockname())
            for sequence, timestamp in ((100, 0), (101, 160)):
                client.send(
                    encode_rtp_packet(
                        RtpPacket(sequence, timestamp, 0x11111111, payload)
                    )
                )
                wire, address = server.recvfrom(MAX_UDP_READ_BYTES)
                _require_loopback(address)
                received = session.receive(wire)
                server.sendto(encode_rtp_packet(session.build_outbound(received.payload)), address)
                reply = decode_rtp_packet(client.recv(MAX_UDP_READ_BYTES))
                if reply.ssrc != 0x22222222 or reply.sequence != sequence + 400:
                    raise RuntimeError("RTP reply did not preserve the profile sequence")
                if reply.timestamp != timestamp:
                    raise RuntimeError("RTP reply did not preserve the profile timestamp")
                if reply.payload != payload:
                    raise RuntimeError("RTP reply did not preserve the PCMU payload")


def run_host_qualification():
    run_sccp_loopback()
    run_iax2_mini_loopback()
    run_rtp_pcmu_loopback()
    return QualificationResult(sccp=True, iax2_mini=True, rtp_pcmu=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="open bounded IPv4 loopback sockets")
    args = parser.parse_args(argv)
    if not args.run:
        print("PLAN: SCCP TCP, IAX2 mini-frame UDP and RTP/PCMU UDP on 127.0.0.1 only")
        print("No sockets are opened without --run; no APU, ATA, QEMU, WireGuard or audio input is used.")
        return 0
    run_host_qualification()
    print("PASS: host loopback SCCP, IAX2 mini-frame and RTP/PCMU qualification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
