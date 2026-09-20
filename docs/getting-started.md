# Getting started: stock ATA 186 → Asterisk on OpenWrt

ATA Tools is a Python port of the ATA firmware flash tools, diagnostics and DHCP
client, together with configuration tooling (profile compilation, TFTP
provisioning, live config apply) and reverse-engineering guidance for the
firmware itself. It does not include Cisco firmware or support files.

This guide is the practical path from a factory Cisco ATA 186/188 (SCCP mode,
never flashed) to a working phone on an Asterisk PBX (the phone system) running
on OpenWrt. It is the short version; each step points at the deep-dive docs.

**What you end up with:** the ATA running the SIP firmware, provisioned over
TFTP, registered to Asterisk on OpenWrt, and able to make calls. Calling from a
browser (WebRTC) is an optional extra at the end.

## What you need

- A Cisco ATA 186/188 and one analog phone to use its IVR (voice menu).
- A host with Python 3 on the same LAN (serves firmware and config).
- An OpenWrt x86/64 box where Asterisk will run.
- The pinned SIP firmware image (SIP 3.1.0, `ATA030100SIP040211A.zup`) and a
  `SHA256SUMS` manifest — keep your own copy; this repo does not ship Cisco
  firmware.
- The ATA's MAC address (printed on the label, e.g. `00070e36e57b`).

## The 30-second version

1. **Flash SIP firmware:** run the upgrade coordinator on your host, then dial
   `100#<host-ip>*8000#` on the phone. The ATA resets into SIP mode.
2. **Serve a config profile** over TFTP; the ATA fetches it at boot (DHCP
   option 66/67, or the profile's `TftpURL`).
3. **Install Asterisk on OpenWrt**, add a peer for the ATA, dial a test
   extension.
4. **Later, when you change anything:** update settings live with an HTTP POST to
   `/dev`, force a config re-fetch with a `check-sync` NOTIFY, and read the ATA's
   own syslog. No power cycles needed.

## Step 1 — Meet the device

Factory ATAs run SCCP (Skinny) and wait for a CallManager; they do not fetch a
TFTP config in that mode.

- Off-hook, dial `123#` on the attached phone: the IVR speaks the firmware
  version.
- Note the MAC on the label: the ATA asks TFTP for `<mac>.cnf.xml` (lowercase),
  e.g. `ata00070e36e57b.cnf.xml`.
- **Entering IVR codes:** press the red **function button** on the ATA itself,
  then dial on the attached phone. If a value contains letters, multi-tap a key
  to cycle through its characters; `#` saves the current character, then press
  `#` again and `3` to save the whole string.
- Useful IVR codes: `123#` version, `81#` NPrintf (debug), `7387277` UI
  password, `792#` config dump (more in `docs/ata-sip-firmware-services.md`).

## Step 2 — Flash the SIP firmware (one time)

The ATA upgrades from a "PC upgrade server" over UDP 8000/8500, triggered from
the phone keypad. Use a dedicated/isolated segment: the coordinator serves DHCP
to the ATA and validates the image before sending anything.

1. Put the pinned image and its `SHA256SUMS` manifest side by side.
2. Run the coordinator (bare invocation is inert):

   ```sh
   python3 -B ata_flash.py --apply \
     --interface <iface> --address <host-ip> \
     --client-mac <ata-mac> \
     firmware/ATA030100SIP040211A.zup
   ```

3. When it prints its ready line, dial the shown `100#<host-ip>*8000#` on the
   phone. The ATA downloads, verifies and resets into SIP mode.
4. Keep your TFTP config server running: the ATA looks for a profile as soon as
   it boots.

Protocol, validation and network-safety checks: `firmware/FLASHING.md` and
`docs/ata-firmware-maintenance.md`.

## Step 3 — A good default config, fast

The ATA accepts the same settings in four forms (see
`docs/ata-config-formats.md`): a text profile compiled to binary, an XML file,
the web UI, or an HTTP POST. For a fresh device the fastest is a small text
profile:

```
#txt
UseTftp:1
TftpURL:0                # 0 = use the DHCP-provided TFTP server
CfgInterval:3600
Dhcp:1
UID0:100                 # SIP username
PWD0:0                   # password
GkOrProxy:192.168.2.10   # your Asterisk host
SIPPort:5060
SIPRegOn:1
```

Compile and serve it:

```sh
{ printf '#txt\n'; cat profile.txt; } > /tmp/profile.txt
python3 firmware/cfgfmt.py -t ata_03_01_00_sip_040211_1/ptag.dat /tmp/profile.txt /tmp/profile.bin
python3 telephony/tftp_profile.py --apply --serve <mac>.cnf.xml   # or any TFTP server
```

Point the ATA at your TFTP server with DHCP options 66 (server) and 67
(filename), or set `TftpURL` explicitly. It fetches at boot and every
`CfgInterval`.

## Step 4 — Asterisk on OpenWrt (build it in the QEMU twin first, then on the box)

### What the "twin" is

The twin is a **complete OpenWrt 24.10.8 + Asterisk 20.8.1 environment running
inside one QEMU guest** on your workstation. It is the safe place to build and
prove the PBX before touching real hardware:

- the guest boots the pinned OpenWrt x86/64 image with **QEMU user-mode
  networking** (`10.0.2.0/24`, guest `10.0.2.15`, no egress) and only
  loopback-forwarded SSH/serial — no bridges, taps or host network changes;
- Asterisk and its dependencies come from a **pinned package closure** (the
  "twin closure": 65 packages, SHA-verified) installed from a local `file://`
  feed, so the guest never downloads anything;
- the **same closure and configs are what you later install on the real APU**;
- the guest disk is a snapshot that is discarded after each run.

The harness also runs an in-guest SIP probe (REGISTER → INVITE → PCMU/RTP →
DTMF → BYE), so one green run proves the engine and the call path end to end
before any hardware is involved.

### Set up and run the twin

1. **Prerequisites:** `qemu-system-x86_64` and Python 3 on the host, plus the
   pinned OpenWrt image
   (`openwrt-24.10.8-x86-64-generic-squashfs-combined-efi.img`).
2. **Stage the closure bytes** (host-side, SHA-verified, no guest egress):

   ```sh
   python3 tests/openwrt/pin-fetch-twin-closure.py            # dry-run: checks all names
   python3 tests/openwrt/pin-fetch-twin-closure.py --stage    # writes the verified ipks
   ```

3. **Run the twin** (dry-run first; `--apply` is the state-writing flag and is
   operator-attended):

   ```sh
   tests/qemu/run-qemu-asterisk.sh            # dry-run: route preflight + plan
   tests/qemu/run-qemu-asterisk.sh --apply    # boot, provision, start, probe, harvest
   ```

   A successful run ends with the in-guest probe reporting a clean
   REGISTER/INVITE/RTP/DTMF/BYE round trip; logs are left in the twin work
   directory.

4. **Then the real box:** copy the same staged ipks to the OpenWrt APU and
   install them offline (`opkg install` from the local files — the box needs no
   internet), deploy the same Asterisk config, and start the service.

### Minimal config (identical in the twin and on the box)

- `sip.conf`: a peer matching the profile's `UID0`/`PWD0`, with
  `context=from-ata`.
- `extensions.conf`: a test extension, e.g. `exten => 600,1,Answer()` then
  `Echo()`.
- Start Asterisk and confirm it listens on UDP 5060.

`telephony/asterisk_conf.py` generates a working pair of files (chan_sip,
ulaw/alaw, a small IVR) if you prefer not to hand-write them.

## Step 5 — Register and call

- Watch the PBX: the ATA registers as `UID0` (e.g. `100`).
- From the phone, dial the test extension (e.g. `600`) and listen for the echo.
- If nothing happens, read the ATA's syslog (Step 6) before changing anything.

## Step 6 — Changing things later (no power cycles)

- **Change settings live:** HTTP POST the `/dev` form (the vendor `atapost`
  mechanism) — see `docs/ata-config-formats.md` §7.2 and
  `telephony/ata_dev_post.py`.
- **Force a config re-fetch:** send the ATA a SIP NOTIFY `check-sync` (from
  Asterisk: `sip notify check-sync <peer>`).
- **Read the ATA's own logs:** set `SyslogIP:<collector>.<port>` and
  `SyslogCtrl:0xFFFFFFFF` (live via the POST above). You get DHCP, TFTP, ARP and
  signalling events as UDP datagrams.
- **Reset only when a profile asks for it** (`cfgNeedReboot`); a power cycle is
  never required for configuration. Long DHCP leases make "cycle by DHCP"
  unreliable — prefer the two methods above.

## Step 7 — Optional: call from a browser (WebRTC)

- Asterisk WebRTC needs DTLS-SRTP. Stock OpenWrt `libopenssl` is built
  **without DTLS** (`no-dtls`), so SIP works but media fails with
  `no protocols available`. Fix: give only Asterisk a DTLS-enabled OpenSSL build
  via `LD_PRELOAD` — recipe in `tests/openwrt/openssl-dtls-build.sh`, deploy and
  rollback in `tests/apu2/apu2-asterisk-dtls-preload.sh`.
- The WebRTC page and pjsip config drafts live in `webrtc/`; verify end-to-end
  with `tests/apu2/webrtc-echo-test.mjs` (headless Chromium; no manual clicks).

## Common questions

**Which DHCP field points the ATA at my TFTP server?**
Option **66** (`tftp_server_name`) and/or option **150** (Cisco's TFTP server
address list) — both carry the TFTP host's IP. The ATA derives its own filename
from its MAC (`ata<mac>.cnf.xml`); option 67 is not required, though serving it
with the same filename is harmless.

**What format is the profile, and how do I create it?**
Two supported forms: an **XML** file (`<MAC>.cnf.xml`, the path this guide uses)
or the **binary TLV** profile (`#ata`) compiled from a text profile (`#txt`) with
`firmware/cfgfmt.py`. Both describe the same ~73 parameters. Examples in the
repo: `telephony/ATA00070E36E57B.cnf.xml` (XML) and
`telephony/ata00070e36e57b.txt` (text).

**Besides TFTP, how else can I push a configuration?**
- **HTTP POST to `/dev`** (the vendor `atapost` mechanism) — applies live, no
  reboot: `telephony/ata_dev_post.py`.
- The same form in a browser at `http://<ata>/dev`.
- **IVR keypad codes** (press the red function button first).
- A **profile-driven reset** for changes that require a reboot
  (`cfgNeedReboot`).

**What services does the device expose?**
An HTTP admin server (`/dev`, `/rtps`, `/clr0`, plus machine views `dev.xml`,
`service.xml`, `stat.xml`; access control via `LoginID0/1`, `UseLoginID` and the
`UIPassword` IVR code) and client roles: DHCP, TFTP, syslog
(`SyslogIP`/`SyslogCtrl`), NPrintf debug, DNS SRV, STUN, SIP and RTP.

**Is fax supported?**
The recovered configuration table has **no fax-specific parameter** — fax
travels as G.711 pass-through over the selected codec (PCMU/PCMA); there is no
evidence of T.38. If your original manual documents additional fax knobs, follow
the manual.

## Troubleshooting

| Symptom | Look at |
| --- | --- |
| No registration | ATA syslog (`SyslogIP`), PBX peer config, `GkOrProxy` |
| SIP fine, no audio | codec mismatch (ulaw/alaw), NAT/RTP ports, DTLS (Step 7) |
| Config not applied | profile form/filename, TFTP reachability, `CfgInterval` |
| Silent after flashing | TFTP profile must already be served when the ATA boots |

## Read more

- `docs/ata-config-formats.md` — all four config forms, compiling, live apply.
- `docs/ata-sip-firmware-services.md` — services, syslog, reboot paths.
- `docs/asterisk-integration.md` — moving the PBX from the QEMU twin to the device.
- `firmware/FLASHING.md` — firmware-service protocol and safety.
