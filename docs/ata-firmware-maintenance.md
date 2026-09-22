# ATA Firmware Maintenance Checklist

**Status:** offline package validation and the complete loopback response stream are
tested. One operator-attended isolated ATA186 transfer completed and the device
subsequently reported SIP 3.1(0); that single result does not qualify another
image, model, device, recovery path, or network.

Use this checklist for one operator-attended maintenance attempt. It is not an
authorization to operate on a device or network you do not own.

## 1. Identify the Device

- Confirm the exact ATA model, current protocol image, and current firmware version.
- Use the ATA IVR code `123#` to hear the running version and record it privately.
- Record current configuration and any available recovery procedure without adding
  credentials, exports, firmware, or device identifiers to Git.
- Confirm the target supports the exact model and a valid upgrade path from the
  installed release. Cisco's historical notice requires an intermediate transition
  image for version 1.34 and earlier; do not assume a direct jump is valid.
- Understand that changing from SCCP, H.323, or MGCP to SIP is a firmware operation,
  not merely a configuration-field change.

## 2. Authorize and Inspect the Image

- Obtain firmware only from a source from which you are legally entitled to receive
  and use it.
- Calculate SHA-256 and compare it with an independent trusted value where possible.
- Create a private adjacent `SHA256SUMS` whose exact basename matches the image.
- Run both local inspection commands:

```sh
python3 -B firmware/sata186us.py --inspect firmware/IMAGE.zup
python3 -B firmware/zup_bank.py firmware/IMAGE.zup
```

- Confirm the outer metadata, platform, protocol, version, and reconstructed-map
  result match the intended operation.
- Do not treat additive checksums, reconstruction, or a local manifest as a vendor
  signature or provenance proof.

## 3. Prepare an Isolated Cable

- Connect one ATA to one dedicated Ethernet interface.
- Keep the interface disconnected from LANs, WANs, VPN forwarding, bridges, and
  unrelated devices.
- Configure the host address outside this project and record which process owns UDP
  ports 8000 and 8500.
- Review both IPv4 and IPv6 routing before launch. Stop if the candidate subnet
  overlaps any other interface or VPN, or if ownership is ambiguous.
- Ensure the selected interface has no gateway, default route, or split default.
- Prefer an explicit expected ATA MAC address.

`ata_flash.py` checks these conditions but does not create them. It never changes
addresses, routes, DNS, packet filters, or VPN state.

## 4. Run Offline Gates

Run the public test commands from `README.md`. For the known reference image, also
run:

```sh
python3 -B firmware/sata186us.py --qualify \
  firmware/ATA030100SIP040211A.zup
```

This is a loopback-only software gate. It does not contact the device.

## 5. Start One Service Window

```sh
python3 -B ata_flash.py --apply \
  --interface IFACE \
  --address HOST_IPV4 \
  --client-address ATA_IPV4 \
  --client-mac ATA_MAC \
  --dhcp-timeout-seconds 600 \
  --duration-seconds 3600 \
  firmware/IMAGE.zup
```

The coordinator validates the package and manifest before opening sockets, reserves
both firmware ports before DHCP, locks one client, and rechecks interface and route
ownership before each response. It exits nonzero for no transfer, partial transfer,
network drift, early firmware traffic, interruption, or ambiguous delivery.

Wait for the exact ready line. Manually enter the printed DTMF sequence once. Do not
pre-enter it, script it, redial it automatically, or rerun the command after an
uncertain outcome.

## 6. Interpret the Result Conservatively

`All firmware blocks were served` means only that Python sent every unique block at
least once and completed the retransmission grace period. It does not establish:

- successful receipt by the ATA;
- a completed flash write;
- image acceptance;
- reboot or boot selection;
- persistent firmware version;
- SIP registration, ringing, or audio.

An interruption, route change, early packet, incomplete block set, or uncertain ATA
state is an ambiguous failure. Preserve power and isolation as appropriate to the
device's documented recovery procedure and investigate manually. Never infer that a
retry is safe.

## 7. Verify the Device Separately

- Let the service exit and ensure no firmware listener remains.
- Use `123#` to hear the running version.
- Re-open management only on a trusted isolated network.
- Confirm the intended protocol and configuration survived.
- For SIP, verify the expected registrar binding and `/stats/` data.
- Test dial tone, one controlled outbound call, one controlled inbound ring, and
  intelligible two-way audio.
- Record each observation separately. Do not promote server logs to hardware proof.

## 8. Configuration Follow-Up

Use `http://<ATA-IP>/dev` for manual configuration or one intentionally managed TFTP
profile path, not both accidentally. TFTP refresh can replace web/IVR settings. See
the configuration section in `../README.md` for field names, private profile handling,
and `firmware/cfgfmt.py` examples.

The historical web UI and provisioning protocols do not meet modern transport-
security expectations. Keep them isolated and do not reuse valuable credentials.

## References

- [Cisco ATA186/188 SIP configuration guide](https://web.archive.org/web/20040221155736id_/http://www.cisco.com/univercd/cc/td/doc/product/voice/ata/ataadmn/sip30ad/sip88ch3.htm)
- [Cisco ATA186/188 3.1 release notes](https://web.archive.org/web/20090704161416id_/http://www.cisco.com/en/US/docs/voice_ip_comm/cata/186_188/3_1_0/english/release/notes/atarn3_1.html)
- `../firmware/FLASHING.md` for protocol and completion semantics
- `firmware-analysis.md` for the current static-analysis evidence
