# ATA Tools

Source-readable tools and research for keeping Cisco ATA186 and ATA188 analog
telephone adapters useful.

**What this is:** a Python port of the ATA firmware flash tools, diagnostics and
DHCP client, together with configuration tooling (profile compilation, TFTP
provisioning, live config apply) and reverse-engineering guidance for the
firmware itself. It does not include Cisco firmware or support files.

**Start here:** [`docs/getting-started.md`](docs/getting-started.md) — the whole
path from a stock (SCCP) ATA to a working call: SIP firmware, TFTP provisioning,
Asterisk on OpenWrt (built first in a QEMU twin), and the everyday operations
that never need a power cycle (live config apply, config re-fetch, device
syslog).

> [!CAUTION]
> Firmware maintenance can permanently disable a device. The transfer protocol has
> been proven against a physical ATA186: the KBOX selection and data dialogue were
> served, the device rebooted and reported SIP 3.1(0) via `123#`, a TFTP-served
> bench profile was applied, and registration, ringing, and two-way RTP audio were
> observed on an isolated bench. These are results for one specific device and
> profile, not a general guarantee. Keep modified firmware and modified profiles
> off production hardware until separately validated.

## Tools

- `ata_flash.py`, `firmware/sata186us.py`, `firmware/ata_upgrade_client.py` —
  firmware-service (KBOX) coordinator, image validation and loopback client.
- `dhcp.py` — bounded DHCP responder for the firmware-service window.
- `firmware/cfgfmt.py` — text ⇄ binary profile compiler (with `ptag.dat`).
- `telephony/tftp_profile.py` — bounded TFTP profile server.
- `telephony/ata_dev_post.py` — live `/dev` config POST (no reboot needed).
- `firmware/zup_bank.py`, `firmware/zup_extract.py`, `firmware/zup_rebuild.py` —
  package and bank tools.
- `firmware/ghidra_module/`, `firmware/ghidra_*.py` — MIPS-X SLEIGH support and
  decompilation drivers.
- `firmware/syslog_lookup.py` — offline message/address lookup over the complete
  27-call packed syslog atlas, with optional package-backed verification.
- `firmware/service_lookup.py` — offline lookup for the complete web-route
  recognizer and the firmware's TFTP client surface.
- `webrtc/`, `tests/apu2/`, `tests/qemu/` — Asterisk/WebRTC deployment, the QEMU
  twin harness, and the automated echo test.

## Documentation

- `docs/getting-started.md` — practical path: stock ATA → Asterisk call.
- `docs/ata-config-formats.md` — the four configuration forms, compiling, and
  live apply.
- `docs/ata-sip-firmware-services.md` — services, syslog, remote reboot paths.
- `docs/firmware-analysis.md` — firmware structure, packages, launch payloads.
- `docs/ata-syslog-atlas.md` — message-to-instruction/class/owner atlas and lookup.
- `docs/ata-service-atlas.md` — web routes and TFTP client operations mapped to
  runtime evidence.
- `docs/ata-firmware-maintenance.md` — operator checklist for maintenance.
- `docs/asterisk-integration.md` — moving the PBX from the QEMU twin to the device.
- `firmware/FLASHING.md` — firmware-service protocol, validation and safety.

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s firmware/tests -v
```

## License and trademarks

BSD-3-Clause — see `LICENSE` and `THIRD_PARTY_NOTICES.md`. Cisco, ATA and related
marks belong to their owners; this project is not affiliated with or endorsed by
Cisco.
