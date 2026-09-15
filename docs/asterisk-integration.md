# Asterisk integration plan

Milestone: stand up Asterisk 20 on the APU (OpenWrt 24.10.8 x86_64) as the
engine that a bench-provisioned ATA186/188 registers and calls. This document is
the reviewed plan; it authorizes no APU, alarm, firewall, route, or production
change by itself. Local development and records live in this repository; APU
deployment is a separately approved, operator-attended maintenance checkpoint
(see TODO.md "Request maintenance checkpoint before any APU deployment").

The bench-proven SIP path is the reference the engine must accept: DHCP
OFFER/ACK with options 66/150 -> TFTP profile -> REGISTER to the service address
-> INVITE/PCMU -> two-way RTP, using extension 100 on the service host. The ATA
currently runs SIP 3.1(0) and is a SIP endpoint, so the primary integration is
SIP through the engine; no SCCP path is involved in the first milestone.

## Verified package feed (2026-09-14)

Source: `https://downloads.openwrt.org/releases/24.10.8/packages/x86_64/telephony/`
(confirmed present and identical version in `24.10-SNAPSHOT`). Asterisk is
`20.8.1-r1`. `chan_sip` is present but deprecated upstream and removed from
Asterisk 21; this pin is exactly why release 20.8.1-r1 is selected and upgrades
must not be unpinned.

| Package | ipk size | Phase |
| --- | ---: | --- |
| `asterisk` | 1160.3 KB | all |
| `asterisk-chan-sip` | 333.6 KB | SIP endpoint for the ATA |
| `asterisk-pjsip` | 579.5 KB | SIP alternative + WebRTC |
| `asterisk-res-rtp-asterisk` | 74.6 KB | RTP engine |
| `asterisk-codec-ulaw` | 3.0 KB | PCMU |
| `asterisk-codec-alaw` | 3.1 KB | PCMA |
| `asterisk-sounds` | 1879.9 KB | IVR prompts |
| `asterisk-app-read` | 4.3 KB | IVR `Read()` |
| `asterisk-app-audiosocket` | 3.9 KB | media to/from an agent adapter |
| `asterisk-app-externalivr` | 11.0 KB | AGI-style external IVR |
| `asterisk-res-agi` | 31.2 KB | AGI dependency |
| `asterisk-res-http-websocket` | 16.3 KB | WebRTC/ARI WebSocket |
| `asterisk-res-ari*` | ~100 KB | channel/event APIs |
| `asterisk-chan-skinny` | 56.3 KB | historical SCCP probe only, not deployed |

ipk size is the download, not the installed footprint (opkg unpacks modules and
dependencies such as `libpjproject`/`libsrtp`). Installed space on the APU must
be re-measured against overlay free space at the maintenance checkpoint. The APU
overlay was ~33 MiB free at audit and has never been cleaned; disk budget is an
open follow-up for the operator, assumed solvable by cleaning and by keeping the
installed module set minimal.

## Local (off-repo, non-APU) stages

These run on the developer Mac or in the isolated QEMU guest, never on the APU,
until the maintenance checkpoint.

1. **Pin and build the engine locally.** Check out `asterisk-20.8.1` source with
   `chan_sip`, `res_rtp_asterisk`, `app_read`, `app_audiosocket`,
   `app_externalivr`, AGI, and minimal codecs; build without OPUS/video. This is
   the host probe that validates config/module behavior the OpenWrt package also
   ships. No engine runs on the APU yet.
2. **Add a local integration test harness.** Reuse the bounded loopback SIP/RTP
   fixtures (`telephony/sip_bench_proxy.py`, `rtp_external_media.py`, `g711.py`)
   so an automated peer can REGISTER + INVITE against the locally built engine on
   loopback and pass/expose 200 OK, PCMU, RTP media, DTMF, and hangup. Bounded
   run/call windows; no ATA needed.
3. **Record an exact OpenWrt package manifest.** The table above plus the opkg
   dependency set it resolves on 24.10.8 (from `opkg depends`), pinned to the
   release feed. This is the reviewed, non-secret release manifest used at the
   maintenance checkpoint.

## Bench topology for the engine (reference, used at the checkpoint)

```
ATA186 192.168.2.10 (SIP 3.1.0, extension 100)
   |  DHCP 66/150  +  TFTP ATA00070E36E57B.cnf.xml  +  SIP 5060  +  RTP
   v
Asterisk engine
   address 192.168.2.2  (bench service host)
   UDP 5060 SIP, RTP from a bounded engine-local port range
```

The bench ATA profile already pins `GkOrProxy=192.168.2.2`, `SIPRegOn=1`,
`SIPRegInterval=60`, `UID0=100`, `SIPPort=5060`, `MediaPort=16384`, PCMU/PCMA.
That exact profile is what the APU-era DHCP+TFTP provisioning would serve again;
nothing about provisioning changes in this milestone.

Identifiers in generated configs are deliberately stable and non-secret
(extension `100`, allowlisted caller) so the config artifact is reviewable and
reproducible, matching the bench profile where credentials are empty strings.

## Engine configuration artifacts (generated in this repo)

`telephony/asterisk_conf.py` generates a private, bounded config tree for the
bench topology, dry-run by default:

- `sip.conf`: `chan_sip` general settings (bind 192.168.2.2:5060, allowguest=no),
  one `friend` peer `100` for ATA `192.168.2.10`, PCMU/PCMA allowlist, RFC2833
  DTMF, no external access, no credentials, bounded REGISTER/qualify behavior.
- `extensions.conf`: `[from-ata]` context with extension 100 = Answer +
  Playback (Phase 2/3 extend to IVR/audio socket).
- `modules.conf`: load only listed modules; no autoload of arbitrary modules.
- `rtp.conf`: bounded RTP engine port range for the ATA peer.
- `ASTERISK.md` inside the generated directory: non-secret run notes.

Generation writes only new files under a `mode 0700` directory; the default is a
dry-run that prints would-be paths. `--apply DIR` writes into an existing or
new empty directory. No engine is run, no socket is bound, and nothing is
written to the APU.

## WebRTC and the ari/engine twin

WebRTC is not needed for the ATA (the ATA is an analog phone over SIP). When
remote/soft-phone access is later wanted, `pjsip` + `res-http-websocket` + `ARI`
would run as a separate bounded engine twin on the APU, never on the same ATA
peer or a public face; the ATA SIP path and the WebRTC twin stay distinct so one
cannot compromise the other. That work is deferred; this milestone only pins the
module set so it stays installable.

## Phases and gates (all locally verified first; hardware gate at the end)

Phase 1 – Engine + SIP interop
- [ ] Local build of pinned Asterisk 20.8.1 with chan_sip and the modules above.
- [ ] Local loopback qualification: automated REGISTER/INVITE/PCMU/RTP/DTMF
      round trip against the local engine, bounded, no ATA.
- [ ] Opkg dependency/package manifest pinned and reviewed.
- [ ] Hardware gate at maintenance checkpoint: ATA REGISTER to the engine on the
      isolated bench, dial 100, hear the engine prompt/tone, two-way RTP.
Phase 2 – IVR prompts
- [ ] `asterisk-sounds` installed; extension 100 plays prompts; DTMF navigation
      through `Read()` bounded to one numeric response.
Phase 3 – External media
- [ ] `audiosocket`/`externalivr` bridge from the call to a bounded local agent
      adapter, PCMU end-to-end, recorded handle/no handle only (no audio store).
Phase 4 – Engine twin (optional, deferred)
- [ ] Separate pjsip/WebRTC twin for remote clients; isolated and allowlisted.

## Rollback and safety

- No change to the APU, alarm, routes, firewall, DNS, VPN, or production in this
  milestone's local batches. APU install is a separate operator-attended step.
- Local stages bind only loopback; the bench hardware gate binds only the
  isolated direct bench addresses and only during the operator-attended window.
- No automatic redial, replay, reprint, or media storage after ambiguity.
- If the APU install/rollback is attempted later, restore the previously
  deployed state and check for concurrent modification before reverting.

## Records of this plan

- TODO.md: date-stamped milestone items (this plan is not a hardware claim).
- WORKLOG.md: append-only entry for feed verification and artifact creation.
- docs/handoff.md: current local state and next safe action.