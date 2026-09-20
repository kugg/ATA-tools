# ATA Firmware-Service Protocol

**Status:** the source-readable Python response stream is qualified against a
recorded vintage-server reference and a synthetic loopback client. It has not yet
flashed a physical ATA. Server completion must not be reported as device success.

This document describes the protocol implementation and its live safety boundary.
The operator checklist is in `../docs/ata-firmware-maintenance.md`.

## Components

- `sata186us.py` validates packages, implements KBOX selection and block responses,
  and runs the fixed-reference loopback qualification.
- `ata_upgrade_client.py` simulates a client only on loopback and byte-checks the
  complete payload.
- `../dhcp.py` implements the bounded DHCP parser/responder.
- `../ata_flash.py` is the only live coordinator. It combines DHCP, route checks,
  image authorization, socket reservation, and one firmware-service window.

Neither `sata186us.py` nor `ata_upgrade_client.py` has a live-device mode.

## Image Validation and Authorization

Live service accepts a bounded, regular, non-symlink `kup1` package whose inner
payload is a deeply validated `+kxz` bank map. Validation includes:

- exact outer framing and additive checksum;
- declared inner length and additive checksum;
- bounded raw and compressed region tables;
- non-overlapping bank destinations;
- exact raw-DEFLATE stream termination and output length;
- matching little-endian CRC-32 and ISIZE trailers.

The operator must also provide a `SHA256SUMS` manifest. Exactly one valid entry must
match the selected image basename and digest. The manifest is an authorization list,
not a vendor-signature or model-compatibility service. Live service is generic within
the validated format; it is not pinned to the reference package.

By contrast, `sata186us.py --qualify` is intentionally pinned to the known reference
image and expected wire identities so it remains a reproducible regression gate.

## Wire Flow

1. A coherent DHCP client obtains one lease on the isolated subnet.
2. The operator waits for the coordinator's ready line and manually enters the one
   printed `100#...*8000#` sequence.
3. The ATA sends a KBOX image-selection request to UDP port 8000.
4. The server returns metadata and a data-channel URL using UDP port 8500.
5. The ATA sends a hello followed by indexed block requests.
6. The server returns zero-padded 1,024-byte blocks until every unique payload block
   has been served and the configured completion grace expires.

The ATA may change source UDP ports and may repeat or reorder requests. The service
therefore locks the leased source IP rather than one source tuple and does not impose
an artificial request-count ceiling. Datagram sizes and parsing are bounded, and the
wall-clock deadline remains the resource limit.

## Live Entry Point

Bare invocation is inert:

```sh
python3 -B ata_flash.py
```

One explicit attempt has this form:

```sh
python3 -B ata_flash.py --apply \
  --interface IFACE \
  --address HOST_IPV4 \
  --client-address ATA_IPV4 \
  --client-mac ATA_MAC \
  firmware/IMAGE.zup
```

The command does not configure an interface or route and does not elevate privileges.
`--address` is an assertion about an already assigned address; when the interface has
multiple IPv4 addresses, the assertion is required. If `--client-address` is omitted,
host number 10 in the selected subnet is offered. If `--client-mac` is omitted, the
first coherent DHCP client is selected.

## Network Safety Checks

Before service and before each response, the coordinator requires all of the
following:

- the selected address still belongs to the selected interface;
- the interface's IPv4 address set and selected subnet have not changed;
- no selected-interface gateway, default route, or split-default-equivalent route;
- no overlapping route to the selected subnet through another interface;
- a direct effective route to the offered client through the selected interface and
  selected output address;
- no collision between the client address and any local interface address.

UDP ports 8000 and 8500 are reserved before DHCP. Sockets bind the exact host address
and, on supported macOS/Linux hosts, the selected interface. Firmware sockets are
nonblocking. Any firmware packet queued before post-DHCP revalidation is treated as
an ambiguous early trigger and aborts the attempt.

DHCP accepts only coherent Ethernet/BOOTP identity and transaction state. The first
accepted client is locked unless a MAC was supplied. Offers contain no gateway or
DNS information. Invalid background packets do not trigger expensive network
revalidation.

These controls reduce accidental contact with unrelated systems; they are not peer
authentication and do not make a shared network suitable for firmware maintenance.

## Completion Semantics

The service distinguishes:

- readiness with no transfer;
- a partial stream;
- every unique block served at least once;
- interruption or safety-check failure.

Only the third condition produces the complete-stream message, after the quiet grace
period. Even then it proves only that Python sent all block responses. It does not
prove receipt, flash writes, validation by the ATA, reboot, boot selection, or
successful SIP operation.

Use `123#` on the ATA after the service ends to hear the running firmware version.
Then verify configuration, registration, ringing, calls, and two-way audio separately.
Never automatically redial or rerun after an ambiguous attempt.

## Reference Qualification

```sh
python3 -B firmware/sata186us.py --qualify \
  firmware/ATA030100SIP040211A.zup
```

The command uses ephemeral `127.0.0.1` UDP sockets and validates:

```text
image_sha256=b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5
command_packets=1/1
command_bytes=42/144
data_packets=313/313
data_bytes=3756/321996
blocks=312
payload_bytes=319135
data_wire_sha256=158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2
selection_normalized_sha256=6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0
```

The vintage server was used only to establish these reference identities during
development. It is not required by the public Python workflow.
