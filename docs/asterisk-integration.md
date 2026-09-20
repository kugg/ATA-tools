# Asterisk: from the QEMU twin to the OpenWrt device

This page is the detailed move instruction for the PBX: build and prove the
whole thing in the digital twin (a QEMU guest), then install the identical
package closure and configuration on the real OpenWrt device and test it. The
short path is in `docs/getting-started.md`; this page is the twin → device
handoff.

Nothing here needs internet on the device: every package is staged and
hash-verified on your host first.

## What you need

- **Host:** `qemu-system-x86_64`, Python 3, the pinned OpenWrt image, and the
  pinned package closure.
- **Device:** OpenWrt 24.10.8 x86/64 with a writable overlay (the closure needs
  roughly 40 MiB installed; leave headroom for logs).
- **ATA** already flashed to SIP and provisioned — see `docs/getting-started.md`.

## Part 1 — Build and prove it in the twin

1. Stage the closure bytes on the host (SHA-verified; no guest egress):

   ```sh
   python3 tests/openwrt/pin-fetch-twin-closure.py            # dry-run: checks all names
   python3 tests/openwrt/pin-fetch-twin-closure.py --stage    # writes the verified ipks
   ```

2. Run the twin harness (dry-run first; `--apply` boots and provisions the
   guest):

   ```sh
   tests/qemu/run-qemu-asterisk.sh
   tests/qemu/run-qemu-asterisk.sh --apply
   ```

3. **Success criteria:** the in-guest probe reports a clean
   REGISTER → INVITE → PCMU/RTP → DTMF → BYE round trip, the engine logs show no
   crashes, and the run harvests its logs to the twin work directory.

The twin's safety model (user-mode networking, no egress, snapshot disk) and
what the "twin closure" means are described in `docs/getting-started.md`
Step 4.

## Part 2 — Move it to the device

1. **Check capacity** on the device:

   ```sh
   df -h /overlay
   ```

2. **Copy the staged ipks** to the device (the closure is small; `/tmp` is RAM
   on OpenWrt, so use the overlay if you are tight on RAM):

   ```sh
   scp -O <staged-ipks>/*.ipk root@<device>:/tmp/twin-ipks/
   ```

3. **Verify the hashes on the device** against the manifest you staged — the
   same bytes the twin proved:

   ```sh
   cd /tmp/twin-ipks && sha256sum -c <manifest>.sha256
   ```

4. **Install offline** (local files only; the device never fetches):

   ```sh
   opkg install /tmp/twin-ipks/*.ipk
   ```

   If opkg refuses an identical version, re-verify the hash first, then use
   `opkg install --force-reinstall <ipk>`.

5. **Deploy the engine configuration** into `/etc/asterisk/` (`sip.conf`,
   `extensions.conf`, `modules.conf`, `rtp.conf`). `telephony/asterisk_conf.py`
   generates a working set for the bench topology (dry-run by default):

   ```sh
   python3 telephony/asterisk_conf.py --apply /tmp/engine-conf \
     --address <device-ip> --ata <ata-ip>
   ```

   Back up any stock files first (e.g. `/etc/asterisk/backup-stock/`).

6. **Start and check** the service:

   ```sh
   /etc/init.d/asterisk enable
   /etc/init.d/asterisk start
   netstat -tuln | grep 5060
   ```

## Part 3 — Test on the device

1. Point the ATA's profile at the device (`GkOrProxy=<device-ip>`) and let it
   register — its syslog shows the registration events when `SyslogIP` is set.
2. From the phone, dial the test extension (the generator's `[from-ata]`
   context: `100` → prompt/IVR, `101` → agent) and confirm audio both ways.
3. Optional: verify from a browser with the automated test
   (`tests/apu2/webrtc-echo-test.mjs`).
4. When it fails, look at the engine log, the ATA syslog, and the troubleshooting
   table in `docs/getting-started.md`.

## Part 4 — Optional: WebRTC (browser calls)

- Install the WebRTC extras (pinned in
  `telephony/openwrt-wbrt-manifest-24.10.8.txt`): `asterisk-pjsip`,
  `asterisk-res-pjproject`, `asterisk-res-sorcery`, `asterisk-res-srtp`,
  `libsrtp2-1`.
- OpenWrt's OpenSSL is built **without DTLS**, so WebRTC media fails until
  Asterisk gets a DTLS-enabled OpenSSL via `LD_PRELOAD`: build it with
  `tests/openwrt/openssl-dtls-build.sh`, deploy with
  `tests/apu2/apu2-asterisk-dtls-preload.sh`.
- The page and pjsip drafts are in `webrtc/`; verify with
  `tests/apu2/webrtc-echo-test.mjs`.

## Rollback

- Stop the service and restore the configuration backups.
- Remove the installed packages only if you want the space back — the closure is
  additive.
- The WebRTC preload has its own rollback:
  `tests/apu2/apu2-asterisk-dtls-preload.sh --rollback`.

## Appendix — the pinned closure

The verified package set is pinned in
`telephony/openwrt-twin-manifest-24.10.8.txt` (65 packages), with the WebRTC
delta in `telephony/openwrt-wbrt-manifest-24.10.8.txt`. The main components:

| Package | Role |
| --- | --- |
| `asterisk` | engine core (20.8.1-r1) |
| `asterisk-chan-sip` | SIP endpoint for the ATA (chan_sip is removed in Asterisk 21 — keep the pin) |
| `asterisk-res-rtp-asterisk` | RTP engine |
| `asterisk-codec-ulaw`, `asterisk-codec-alaw` | PCMU / PCMA |
| `asterisk-sounds`, `asterisk-app-read` | IVR prompts and `Read()` |
| `asterisk-app-audiosocket`, `asterisk-app-externalivr`, `asterisk-res-agi` | external media/agent bridges |
| `asterisk-pjsip`, `asterisk-res-srtp`, `asterisk-res-http-websocket` | WebRTC (optional) |

ipk sizes are downloads, not installed footprint — opkg unpacks modules and
dependencies (for example `libpjproject` and `libsrtp`).
