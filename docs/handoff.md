# Handoff

Updated 2026-09-15. Read TODO.md and WORKLOG.md before continuing. The final section
supersedes older firmware-gate statements retained below as historical context.

## Asterisk local engine + loopback harness pass (2026-09-15)

Local work only: no APU/alarm/hardware change.

Pinned Asterisk 20.8.1 built natively (arm64/clang) in
`/var/folders/.../T/opencode/asterisk-build` (private, untracked) with the
pinned module set; all 27 modules Running. Build Darwin fixes (makeopts
CC=clang, arm64 OpenSSL 3 at /opt/homebrew, bundle1 removal, strcasecmp_l,
ast_poll, ASTMM_LIBC=2, pjproject undef) are recorded step by step in
WORKLOG 2026-09-15 entries; the engine binary links Homebrew libssl/libcrypto.

Loopback qualification PASSES: `telephony/sip_loopback_probe.py --apply`
(UDP 127.0.0.1:15060/16384) achieves REGISTER 200 OK -> INVITE 200 OK + ACK ->
49 PCMU RTP packets (hello-world prompt) -> RFC2833 DTMF -> BYE 200 OK;
engine executed Answer/Playback/Hangup (1 call processed). Generator peer is
now `host=dynamic` + `permit=<ata>` (chan_sip rejects REGISTER from static
hosts) and uses `defaultuser`; probe requires a From tag (pedantic checking).
Repo suite: 141 unit tests OK. Runtime configs live in the private run tree
`.../T/opencode/asterisk-run/etc/asterisk` (sip/extensions/modules/rtp +
private asterisk.conf/logger.conf with debug enabled).

Known open items:
- Engine is currently a plain background daemon (pid from
  `pgrep -f "sbin/asterisk -f"`); kill it before changing configs, then
  relaunch with the private master config. It is NOT under lldb anymore.
- `res_crypto.so`/`res_http_websocket.so` install to the Darwin
  `Library/Application Support/Asterisk/Modules` path and were copied into the
  astmoddir used by the engine; done by hand, would rerun after reinstall.
- Phase 1 remains open on the opkg dependency/footprint manifest (operator
  follow-up) and the hardware gate at the maintenance checkpoint.
- Do not treat the probe pass as proof of ATA/hardware behavior; mock-free but
  host-only.

Next safe local action: Phase 3 external media (audiosocket/externalivr)
against the host probe, or pin the opkg dependency set; hardware gate is
operator-only.

## Hardware gate PASSED (2026-09-15, operator-attended)

The ATA 186 (SIP 3.1.0, UID 100) registered to the locally built Asterisk
20.8.1 running on the bench address 192.168.2.2 (en28) and completed the
full IVR flow on the analog handset: dial 100 -> prompt playback -> RFC2833
digit 5 through Read() -> confirmation tone -> clean BYE. Engine-side SIP
capture (console3.log in the private bench tree) shows the Cisco ATA186
v3.1.0 user agent, real SDP negotiated (PCMA/PCMU/G723 + telephone-event),
remote RTP 192.168.2.10:16384. Bench engine lives in
/var/folders/.../T/opencode/asterisk-bench (private master asterisk.conf
with plain `=` syntax; dynamic peer with permit=192.168.2.10; file logger
quirk known: console logging used as fallback). The loopback engine also
remains available (asterisk-run tree). See WORKLOG for the full entry and
the two bench-configuration lessons ('=' vs '=>' in [directories], explicit
res_timing_pthread with autoload=no).

Next milestone: Phase 3 external media (audiosocket/externalivr) — requires
the operator present; wire the existing call to a bounded local agent while
keeping this IVR path intact.

## Phase 3 external media PASSES (2026-09-15, operator-attended)

telephony/audiosocket_agent.py (bounded AudioSocket agent, loopback-only,
no audio persisted) bridges the live ATA call: dial 101 on the handset
bridges the channel to 127.0.0.1:9100; the agent streams a paced, phase
continuous 660 Hz tone (2 s), counts inbound frames/energy, then terminates
cleanly. Operator confirms call audio quality through the bridge; unit
suite 146 OK. Three audio defects were root-caused in the agent (queue
burst truncation, sleep-granularity pacing, per-frame phase clicks) and
fixed; see WORKLOG. Dialplan extension 101 + module set handled by
telephony/asterisk_conf.py (AUDIOSOCKET_* constants). Cosmetics: engine
logs an app_audiosocket ERROR when the agent closes the session; bench
file logger quirk persists (console logging in use).

Bench state: engine (asterisk-bench tree) and agent both still running;
dial 100 = IVR gate, dial 101 = external-media agent. Remaining scope for
the operator: OpenWrt module manifest check before APU deployment and the
choice of what production agent (if any) sits behind the AudioSocket side.

## Phase 2 IVR passes + DTMF-path crash fix (2026-09-15)

Phase 2 is complete and pushed (commits 0fc134a, 219e9f9, 66bffcd): the
generated dialplan now does Answer -> Playback(hello-world) -> Read(one
digit) -> GotoIf(digit=5) -> Playback(confirmed) -> Hangup; prompts are
synthesized by telephony/gen_ivr_prompts.py. The loopback probe negotiates
telephone-event/8000, sends one RFC2833 '5' with a real incrementing RTP
sequence, and passes on confirmation audio. 141 unit tests OK.

Key operational lesson (also applies to OpenWrt with autoload=no):
res_timing_pthread.so MUST be in the explicit module list — a missing timing
thread gives every channel a NULL timer and the first accepted RFC2833 DTMF
END segfaults ast_timer_set_rate during Read() (local crash report
asterisk-2026-09-15-221726.ips, not in the repo).

Engine state: plain background daemon (`pgrep -f "sbin/asterisk -f"`)
against the private run tree; modules.conf now includes app_read and
res_timing_pthread.

## Asterisk integration plan and local config generator (2026-09-14)

Local work only: no APU/alarm/hardware change in this batch.

Verified the OpenWrt 24.10.8 x86_64 telephony feed ships Asterisk 20.8.1-r1
plus the pinned module set (exact ipk sizes). Plan in
`docs/asterisk-integration.md`; pinned manifest in
`telephony/openwrt-asterisk-packages-24.10.8.txt`; dry-run config generator
`telephony/asterisk_conf.py` + `tests/unit/test_asterisk_conf.py` (12 tests).
The generated tree is a private chan_sip config for the bench topology
(extension 100, ATA 192.168.2.10 -> 192.168.2.2), no credentials, no socket or
engine run by the generator. Full unit suite 131 OK.

Known open items:
- chan_sip is removed in Asterisk 21, so 20.8.1 stays pinned; asterisk-chan-skinny
  remains an SCCP probe only (D013), not part of this SIP milestone.
- APU overlay disk budget (~33 MiB free, machine never cleaned) is the operator's
  follow-up; ipk size is download size, not installed footprint.
- Next local action: build pinned Asterisk 20.8.1 on the developer host and run
  the loopback integration harness against it; the hardware gate is a separate
  operator-attended maintenance checkpoint.

## Production state

No APU/alarm changes in this batch. Printer continues using previously deployed
static bind configuration. Local lifecycle changes are NOT deployed. Ephemeral
no-hardware QEMU qualification now runs the actual i386 ATA firmware server through
loopback-only UDP forwards; it made no USB/device contact. ATA ringing/media and
real Chatterbox generation remain unverified.
Do not rerun historical bench commands just because scripts are present.

## Local work

Gateway durable documentation/task files now exist. Git is initialized on `main`
with no remote; transient staging/commit status must be read from Git. A bounded offline ATA186 SCCP fixture now
exists in `telephony/skinny_fixture.py`; it opens no socket and is not a call
server, device test, or engine-selection result. Artifact/deployment/runtime
acceptance remains pending.

This follow-up changed `telephony/skinny_fixture.py`,
`tests/unit/test_skinny_fixture.py`, `docs/telephony-fixture.md`, `README.md`,
`docs/decisions.md`, task003/task004, durable records, and the local SCCP security
report. Printer-local changes are recorded in its `OPENWRT-WORKLOG.md` and include
the package/init lifecycle, QEMU safety scripts and their tests.
Printer repo modifications: APU-DEPLOYMENT.md; packaged init and config; new
openwrt/scripts/test_printer_lifecycle.py and PRINTER-LIFECYCLE.md. Its ignored
OPENWRT-WORKLOG.md was redacted, repaired after accidental condensation, and records
a four-line historical omission. No secret should be restored to repair wording.

Final independent commands (working directory noted):

| Directory | Command | Result |
| --- | --- | --- |
| ata | `python3 -B -m unittest discover -s tests/unit -v` | 22 PASS, 0.239s |
| ata | `python3 -B -m unittest tests.unit.test_skinny_fixture -v` | 16 PASS, 0.001s |
| printer | `python3 -B -m unittest discover -s openwrt/scripts -p 'test_*.py' -v` | 41 PASS, 5.462s |
| printer | `python3 -B -m unittest discover -s tests -v` | 57 PASS, 0.884s |
| printer | `sh -n` for packaged init, QEMU harness, and WireGuard helper | PASS |
| both | `git diff --check` and per-untracked-file `git diff --no-index --check` | PASS; exact pipeline in results report |
| ata | `git check-ignore .venv/bin/python lease.json ata-config-1788813827812482000.json ata-config-1788813991074715000.json` | All four ignored |

Count-only base64-key-shaped scans on intended text returned no matches; this is
not comprehensive secret/history erasure. See reports/local-results-2026-09-08.md
for exact scan commands and evidence limits. No credentials were staged.

Final source hardening: private root-owned snapshot inodes validated on all paths,
atomic publication/revocation and synchronous cleanup, fixed interface validation
in both modes, scoped new-spool failure cleanup. Bench scripts default offline;
ring HTTP has 64KiB bound plus 10s total Unix process timer and private backups.
It remains an experimental whole-form best-effort restore tool, not deployment.

The local printer follow-up reclaims only one verified root-owned mode0600
`.snapshot.??????` temporary on explicit publication; unsafe, ambiguous or event
paths fail closed. Package release2 declares `coreutils-stat`. QEMU source now has
numeric route/Docker overlap checks, private stage records, per-run route/NWI
baselines, restricted user networking and guest-only WireGuard safeguards. No VM
was launched, so none of those controls prove target or host-runtime behavior.

Oplane model477779bb-8e51-4093-9812-7003c3f6cd00: all40 original cases regraded,
26 PASS/10 FAIL/4 N/A; source properties3455,3456,3458 IMPLEMENTED, lifecycle3457
NOT_IMPLEMENTED. Current model states updated. See final security report.
Mocks do not establish procd behavior. Real UCI export/eval, event serialization,
replacement/withdrawal and process cleanup remain unproven.

Oplane model `0067aeb3-5c6e-4ea8-b348-1a49f821a617` covers the new local SCCP fixture.
Requirements `OPLANE_REQ-00003471`, `OPLANE_REQ-00003472`, and
`OPLANE_REQ-00003473` are IMPLEMENTED for bounded frame handling, terminal
error isolation, and exact ATA186 identity/type validation. Streaming fragments are
valid until `finish()` establishes EOF; no transport, QEMU, ATA or production test
is implied. See `reports/security-2026-09-08-sccp-fixture.md`.

Next safe action: establish pinned OpenWrt SCCP/IAX2/external-media compatibility,
then adapt the offline fixture to one selected engine in an approved isolated
loopback-only QEMU test. Keep printer lifecycle3457 target-procd/event-pressure and
QEMU acceptance separate. Do not bypass runtime_confinement_verified to start an
integration test. No IPK rebuilt; no deployment/SSH/service/network mutation
performed in this batch. No model inference, power cut or physical print/ring test.

## Refactor batch (2026-09-09)

New: `refactor/cfgfmt.py`, `refactor/prserv.py`, `refactor/sata186us.py`
plus `refactor/README.md` and 70 tests in `refactor/tests/`. These are
Ghidra + Docker-i386 verified Python ports of the vintage
`cfgfmt.linux` / `prserv.linux` / `sata186us.linux` support tools; the
vintage directory was not modified (the user's
`ata_03_01_00_sip_040211_1/refactor/swedish` tone file was used
read-only as a regression vector).

Verification (working directory `ata`, i.e. repo root):

| Command | Result |
| --- | --- |
| `python3 -B -m unittest refactor.tests.test_cfgfmt refactor.tests.test_prserv refactor.tests.test_sata186us` | 70 PASS |
| `python3 -B -m unittest discover -s tests/unit` | 36 PASS (unchanged) |
| 41-case Docker differential (exit/stdout/stderr/files vs originals) | 0 mismatches |
| `sip_example.txt` and Swedish vectors, original vs port | byte-identical |
| per-file `git diff --no-index --check` on new files | PASS |

Open gates: Oplane threat model for the new UDP/parser code (required
before any commit including `refactor/`); documented port limits in
`refactor/README.md` (bad-size/split crash safety, `*Freq` float LSB,
`kbox` bytes [8:12], `.sbin` RSA). No commit requested or made.

## Safe refactor and ATA firmware gate (2026-09-09)

Before: the historic ports still exposed compatibility behavior unsuitable for
device maintenance: wildcard firmware admission/bind paths, arbitrary output
overwrites, unconstrained profile includes, and key-bearing verbose logs. The
local SIP bundle was structurally unassessed as a future target, and no verified
rollback artifact was available.

Change: `refactor/sata186us.py` now defaults to no I/O; `--inspect` validates a
bounded local image only; `--apply` requires a private policy pinned to
`192.168.2.2`/`192.168.2.10`, exact current-request metadata, a target, and a
distinct rollback image. `cfgfmt.py` now bounds custom files, confines includes,
redacts verbose keys, and atomically creates new `0600` outputs without overwrite.
`prserv.py` remains loopback metadata-only. Added
`docs/ata-firmware-maintenance.md` and sanitized local evidence.

Verification (repository root):

| Command | Result |
| --- | --- |
| `python3 -B -m py_compile refactor/*.py refactor/tests/*.py` | PASS |
| `python3 -B -m unittest refactor.tests.test_cfgfmt refactor.tests.test_prserv refactor.tests.test_sata186us -v` | 59 PASS; UDP tests use ephemeral `127.0.0.1` only |
| `python3 -B -m unittest discover -s tests/unit -v` | 36 PASS |
| `git diff --check` and per-file `git diff --no-index --check` | PASS; repository files are untracked |
| `python3 -B refactor/sata186us.py --inspect ata_03_01_00_sip_040211_1/ATA030100SIP040211A.zup` | Valid internal envelope; SHA-256 `b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5`; platform `0x301`, proto `0x0400`, version `0x0301` |
| `python3 -B refactor/sata186us.py --inspect ata_03_01_00_sip_040211_1/transition.zup` | Valid internal envelope; SHA-256 `9cf97b172f4d3422dfa54ad9708a5e110637130963d9f1bc1f1e70c1bbfcc278`; platform `0x301`, proto `0x0400`, version `0x0200` |

Historical firmware verdict at that point: the local SIP 3.1.0 artifact had only
internal integrity and community-archive corroboration, and the current SCCP image
was not local. This conservative verdict is superseded by the operator decision and
qualified QEMU path in the final section.

Current local/production state: no ATA-facing listener, ATA request, flash,
configuration write, Docker launch, QEMU launch, APU action, or production change
occurred in this follow-up. No Oplane action or commit was requested. Historical
Docker differential claims apply only to legacy-format reverse engineering, not the
deliberately changed fail-closed wrappers.

Historical next action is superseded by the final section. `transition.zup` remains
outside the selected path and automatic retries remain disabled.

## DHCP Interface Observation and CSCsd44357 Assessment (2026-09-09)

The user reported that the direct bench interface is now `en28` and personally ran
the bounded responder with `--apply`. Its output showed an OFFER and ACK for
`192.168.2.10`; this demonstrates server-side request handling only, not that the
ATA installed the lease or is reachable. The agent did not run `--apply`, send
packets, inspect the ATA, or change host networking. `dhcp.py` already used `en28`
when inspected; only its stale interface-specific docstring was generalized. The optional Scapy
dependency remains lazy and apply-only through `import_module("scapy.all")`.

Archived Cisco guest content for `CSCsd44357` identifies an ATA186/ATA180-series
CUCM auto-registration failure when the TFTP-served XML configuration exceeds 4 KiB;
it lists SCCP 3.2(3) as known affected. A Cisco employee's public response says the
fix is in 3.2(4). The observed image is the matching SCCP 3.2(4) load, so this is not
a current-source release blocker. It does not characterize the unapproved SIP 3.1.0
target or prove a direct `kbox` transfer/recovery path. Any future CUCM/TFTP path
must retain selected-version evidence, begin with a configuration no larger than
4096 bytes, and prove its own transfer result under separate approval.

Changed files: `dhcp.py`, `TODO.md`, `docs/assumptions.md`,
`docs/ata-firmware-maintenance.md`, `docs/operations.md`,
`reports/local-results-2026-09-09-refactor-firmware.md`, this handoff, and
`WORKLOG.md`.

Verification (repo root):

| Command | Result |
| --- | --- |
| `python3 -B -m py_compile dhcp.py` | PASS |
| `python3 -B dhcp.py` | PASS; dry run, no sockets opened |
| `python3 -B -m unittest tests.unit.test_bench_safety -v` | 8 PASS |
| `python3 -B -m unittest discover -s tests/unit -v` | 36 PASS |
| `/var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/ata-bench-venv/bin/python -B -c 'from importlib import import_module; print(import_module("scapy.all").__name__)'` | PASS; prints `scapy.all`, no packets sent |
| `git diff --check` and per-file `git diff --no-index --check` | PASS; repository remains untracked |

Historical local state: the user-operated isolated DHCP responder was the only new
device-facing event. No firmware transfer or production change occurred. Its former
artifact-gate conclusion is superseded by the final section.

## No-Response KBOX Capture Attempt (2026-09-09)

Changed files: `refactor/sata186us.py`, `refactor/tests/test_sata186us.py`,
`refactor/README.md`, `TODO.md`, `docs/assumptions.md`,
`docs/ata-firmware-maintenance.md`,
`reports/local-results-2026-09-09-refactor-firmware.md`, this handoff, and
`WORKLOG.md`.

The new explicit `--capture` mode binds only `192.168.2.2:8000`, accepts a
policy-safe KBOX header only from `192.168.2.10`, retains no raw packet, sends no
UDP response, and exits after one valid header, 32 packets, or 60 seconds. It is
not an image-transfer mode and rejects firmware-policy/image inputs.

Immediately before the approved one-shot run, read-only `netstat -rn` showed exact
host routes for `192.168.2.2` and expected peer `192.168.2.10` on `en28`, with the
expected ATA MAC; `netstat -an -p udp` showed no port-8000 listener. The command
`python3 -B refactor/sata186us.py --capture --capture-seconds 30` bound and printed
that it would send no responses, then ended without valid metadata. It sent no
packet. The user confirmed the handset trigger missed the capture window, so this
does not establish an ATA protocol or hardware result. Do not retry automatically.

Verification (repo root):

| Command | Result |
| --- | --- |
| `python3 -B -m py_compile refactor/sata186us.py refactor/tests/test_sata186us.py` | PASS |
| `python3 -B -m unittest refactor.tests.test_sata186us -v` | 19 PASS |
| `python3 -B -m unittest refactor.tests.test_cfgfmt refactor.tests.test_prserv refactor.tests.test_sata186us -v` | 63 PASS |
| `python3 -B -m unittest discover -s tests/unit -v` | 36 PASS |
| `python3 -B refactor/sata186us.py` | PASS; dry run, no sockets/files opened |
| `git diff --check` and per-file `git diff --no-index --check` | PASS; repository remains untracked |

Historical local state: the capture-only socket emitted no response and no device
change occurred. Its former artifact-gate and policy-creation plan is superseded by
the final section.

## KBOX Capture Diagnostics and Peer-Preflight Follow-Up (2026-09-09)

Before: one approved KBOX capture had missed its handset trigger. A second explicitly
approved, synchronized 30-second no-response capture subsequently ended without a
valid header. Its prior output could not distinguish no datagrams from packet
rejection. No transfer, reply, configuration, flash, or other ATA change occurred.

Change: `refactor/sata186us.py --capture` now emits only aggregate failure counts:
total datagrams, expected-peer and other-peer traffic, oversized packets, invalid
formats, and packet-limit reach. It still retains no packet content or source address
and has no response path. Added a regression test for aggregate-only diagnostics and
updated firmware/TODO/assumption/results records. Historical Cisco SCCP 3.0
cross-protocol TFTP/`upgradecode` material is recorded as a non-actionable research
lead, not evidence for SCCP 3.2.4.

Verify (repository root):

| Command | Result |
| --- | --- |
| `python3 -B -m py_compile refactor/sata186us.py refactor/tests/test_sata186us.py` | PASS |
| `python3 -B -m unittest refactor.tests.test_sata186us -v` | 20 PASS |
| `python3 -B -m unittest refactor.tests.test_cfgfmt refactor.tests.test_prserv refactor.tests.test_sata186us -v` | 64 PASS |
| `python3 -B -m unittest discover -s tests/unit -v` | 36 PASS |
| `git diff --check` and per-file `git diff --no-index --check` for follow-up files | PASS; the repo-wide untracked scan reports pre-existing CRLF/trailing whitespace in untouched vintage references |

Current local/production state: the user later requested a third window using stored
DTMF, but the agent did not open it. Read-only `netstat -rn` showed the local `.2`
route on `en28` but no current `.10` neighbor/MAC; `netstat -an -p udp` showed no
port-8000 listener. The DHCP lease/peer state is therefore ambiguous. No DHCP action,
listener, ATA packet, flash, APU action, or production change occurred in this
follow-up.

Next safe action: the user may re-establish the bounded direct-bench lease, then the
agent must repeat read-only exact-peer/port preflight and obtain a fresh explicit
capture authorization. Do not redial or open a listener until those conditions hold.

## Third KBOX Capture and Parser-Stage Diagnostics (2026-09-09)

Before: the expected `.10` neighbor had disappeared after the earlier DHCP lease.
The user re-ran the bounded `dhcp.py --apply` command and reported an OFFER/ACK for
`.10`, then explicitly requested another capture using the handset's stored DTMF.

Live observation: read-only `netstat -rn` showed `192.168.2.10` at exact ATA MAC
`00:07:0e:36:e5:7b` on `en28`, the local `.2` route remained present, and
`netstat -an -p udp` showed no UDP 8000 listener. The approved command
`python3 -B refactor/sata186us.py --capture --capture-seconds 30` received three
datagrams from the exact peer. All three failed strict KBOX parsing; other-peer and
oversized counts were zero. It retained no packet and sent no response.

Change: because that run's aggregate `invalid=3` cannot identify the rejected stage,
the capture now reports fixed counters for non-KBOX, version, framing, checksum, and
metadata rejection. It still records no packet bytes or source addresses, and the
transfer parser remains strict. Offline vintage-server decompilation shows that the
old receive path checks the declared payload checksum without requiring exact UDP
datagram length, making trailing padding a hypothesis rather than a proven diagnosis.

Verification (repository root):

| Command | Result |
| --- | --- |
| `python3 -B -m py_compile refactor/sata186us.py refactor/tests/test_sata186us.py` | PASS |
| `python3 -B -m unittest refactor.tests.test_sata186us -v` | 21 PASS |
| `git diff --check` | PASS |

Current local/production state: the third listener has closed. No firmware response,
transfer, configuration write, flash, APU action, or production change occurred.
Exact request metadata remains unknown. Do not retry automatically or relax framing;
another capture requires fresh explicit approval and exact-peer/port preflight.

## Flash-tool QEMU handoff (2026-09-09)

New: `refactor/FLASHING.md` describes the policy-gated `sata186us.py` modes,
transfer mechanics, QEMU rules, and the gated runbook for a follow-up model.
Verified this turn: dry run, `--inspect` on both local images, 21 sata unit
tests PASS, whitespace check PASS. No sockets, launches, or device contact.

Historical note: the stock-guest/direct-host proposal described here was replaced by
the direct-USB, direct-boot QEMU implementation in the final section.

## QEMU tools launcher (2026-09-09)

New: executable `tests/qemu/run-qemu-tools.sh` starts one isolated guest
with `refactor/` shared inside read-only (9p tag `refactor`). User-mode
networking with `restrict=on`, no host forwards, snapshot-mode disk,
dry-run default, bounded runtime, read-only route/neighbor snapshots with
numeric `10.0.2.0/24` overlap review, stale-instance guard, post-run drift
report. Verified: `sh -n`/`bash -n`, `--help`, dry-run, failure exits,
overlap unit cases; no VM launched, no host/network/device change.
In-guest follow-ups once booted: mount the 9p share, run `--inspect` and
the unit suite over guest loopback only. No ATA attached, ever, under this
script.

Follow-up: the launcher now also shares `ata_03_01_00_sip_040211_1/`
read-only (9p tag `legacy`, `--legacy` override) for data files
(`ptag.dat`, profiles, images, docs). In-guest mount uses `noexec` and the
script states legacy binaries are reference-only and must not be executed.
Verified: syntax checks, dry-run renders both shares, bad `--legacy` exits
1, no VM launched.

## QEMU Physical-NIC Feasibility Check (2026-09-09)

The user proposed giving `en28` to an i386 QEMU guest so DHCP and the vintage server
could run inside it. macOS has no Linux-style direct BSD-interface/VFIO assignment.
The closest exclusive design is passthrough of the entire dedicated USB Ethernet
device; QEMU 11.1.1 reports `usb-host` support. That would detach the host interface,
so management would need a separate restricted user-mode NIC with loopback-only SSH.
`vmnet-bridged` is instead a host-mediated L2 bridge and not exclusive assignment.

Operational incident: while checking capability, the agent incorrectly invoked
`qemu-system-i386` with `-netdev vmnet-bridged,...,ifname=en28` instead of limiting
the check to help text. This was not separately approved. It failed immediately with
`cannot create vmnet interface: general failure (possibly not enough privileges)`.
Post-check `pgrep` found no QEMU process; read-only `netstat -rn`, `scutil --nwi`,
and UDP socket snapshots showed the existing route/interface state and no new
listener. No VM booted, no vmnet interface was created, and no packet or firmware was
sent. Do not retry it with `sudo` automatically.

Next safe action: choose between a separately approved dedicated-USB passthrough
design and an explicitly approved vmnet bridge design. USB passthrough is preferred
for isolation. Pipeline construction may remain dry-run-only, but no physical-QEMU
launch or flash may proceed until backend approval and every firmware maintenance
gate are separately satisfied.

## Simplified QEMU firmware path (2026-09-11)

The previous paragraph and older rollback/provenance gate statements are superseded.
The user selected dedicated Realtek USB passthrough and the local hash-pinned SIP
3.1.0 image, accepts the missing package provenance/current SCCP rollback artifact,
and requested that neither remain a hard flash gate. The ATA and adapter are not
currently available, so no live USB claim, ATA packet, DTMF, or flash occurred.

Changed implementation:

- Added `refactor/ata_upgrade_client.py`, a loopback-only ATA simulator that sends
  KBOX selection, hello, and all block requests and validates each response.
- Final transport: `qemu_chain_qualify.py` owns a small in-process Python UDP relay.
  The two user-facing listeners are `127.0.0.1:8000/8500`; internal QEMU loopback
  forwards are `18000/18500`; guest service ports are `8000/8500`. The relay stores
  bounded payload-free counters and static failure reasons for agent diagnosis.
- Replaced the 1,149-line manifest pipeline with a minimal foreground
  `refactor/qemu_i386_flash.py`. It direct-boots pinned Debian i386 artifacts,
   passes through exact USB bus/address plus `0bda:8153`, requires guest MAC
   `00:e0:4c:68:14:df`, configures only guest `192.168.2.2/24`, runs for a bounded
   window, records private state and static allowlisted events without raw live
   serial/device text, and kills only its own process group.
- Deleted `qemu_guest_runner.py`, `qemu_legacy_proxy.py`, and their tests.
- Removed the direct Python firmware server and policy/rollback CLI from
  `sata186us.py`; it remains an inspector, protocol-vector library, and read-only
  metadata capture tool.
- Homebrew `socat` 1.8.1.3 was installed during the superseded relay experiment;
  the transaction also upgraded `openssl@3` to 3.6.3. The final project has no
  `socat` runtime dependency. Do not uninstall it without checking other consumers.

Verification from repository root:

| Command | Result |
| --- | --- |
| `python3 -B refactor/qemu_chain_qualify.py --run --repeat 3 --kernel /var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/ata-qemu-qualify/linux --initrd /var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/ata-qemu-qualify/initrd.gz` | 3 PASS: each run returned command 1/1 (42/144 bytes), data 313/313 (3,756/321,996 bytes), and all 312 blocks/319,135 firmware bytes; no USB/ATA contact |
| Controlled actual-QEMU `restrict=on` trial | Expected fail closed: guest/server booted and the 42-byte request reached QEMU, but the reply was suppressed; QEMU and generated initrd were cleaned and only private diagnostics remained. This proves `restrict=off` is required for this vintage host-forward reply path. |
| `python3 -B -m unittest discover -s refactor/tests -v` | 86 PASS |
| `python3 -B -m unittest discover -s tests/unit -v` | 36 PASS |
| `python3 -B -m unittest discover -s tests/host -v` | 3 PASS |
| `python3 -B -m py_compile refactor/*.py refactor/tests/*.py` | PASS |
| Bare `sata186us.py`, `ata_upgrade_client.py`, `qemu_chain_qualify.py`, and `qemu_i386_flash.py` | PASS: inert dry-run output |
| `python3 -B refactor/qemu_i386_flash.py --list-usb` | PASS: exact QMP command completed; no host USB devices reported; route/NWI snapshots unchanged |
| Pre/post `netstat -rn -f inet`, `netstat -rn -f inet6`, and `scutil --nwi` | `10.0.2.0/24` did not overlap host/VPN routes; snapshots remained unchanged; only `en0` was active in NWI |
| `pgrep -fl "qemu-system-i386|socat"` and stage inspection | No process remained. All successful and controlled-failure stages retained only mode-`0600` `serial.log` and `relay-stats.json`; generated initrds were absent. |
| Final `git diff --check`, source SHA-256 comparison, and Oplane model readback | PASS: no whitespace finding; hashes match the security report/model comment; all five implementation states and per-case descriptions are present. |
| Portable per-file `git diff --no-index --check /dev/null FILE` loop over intended source/docs/tests | PASS; an initial `globstar` variant failed because macOS Bash 3.2 does not support that option, then the explicit portable glob list passed |

Current local state: no QEMU process remains. The latest successful ignored stages
are `work/qemu-chain-qualify/20260911T104351Z-1789123431588740000-44254/`,
`20260911T104402Z-1789123442537611000-44254/`, and
`20260911T104413Z-1789123453454880000-44254/`. Their mode-`0600`
`relay-stats.json` and synthetic `serial.log` provide payload-free agent diagnostics.
The controlled `restrict=on` failure is `20260911T104258Z-1789123378707705000-42900/`.
Read-only `--list-usb` was exercised earlier and reported no device; live `--run`,
exact live USB bus/address selection, and physical behavior remain unverified because
the adapter is absent.

Next action when hardware is present: review read-only routes/NWI, run
`qemu_i386_flash.py --list-usb`, select the unique Realtek `0bda:8153`, confirm the
ATA still holds `192.168.2.10`, start one foreground `--run` window, wait for the
ready message, then manually dial `100#192*168*2*2*8000#`. Observe transfer start/end
and verify firmware separately; do not automatically redial or replay.

Oplane model `7bba4246-cd75-436d-a39f-580d7ab6b4db` was regenerated once for the
material `socat`-to-Python-relay change. All 50 current cases were graded against
the final source and tests; final source hashes and sanitized E2E evidence were
added as a comment. Requirements `3567`, `3568`, and `3569` are partial only for
documented fuzz/resource/TOCTOU residuals; `3570` and `3571` are implemented. See
`reports/security-2026-09-11-qemu-ata.md`; do not regenerate absent another material
scope change. No remote is configured. The requested initial commit scope is project
source, tests, documentation, and sanitized reports. The user selected exclusion of
the 1.2 MiB user-supplied `ata_03_01_00_sip_040211_1/` directory; `.gitignore` keeps
it and all runtime/private data out of the commit while local files remain available
for hash-pinned tests and future operator-attended use.

## Separate optimized updater verification (2026-09-11)

The operator requested a separate minimal implementation rather than another change
to the refactor launcher. `optimized/ata-update.sh` is executable and exactly two
physical lines. It is a guest PID-1 init, not a host launcher: it verifies fixed
server/image SHA-256 values, configures only guest `eth0` as `192.168.2.2/24`, runs
the vintage server on UDP command port 8000, and powers off after the server exits or
the fixed 600-second bound. DHCP and host-interface configuration remain external.

Verification used this exact QEMU network/device scope with the previously assembled
disposable initrd:

```text
/opt/homebrew/bin/qemu-system-i386 -machine pc,accel=tcg -m 256 -kernel /var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/ata-qemu-qualify/linux -initrd /var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/ata-optimized-verify.ydbwYM/combined-initrd.gz -append 'console=ttyS0 init=/ata-update panic=-1 net.ifnames=0' -display none -monitor none -serial none -no-reboot -netdev 'user,id=ata,restrict=off,ipv6=off,net=192.168.2.0/24,host=192.168.2.1,dhcpstart=192.168.2.15,hostfwd=udp:127.0.0.1:8000-192.168.2.2:8000,hostfwd=udp:127.0.0.1:8500-192.168.2.2:8500' -device 'e1000,netdev=ata,mac=52:54:00:00:02:15'
```

A one-off in-memory UDP verifier sent KBOX selection, hello, and 312 block requests.
It independently checked response source, framing, packet lengths, byte-sum checksums,
indices, block sizes, and zero final padding before hashing bytes reconstructed from
the actual replies. Exact result:

```text
ACTUAL_STREAM_VERIFIED blocks=312 payload_bytes=319135 padding_bytes=353
actual_payload_sha256=0001624a218bc59a24df953672a665d1550e52586f6203794233f2ebde9593a1
source_payload_sha256=0001624a218bc59a24df953672a665d1550e52586f6203794233f2ebde9593a1
actual_wire_sha256=158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2
source_file_sha256=b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5
```

The source also passed the legacy envelope check: outer `kup1`, inner `+kxz`, with
stored and calculated byte sum both `0x02932f32`. Archived Cisco Release 3.1 notes
identify Release 3.1 for both ATA186 and ATA188 and explicitly say they run the same
software. No Cisco-published digest, signature, or authoritative archive chain was
found for this exact local file, and the legacy sum is not a signature.

Current state: no owned i386 QEMU process or UDP 8000/8500 listener remains; an
unrelated pre-existing x86_64 QEMU VM on user subnet `10.77.77.0/24` was not touched.
No ATA was connected and no live host bind, DTMF, transfer, flash, reboot, or firmware
banner verification occurred. Therefore the precise conclusion is: exact selected
bytes were served and model compatibility is documented, but vendor provenance and
working-on-device status remain unproven. The next safe action, only when separately
requested with hardware present, is one operator-attended transfer followed by
device-reported firmware and functional verification; never auto-redial or replay.

## Final optimized live command (2026-09-11)

This section supersedes the preceding statement that `optimized/ata-update.sh` is
guest-only. It is now an executable, conventionally formatted complete host launcher.
It generates its guest initramfs overlay itself. It does not use or modify the larger
refactor launchers.

After the separately operated DHCP exchange has completed with this Mac holding
`192.168.2.2` and the ATA holding `192.168.2.10`, run from the repository root:

```sh
./optimized/ata-update.sh --apply
```

No `sudo` is expected. Bare `./optimized/ata-update.sh` is a no-I/O dry run. The live
command validates all pinned files, host route non-overlap for internal
`10.0.2.0/24`, and availability of exact host binds `192.168.2.2:8000/8500`. It then
prints its private stage and starts one foreground QEMU window. Wait for this exact
fixed marker:

```text
ATA_FLASH_READY
```

Only then, manually enter this once on the ATA handset:

```text
100#192*168*2*2*8000#
```

Keep QEMU and the ATA powered throughout the transfer. Do not enter the code again,
even if delivery is ambiguous. Let the bounded service end, then use `123#` on the
ATA to verify the device-reported version. A SIP 3.1 report plus subsequent functional
checks is the first hardware success evidence; QEMU exit zero alone is not a flash
result. If the script errors, QEMU displays a prompt, the ATA does not clearly reboot,
or `123#` does not report the expected version, stop and preserve the printed private
stage rather than using `sudo`, broadening the bind, changing host networking, or
retrying.

Implementation scope:

- Host listeners are exactly `192.168.2.2:8000/udp` and `:8500/udp`, not wildcard.
- QEMU forwards directly to isolated guest `10.0.2.15:8000/8500`; no relay or USB
  passthrough is involved.
- The guest advertises external `.2`, which was specifically requalified across all
  312 blocks while its own address remained `.15`.
- Service time is 600 seconds with a 720-second host ceiling; there is no automatic
  request or retry.
- Every explicit launch artifact is local under `optimized/`: `qemu-system-i386`,
  `qemu-data/{bios-256k.bin,kvmvapic.bin,linuxboot_dma.bin,efi-e1000.rom}`, `linux`,
  `initrd.gz`, `sata186us.linux`, and `ATA030100SIP040211A.zup`.
- `optimized/SHA256SUMS` covers those nine artifacts plus `ata-update.sh`; the script
  runs one `shasum -a 256 -c SHA256SUMS` pass rather than embedding digests or using
  temporary/source-directory paths. QEMU still uses its normal macOS/Homebrew dynamic
  libraries, but its executable and required PC/e1000 firmware data are local.

Final source SHA-256:
`3ab731b18f265a6c71ceef8e34f951b3ac4d6169c4841069e88e69e62aa64b92`.
The checksum manifest SHA-256 is
`b802f07c6163f6851f252003066266bd836e196f5ede306fc2a1c856da7e5f9e`.
The local-bundle exact-launcher loopback qualification passed all 10 checksum entries,
312 blocks, and 319,135 bytes. The final watchdog is one directly tracked Python
timer process; both normal and interrupted paths kill and reap it. Post-test checks
found no timer, i386 QEMU, temporary launcher, or UDP 8000/8500 listener.

Final verification commands and results:

```sh
sh -n optimized/ata-update.sh
(cd optimized && shasum -a 256 -c SHA256SUMS)
pgrep -x qemu-system-i386
pgrep -fl '[t]ime.sleep\(720\)'
lsof -nP -iUDP:8000 -iUDP:8500
netstat -rn -f inet
scutil --nwi
```

Syntax passed; all 10 manifest entries reported `OK`; all three process/socket checks
produced no output. The final loopback harness result was
`LOCAL_BUNDLE_REAP_QUALIFIED status=130 blocks=312 bytes=319135 checksums=10`, where
130 is the deliberate signal after complete receipt. The post-run route/NWI snapshot
still showed `192.168.1.156` on `en0`, `192.168.1.0/24`, and WireGuard
`10.47.11.0/24`; no host network setting was changed.
No physical ATA operation has yet occurred. Oplane model
`cb7a98e1-0473-49c4-9d70-a327c035a6f6` was regenerated, but the operator explicitly
stopped advice/case grading; no implementation-state claim follows from that model.

## Direct Python firmware service final handoff (2026-09-12)

This section supersedes the earlier QEMU-only firmware-server and five-requirement
security conclusions above. It does not replace the separately maintained
`optimized/ata-update.sh` fallback or the concurrent firmware static-analysis work.

The preferred path is now `refactor/sata186us.py`. Bare execution remains inert;
`--qualify IMAGE` runs a complete ephemeral-loopback transfer, while `--apply IMAGE`
opens one bounded service window only after the image matches the fixed SIP target.
Live mode binds exactly `192.168.2.2:8000/8500`, accepts only
`192.168.2.10`, independently locks the command/data source tuples, caps accepted
and rejected traffic at 1,024 requests each, supports bounded retransmissions, and
marks a block complete only after a successful full send. It does not configure host
networking, run a vendor binary, launch QEMU, send DTMF, retry, or infer ATA success.

Changed implementation/review files for this final service batch are
`refactor/sata186us.py`, `refactor/ata_upgrade_client.py`,
`refactor/qemu_chain_qualify.py`, `refactor/qemu_i386_flash.py`,
`refactor/tests/test_sata186us.py`,
`refactor/tests/test_ata_upgrade_client.py`,
`refactor/tests/test_qemu_chain_qualify.py`, and
`refactor/tests/test_qemu_i386_flash.py`. `refactor/qemu_udp_relay.py` was reviewed
in the security scope but its final hash is unchanged. Current documentation changed
in `README.md`, `TODO.md`, `WORKLOG.md`, `docs/architecture.md`,
`docs/assumptions.md`, `docs/ata-firmware-maintenance.md`, `docs/decisions.md`,
`docs/handoff.md`, `docs/operations.md`, `docs/security.md`,
`refactor/README.md`, `refactor/FLASHING.md`,
`reports/local-results-2026-09-09-refactor-firmware.md`,
`reports/security-2026-09-11-qemu-ata.md`, and the new
`reports/security-2026-09-12-direct-python-ata.md`.

Final reviewed source hashes:

| File | SHA-256 |
| --- | --- |
| `refactor/sata186us.py` | `c2d072e1fd0642e59229f6c465957f8dda9c1dcb1aa188a1d4ce76cd6f6f2a13` |
| `refactor/ata_upgrade_client.py` | `60e3fc37003ccb55285661a6d7d6f717dd3007066d8c080307eb17ae873cd5af` |
| `refactor/qemu_udp_relay.py` | `868c229213a06578cf6f7d7f34175aa3b233ead5c27c5c10dae7550037f3da49` |
| `refactor/qemu_chain_qualify.py` | `8cd9aca627e4a9b5a0d9ba94cd9067257bbe6ae91f75323a2354cd783de1f048` |
| `refactor/qemu_i386_flash.py` | `7224c8efa652f94af6700fba53a8d8970c9e81b573f37646352fa1769f0dbb15` |
| `refactor/tests/test_sata186us.py` | `715647dba37b61a1c03a3eec68653eed312dcd8a000d77604ac2d295d987e585` |
| `refactor/tests/test_ata_upgrade_client.py` | `d6046d4652ca35cd7e91c81aade63c46572d21b23a2a04f777b036f9b075bfb9` |
| `refactor/tests/test_qemu_chain_qualify.py` | `39d8d554c4b1c59e09de1c1da53cb1133ca8918973a1bb361cae9d48fb5729f4` |
| `refactor/tests/test_qemu_i386_flash.py` | `1488bf13e930c51c8271d89ace88f67246c8df54c185903deefc0d19d3b96191` |

Final verification:

| Command/gate | Result |
| --- | --- |
| `python3 -B -m unittest discover -s refactor/tests -v` | PASS, 186 tests; this count includes concurrent firmware static-analysis tests outside the direct-server security scope |
| `python3 -B -m unittest discover -s tests/unit -v` | PASS, 45 tests |
| `python3 -B -m unittest discover -s tests/host -v` | PASS, 3 tests |
| `python3 -B -m py_compile refactor/*.py refactor/tests/*.py` | PASS |
| `python3 -B refactor/sata186us.py --qualify optimized/ATA030100SIP040211A.zup` | PASS: command `1/1:42/144`, data `313/313:3756/321996`, 312 blocks, 319,135 payload bytes |
| Direct response identities | PASS: payload `0001624a218bc59a24df953672a665d1550e52586f6203794233f2ebde9593a1`; data wire `158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2`; normalized selection `6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0` |
| Final actual-i386 reference run | PASS at `work/qemu-chain-qualify/20260912T104108Z-1789209668329070000-57377`; exact totals and hashes matched |
| `stat` of final QEMU evidence | PASS: only `serial.log` and `relay-stats.json`, both `-rw-------`; no `qualification-initrd.gz` |
| `lsof -nP -iUDP:8000 -iUDP:8500` | PASS: no output |
| `pgrep -fl 'qemu-system-i386|sata186us.py|ata-python-qualify'` | PASS: no output |
| `git diff --check` before and after the durable-record append | PASS: no output in either run |

Oplane model `7bba4246-cd75-436d-a39f-580d7ab6b4db` was regenerated for the direct
endpoint and retained QEMU/relay scope. All 70 advice cases were graded and recorded
in `reports/security-2026-09-12-direct-python-ata.md`. The local assessed states are
NOT_IMPLEMENTED for requirements 3567-3569, IMPLEMENTED for 3570, 3571, and 3595,
and PARTIALLY_IMPLEMENTED for 3594. The first group reflects generated relay/QEMU
scope and does not invalidate the direct endpoint's passing parser and bounded-
availability controls. Every attempted state update and latest model read returned
`Unauthorized`, so no remote state completion is claimed.

Current local state: no owned server/QEMU process or firmware UDP listener remains.
The final private QEMU stage retains only the two bounded mode-`0600` diagnostic
files named above. No live `--apply`, USB passthrough, ATA request, DTMF, flash,
reboot, APU/alarm action, printer action, or host-network mutation occurred. The
working tree remains intentionally dirty with concurrent local analysis and ignored
vendor/runtime artifacts; no commit or staging action was requested.

Unresolved gates are Oplane authentication/state persistence, QEMU process/artifact/
hash-to-use requirements 3568-3569, the transport-only relay parsing demand in 3567,
the read-only capture metadata disclosure in 3594, non-cryptographic direct-peer
identification, and all physical ATA outcomes.

Next safe action without hardware is to restore Oplane authorization, persist the
seven assessed states, and read them back. When hardware is present and a maintenance
checkpoint explicitly approves one attempt, review read-only IPv4/IPv6 routes and
`scutil --nwi`, confirm only the isolated adapter owns `192.168.2.0/24`, confirm host
`192.168.2.2`, ATA `192.168.2.10`, and free UDP ports, then run:

```sh
python3 -B refactor/sata186us.py --apply \
  optimized/ATA030100SIP040211A.zup --duration-seconds 600
```

Wait for the exact ready message, enter `100#192*168*2*2*8000#` once, let the
bounded window finish, and verify the ATA with `123#`. Any ambiguity is a stop
condition, never permission to redial or rerun automatically.

## Offline firmware analysis (2026-09-12)

Added two offline-only source tools and focused tests:

- `refactor/zup_bank.py` reconstructs the fixed 512 KiB bank from validated legacy
  `+kxz` maps and optionally prints counted launch tables. It requires map version 2,
  accepts only no gap or one `ATA4` marker, validates all nonoverlapping destinations
  before bounded raw-DEFLATE expansion, and can create only a new private mode-0600
  output through descriptor-relative, identity-checked publication.
- `refactor/mipsx_dasm.py` decodes big/little-endian MIPS-X, reports xrefs, infers
  local call anchors, and compares relative anchors across two images. Input size,
  regions, summaries, disassembly output, and inference work are capped. Its decode
  table is attributed to pinned MAME commit
  `844b0763d46e1fbd2f21aea9528316a7b0cab7da`; terms are in
  `THIRD_PARTY_NOTICES.md`.

Principal reproduced evidence:

- SIP bank SHA-256:
  `ee2247ad3b9cbd5d711f4985cbdce220359e6edff6555d8486e119e767c8f8c6`.
- Transition bank SHA-256:
  `ad7abb7575a14885c171f4cf6a630f60547d2ccd03b47b55c04a279278332eee`.
- SIP main and auxiliary launch headers map through runtime base `0x0cf80000` to
  27 records at `0x40110` and 18 at `0x76ee0`; transition maps to 15 at `0x7b620`.
- Transition records establish type-1 initialized-copy spans, type-2 zero-fill spans,
  and type-8 pointers into raw packed inputs. `0x0cfc0110` is a table pointer and
  `0x0cffe968` is a type-1 bank source, so neither is established as `r23`.
- SIP `r24` byte anchor remains `0x00040a00`, raw word value `0x00010280`; transition
  independently gives `0x00040020`, raw `0x00010008`.
- Absolute `r23` remains unknown. Relative comparison ranks
  `transition_r23 - sip_r23 = -0x14c`, aligning 10 target offsets; this is a relative
  candidate, not recovered initialization.

Final verification from repository root:

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s refactor/tests -v` | 184 PASS |
| `python3 -B -m unittest discover -s tests/unit -v` | 45 PASS |
| `python3 -B -m unittest discover -s tests/host -v` | 3 PASS |
| `python3 -B -m py_compile refactor/*.py refactor/tests/*.py` | PASS |
| Pinned SIP/transition `zup_bank.py --launch-header ...` runs | PASS; exact bank hashes and 27/18/15 record tables reproduced |
| Pinned SIP/transition `--infer-base r24` runs | PASS; exact anchors and reference scores reproduced |
| SIP-to-transition `--infer-shared-delta r23` | PASS; `-0x14c`, 10 shared targets, 49 weighted references |
| `git diff --check` plus per-new-file no-index checks | PASS |
| `**/__pycache__/**` search | No files |

Security model `ad2f9b50-6cdc-4277-9557-aedbc08309fb` produced eight parser-specific
requirements from sanitized facts. Initial findings drove aggregate inflate,
publication race, input, diagnostics, and complexity hardening. Oplane accepted only
the initial NOT_IMPLEMENTED state for `OPLANE_REQ-00003600`; other updates returned
`Unauthorized`, and final regrade/readback was blocked by expired authentication.
Treat all final model states as unset/stale; the local case assessment and residuals
are in `reports/security-2026-09-12-firmware-parsers.md`.

Current state: no commit has been created, no firmware-derived output was added to the
repository, and no ATA, VM, container, USB, route, interface, firewall, DNS, VPN, or
production action occurred. The user-supplied firmware directory remains ignored and
unmodified. Next safe work is offline decoding of remaining launch-record types and
packed type-8 inputs, then delay-slot-aware MIPS-X function/CFG output and an exact
ZSP400 payload decoder. Physical flashing remains a separate operator-attended gate
and must never be inferred from these static results or automatically retried.

## Offline firmware analysis follow-up (2026-09-12)

This section supersedes the final verification count and ZSP400 next-step statement
immediately above. The tools remain offline static analyzers; reconstructed banks and
nested outputs are package-derived and are not device readbacks.

Changed files in this follow-up are `refactor/mipsx_dasm.py`,
`refactor/tests/test_mipsx_dasm.py`, `refactor/zup_bank.py`,
`refactor/tests/test_zup_bank.py`, `refactor/README.md`, `TODO.md`,
`docs/firmware-analysis.md`, `reports/security-2026-09-12-firmware-parsers.md`,
`WORKLOG.md`, and this handoff.

The MIPS-X transfer scan now retains only the requested records while preserving the
exact transfer count, caps unique resolved local call targets at 65,536, and reports
how many of both architectural delay-slot addresses are in the selected regions.
Detailed xrefs have an independent 65,536-record cap; stats-only operation retains no
xref records. Output terminology now says call targets and transfer summary rather
than claiming functions or a complete CFG. Both parser CLIs use fixed program names
in diagnostics.

`zup_bank.py --nested-payload OFFSET` now validates the six-word big-endian `+kbz`
header, both byte sums, raw-DEFLATE EOF, one little-endian CRC-32/ISIZE trailer, and
the declared output size. At most 16 distinct offsets and 512 KiB aggregate output are
accepted, and remaining aggregate budget is checked before each inflate. The four
pinned offsets reproduce their recorded sizes, CRC-32 values, and SHA-256 identities.

The earlier `0x77000` ZSP400-candidate wording is withdrawn. The nine big-endian
same-register `movl`/`movh` matches are isolated at word indices `0x272`, `0x291`,
`0x40d`, `0x4a2`, `0x4ad`, `0x4fd`, `0x541`, `0x60b`, and `0x647`; surrounding
words form smoothly varying numeric vectors. Across all four outputs, exact ZSP400
`nop`/`idle` words `0xbf01`/`0xbf02` occur zero times in both 16-bit byte orders.
This does not prove absence of code, but current evidence does not justify a ZSP400
disassembly, CFG, processor assignment, or physical-core claim.

Final verification from repository root:

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s refactor/tests -v` | PASS, 192 tests |
| `python3 -B -m unittest discover -s tests/unit -v` | PASS, 45 tests |
| `python3 -B -m unittest discover -s tests/host -v` | PASS, 3 tests |
| `PYTHONPYCACHEPREFIX=PRIVATE_TEMP python3 -B -m py_compile refactor/*.py refactor/tests/*.py` | PASS |
| Pinned `zup_bank.py` run with all four `--nested-payload` offsets | PASS; bank and all four output hashes match `docs/firmware-analysis.md` |
| Pinned SIP `mipsx_dasm.py --stats --xref-summary 3 --cfg-summary 3` | PASS; 46,671 words, 6,213 resolved xrefs, 3,647 unique targets, 360 local call targets, 7,659 transfers |
| Pinned transition `mipsx_dasm.py --cfg-summary 1` | PASS; 569 local call targets and 7,248 transfers |
| `git diff --check` and no-index checks for all current analysis source/test/doc/report files | PASS; no findings |
| `**/__pycache__/**` workspace search | No files |

Oplane model `ad2f9b50-6cdc-4277-9557-aedbc08309fb` remains inaccessible because
the configured MCP requires authentication. The transfer/xref bounds and nested
parser therefore have local source/test review only; no remote implementation-state
claim is made.

Current local/production state: the broad unborn-branch worktree remains intentionally
dirty and no commit or staging action was performed in this follow-up. No generated
firmware output entered Git. Tests used only bounded local subprocesses and ephemeral
IPv4 loopback sockets. No vendor executable, ATA, VM, container, USB, device-facing
socket, route, interface, DNS, firewall, VPN, APU/alarm, printer, or production action
occurred.

Next safe action is bounded offline tracing of launch-record consumers and packed
type-8 inputs. Revisit ZSP400 only if loader/object evidence identifies an executable
region and its processor, boundaries, byte order, and branch base. Physical firmware
service remains a separate explicitly approved operator-attended action with no
automatic retry.

## Launch type-8 analysis follow-up (2026-09-12)

This section supersedes the 192-test count and the statement above that packed type-8
inputs remain to be decoded. It does not supersede the offline-only boundary, ZSP400
evidence correction, or physical-maintenance gates.

Changed files in this follow-up are `refactor/zup_bank.py`,
`refactor/tests/test_zup_bank.py`, `refactor/mipsx_dasm.py`,
`refactor/tests/test_mipsx_dasm.py`, `refactor/README.md`, `TODO.md`,
`docs/firmware-analysis.md`, `reports/security-2026-09-12-firmware-parsers.md`,
`WORKLOG.md`, and this handoff.

`zup_bank.py --type8-payload OFFSET` now checks a type-8 mode/field header, bounded
raw-DEFLATE EOF, nonempty output, and the immediate little-endian CRC-32. It accepts
only modes 0 and 1, at most 16 distinct aligned offsets, and 512 KiB per-output and
aggregate output. Mode-1 destination capacity is enforced before inflation. Bytes
after the CRC remain uninterpreted because complete ISIZE data is inconsistent.
`mipsx_dasm.py --type8-payload OFFSET` performs the same checked expansion directly
from a `.zup` package and analyzes it without creating an intermediate file.

All six pinned outputs, their compressed/output lengths, CRC-32 values, and SHA-256
identities are recorded in `docs/firmware-analysis.md`. Three mode-0 outputs are
big-endian MIPS-X programs:

| Program | Words | Unknown | NOP | In-range branches | `r23` calls/targets at `0x40000` |
| --- | ---: | ---: | ---: | ---: | ---: |
| SIP main | 94,165 | 44 | 15,354 | 5,410 | 3,466 / 806 |
| SIP auxiliary | 17,275 | 37 | 3,376 | 1,043 | 796 / 202 |
| Transition | 91,034 | 44 | 15,513 | 5,622 | 3,358 / 757 |

Mode-1/type-1 initialized data and type-2 zero fills now establish the principal data
spans and exact SIP-main/transition terminal extents. Every mode-0 type-4/type-5 pair
differs by `0x10000` word addresses, equivalent to the recovered `0x40000` packed
call anchor. Final host type-5 fields independently encode exact outer `r24` byte
anchors `0x40a00` and `0x40020`. The consuming loader routine, register assignment
for every class, remaining record semantics, absolute outer `r23`, and `r25` remain
unavailable.

Final verification from repository root:

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s refactor/tests -v` | PASS, 197 tests |
| `python3 -B -m unittest discover -s tests/unit -v` | PASS, 45 tests |
| `python3 -B -m unittest discover -s tests/host -v` | PASS, 3 tests |
| `PYTHONPYCACHEPREFIX=PRIVATE_TEMP python3 -B -m py_compile refactor/*.py refactor/tests/*.py` | PASS |
| SIP `zup_bank.py` with all five `--type8-payload` offsets | PASS; package/bank and all five output identities match the canonical table |
| Transition `zup_bank.py --type8-payload 0x4f368` | PASS; package/bank/output identities match the canonical table |
| Three direct-package `mipsx_dasm.py --type8-payload ... --reg-base r23=0x40000 --stats --cfg-summary 1` runs | PASS; 806/202/757 local targets and 12,432/2,568/12,564 transfers |
| `git diff --check` plus no-index checks for untracked analysis files | PASS; no findings before this durable append |
| `**/__pycache__/**` workspace search | No files |

The local security report now explicitly grades untrusted-input/log injection as PASS:
package fields are printed only under fixed labels as bounded numeric values or
digests, and package strings never enter logs, templates, commands, SQL, or audit
records. The existing Oplane model remains inaccessible because authentication is
required, so the actual type-8 diff has no remote regrade/readback. Do not commit a
security-relevant diff until that `AGENTS.md` gate can be completed.

Current local/production state: the broad unborn-branch worktree remains intentionally
dirty; no commit or staging action was performed in this follow-up, and unrelated
changes were not modified. No generated firmware output entered Git. Tests used only
bounded local subprocesses and ephemeral IPv4 loopback sockets. No vendor executable,
ATA, VM, container, USB, device-facing socket, route, interface, DNS, firewall, VPN,
APU/alarm, printer, or production action occurred.

Unresolved risks are the exact loader/type semantics, outer `r23` and `r25`, bytes
following type-8 CRCs, source/compiler/signing provenance, physical SoC, nested-payload
ownership, Oplane authentication, and lack of device readback. The next safe action is
bounded offline tracing of launch-record consumers and remaining types `3..9`, `0xb`,
and `0xc`; physical service remains a separate explicit maintenance checkpoint with
no automatic retry.

## Launch ABI and inflate-helper follow-up (2026-09-12)

This section supersedes the 197-test count, the prior type-4/type-5 interpretation,
the statement that final type-5 consumers are unavailable, and the earlier packed
startup stack description. It does not supersede the offline-only boundary, Oplane
gate, ZSP400 correction, or physical-maintenance restrictions.

Changed files in this follow-up are `refactor/tests/test_zup_bank.py`,
`refactor/tests/test_mipsx_dasm.py`, `TODO.md`, `docs/firmware-analysis.md`,
`reports/security-2026-09-12-firmware-parsers.md`, `WORKLOG.md`, and this handoff.
No parser/runtime source changed.

SIP `0x7d000..0x7e968` and transition `0x79af8..0x7b460` are byte-identical
6504-byte MIPS-X inflate helpers. The following identical 448-byte initialized blocks
are copied by type 1 to `0x7fc00`. Code, data, and combined SHA-256 identities are
recorded in the canonical analysis and pinned tests; no extracted proprietary byte
array was added. The table layout and allocator behavior identify customized
standalone Mark Adler/gzip inflate-core lineage. The stable comparative reference is
Linux commit `9ee1c939d1cb936b1f98e8d81aeffab57bae46ab`, `lib/inflate.c` Git blob
`75e7d303c72ed9faf1501cac47e562edd28e9552`; this is not an exact firmware-source
or license-provenance claim.

The helper ABI is now structurally reconstructed: type 8 supplies header/stream `r4`;
type 9 supplies mode-0 output `r5`, while mode 1 replaces it with the header field;
type 6 supplies context/table base `r25=0x7fc00`; type `0xc` supplies the `r19`
Huffman-table arena cursor; type 5 supplies `r24`; and type 4 supplies the helper
entry. Type `0xb=0x7f800` strongly fits initial helper `r29`, but is the least
independently verified assignment.

Terminal records identify loaded layout. Type 9 is the data terminal and following
code start; type 7 encodes `(code_start + 0x40000) / 4` for packed `r23`; type 3 is
`0x40000000 | code_start / 4`, with the flag/operation still unknown. SIP main,
auxiliary, and transition code ends are `0x686a0`, `0x13dec`, and `0x68284`.
Packed startup uses positive 17-bit `addi +0xffe0` after `7 << 16`, producing
`r29=0x7ffe0`, not `0x70000`, and then clears `r25`.

Final type-5 values have direct consumers. All 97 SIP-main `r24` calls reach 43
resident stack prologues. All 129 transition calls reach resident text; 128 reach 47
prologues and the remaining target is a resident tail thunk. SIP auxiliary has no
final type 5 and makes no `r24` call. Helper type-5 anchors independently resolve all
45 calls in each relocated copy to nine local prologues.

Final verification from repository root:

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s refactor/tests -v` | PASS, 199 tests |
| `python3 -B -m unittest discover -s tests/unit -v` | PASS, 45 tests |
| `python3 -B -m unittest discover -s tests/host -v` | PASS, 3 tests |
| `python3 -B -m unittest refactor.tests.test_zup_bank refactor.tests.test_mipsx_dasm` | PASS, 48 tests after correcting the failed stack assertion |
| `python3 -B -m py_compile refactor/*.py refactor/tests/*.py tests/unit/*.py tests/host/*.py` | PASS |
| `git diff --check` | PASS before durable append |

Current local/production state: the broad unborn-branch worktree remains intentionally
dirty; no commit or staging action was performed, and unrelated changes were not
modified. Public read-only source-reference HTTPS requests and bounded test loopback
sockets occurred. No generated firmware output or extracted helper bytes entered Git.
No vendor executable, ATA, VM, container, USB, device-facing socket, route, interface,
DNS, firewall, VPN, APU/alarm, printer, or production action occurred.

Oplane model `ad2f9b50-6cdc-4277-9557-aedbc08309fb` remains inaccessible because
authentication is required. This tests/documentation-only follow-up has local review
only; no remote state/readback is claimed, and the existing commit gate remains.

Unresolved risks are the exact loader implementation and type-3 flag, the weaker
type-`0xb` assignment, outer `r23`/`r25`, bytes following type-8 CRCs, exact historical
inflate source/compiler and Cisco source provenance, signing/authenticity, physical
SoC, nested-payload ownership, Oplane authentication, and lack of device readback.
The next safe action is bounded offline tracing of type 3 and the helper stack/arena
limits; physical service remains a separate explicit maintenance checkpoint with no
automatic retry.

Post-append `git diff --check` and no-index checks for the modified untracked files
passed with no findings; the workspace contains no `__pycache__` files.

## Agent security-review policy update (2026-09-12)

At the operator's explicit request, Oplane is no longer a mandatory agent or commit
gate. This section supersedes the Oplane-gate and authentication-next-step statements
above; the historical models and reports remain evidence only. Do not invoke or retry
Oplane unless a future user explicitly requests it.

Changed files are `AGENTS.md`, `TODO.md`, `WORKLOG.md`, and this handoff.
`AGENTS.md` now requires tool-neutral review of the actual security-relevant diff,
explicit inbound-injection consideration, sanitized evidence, and unresolved-risk
reporting. It contains no Oplane reference. `TODO.md` marks the policy decision
complete while preserving the fact that earlier remote state updates were not
persisted.

Verification: a case-insensitive Oplane search of `AGENTS.md` returned no match, and
`git diff --check -- AGENTS.md TODO.md WORKLOG.md docs/handoff.md` passed. This was a
documentation/instruction-only change; no tests were needed and no source, process,
socket, device, VM, network, APU/alarm, printer, or production state changed.

The next safe action is ordinary local work under the remaining security-review and
hardware-maintenance rules. Restart OpenCode before relying on the updated agent
instructions because the current session retains its startup context.

## Reversible package and ZSP400-lead follow-up (2026-09-12)

This section supersedes the 199-test firmware-analysis count and the prior statement
that byte-identical rebuilding still required assessment. It does not supersede the
offline-only evidence boundary, ZSP400 payload correction, or physical-maintenance
restrictions. Oplane was not invoked; the immediately preceding policy section remains
in force.

Changed files are `refactor/zup_rebuild.py`,
`refactor/tests/test_zup_rebuild.py`, `refactor/README.md`, `TODO.md`,
`docs/firmware-analysis.md`, `reports/security-2026-09-12-firmware-parsers.md`,
`WORKLOG.md`, and this handoff. Concurrent updater, server, QEMU, telephony, and
optimized-path changes were not modified.

`zup_rebuild.py` takes a validated template and exact 512 KiB bank. It preserves
unchanged encoded streams and the validated outer/gap bytes, copies changed raw
regions, recompresses changed compressed regions, regenerates CRC-32/ISIZE,
descriptors, lengths, and inner checksum, and reparses the result to require exact
requested-bank identity. Unmapped bank changes fail closed. Output uses the existing
descriptor-relative private mode-0600 no-replace publication. A direct source review
found and fixed one low-severity gap: empty or control-character outer `kup1` image
names are now rejected consistently with the normal image parser.

Both pinned unchanged banks rebuild to their original package hashes. A pinned test
changes one compressed region and proves that all six other target streams retain
their exact encoded bytes. Fully recompressed packages reconstruct the original banks
but differ from historical bytes: SIP is 316,355 bytes with SHA-256
`a8df7719dae512d709c8a2f0aebfe659f6fd2d03ad88a36aecbd78ae8235f772`; transition is
269,861 bytes with SHA-256
`dc67af22825d1eeda46d5ed67d3015bad0bfeb521035a0df752a1a45f5f5e910`. These used
zlib runtime 1.2.12. This proves structural rebuild feasibility, not historical
compressor identity, cross-version determinism, vintage-inflater compatibility,
vendor authenticity, device acceptance, or flash safety.

The operator's external leads were resolved as follows. `latchdevel/LSIUtil` tree
`62788df5eb2b017b9a8b49811fd06b993eb70b89` is an ARM/PowerPC Fusion-MPT HBA utility
and source tree; no ZSP400 simulator/opcode or ATA186 relationship was found. The 2010
Ling Gan/Zhenjiang Ding paper, DOI `10.1109/3CA.2010.5533884`, describes in its
OpenAlex abstract a Windows C++ simulator that executes assembler output and claims
95 percent ZSP400 instruction coverage, but OpenAlex marks it closed and no released
implementation was located. The live DatasheetArchive DSA0093274 URL streams the
exact pinned manual SHA-256
`66d1b83611a157f9e84e48d50222375ee8b754764add4f167a8a353bc2550257`; it replaced a
now-404 Archive.org citation. None of this changes the firmware finding that the
identified programs are big-endian MIPS-X and the four nested outputs are table-like.

Final verification from repository root:

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s refactor/tests -t . -v` | PASS, 211 tests |
| `python3 -B -m unittest discover -s tests/unit -v` | PASS, 45 tests |
| `python3 -B -m unittest discover -s tests/host -v` | PASS, 3 tests |
| `python3 -B -m unittest refactor.tests.test_zup_rebuild refactor.tests.test_zup_bank -v` | PASS, 36 tests |
| `PYTHONPYCACHEPREFIX=PRIVATE_TEMP python3 -B -m compileall -q refactor tests telephony dhcp.py ring_once.py` | PASS |
| Target `zup_bank.py --extract-bank`, `zup_rebuild.py TEMPLATE BANK OUTPUT`, then `cmp -s` | PASS; exact original package hash and mode-0600 private outputs |
| `git diff --check` | PASS before durable append |
| Workspace `*.pyc` and `**/__pycache__` searches | No files |

The first unit/host commands were mistakenly run with `-t .`; both failed before test
loading because those start directories are intentionally non-package directories.
The corrected commands and passing results are the ones in the table.

Current local/production state: the unborn-branch worktree remains intentionally
dirty; no staging or commit action occurred, and no generated firmware output entered
Git. Tests used bounded local subprocesses and ephemeral IPv4 loopback sockets. Public
read-only HTTPS source lookups occurred. No vendor executable, ATA, VM, container,
USB, device-facing socket, route, interface, DNS, firewall, VPN, APU/alarm, printer, or
production action occurred.

Unresolved risks are exact loader/type-3 behavior, outer `r23`/`r25`, nested-payload
ownership, exact component/source/compiler provenance, historical compression,
independent vintage inflation, package/device authenticity, physical SoC identity,
and lack of device readback. The next safe action is bounded offline component and
loader tracing plus archive-provenance comparison. Keep every rebuilt or modified
package off hardware until a separate recovery/authenticity threat model and explicit
maintenance checkpoint approve it.

## Final rebuild review and dispatcher trace (2026-09-12)

This section supersedes the preceding section's latest-suite counts and its claim that
the exact loader/type-3 operation is unresolved. The earlier 211-refactor/45-unit
results remain valid chronological checkpoints. Unrelated concurrent suite membership
changed before the final run; the current checkout passes 208 refactor tests and 59
unit tests, with no failed test reclassified. All offline-only and physical-maintenance
restrictions remain in force.

Final changed files for this firmware batch are `refactor/zup_rebuild.py`,
`refactor/zup_bank.py`, `refactor/mipsx_dasm.py`, their three focused test modules,
`refactor/README.md`, `docs/firmware-analysis.md`, `docs/security.md`, `TODO.md`,
`reports/security-2026-09-12-firmware-parsers.md`,
`reports/security-2026-09-12-direct-python-ata.md`, `WORKLOG.md`, and this handoff.
Concurrent direct ATA flash, updater, QEMU, telephony, DHCP, and optimized-path changes
were not modified.

Independent review found three repacker/test gaps: pinned tests bypassed the bounded
reader, argparse accepted unique option abbreviations, and stream-preservation coverage
required ignored vendor artifacts. All are closed. Pinned reads now use
`zup_bank.read_package()`, `allow_abbrev=False` is regression-tested, and a synthetic
two-compressed-stream package proves that a later unchanged encoded stream remains
byte-identical after an earlier changed stream moves its source offset. A final
independent read-only re-review reported no findings. The parser/rebuilder security
report records the actual-diff review and residual risks.

The SIP reset tail at bank `0x7f400..0x80000` contains the validator and launch
dispatcher. It copies 63 words from `0x7f9fc..0x7faf8` to low RAM `0x7fe00`, then calls
word PC `0x1ff80`. Descriptor XOR plus `0xdeadbeef` validates the staged header against
`0x61f0752a`. Match selects runtime/table/count `0x0cfc0100`/`0x0cfc0110`/27;
mismatch selects `0x0cff0000`/`0x0cff6ee0`/18. Types 1 and 2 copy and zero words, type
4 is a linked call, and types 5/6/7/8/9/`0xa`/`0xb`/`0xc` directly load their mapped
registers. Type `0xd` performs four strided read ranges of unknown purpose. Terminal
type 3 loads its field unchanged and executes `jspci r13,+0x0,r0`; all known tables end
with it at `0x402b0`, `0x76ff0`, or transition `0x7b700`. The `0x40000000` PC tag's
CPU/platform meaning remains unknown and is not proven to select user mode.

Transition shares bank `0x7fd20..0x7fed4`, SHA-256
`80d37f8c13ffdd054562b8106419445c3df9cf439c28d5428e88d708127b50bd`, with SIP; its
later tail is `0xff`, so reliance on a resident suffix remains a static hypothesis.
Tests retain only hashes, offsets, counts, and decoded relationships, not proprietary
firmware byte arrays.

Final verification from repository root:

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s refactor/tests -t . -v` | PASS, 208 tests |
| `python3 -B -m unittest discover -s tests/unit -v` | PASS, 59 tests |
| `python3 -B -m unittest discover -s tests/host -v` | PASS, 3 tests |
| `python3 -B -m unittest refactor.tests.test_zup_bank refactor.tests.test_mipsx_dasm refactor.tests.test_zup_rebuild -v` | PASS, 62 tests |
| `PYTHONPYCACHEPREFIX=PRIVATE_TEMP python3 -B -m compileall -q refactor tests telephony ata_flash.py dhcp.py ring_once.py` | PASS |
| `git diff --check` plus no-index checks for untracked firmware files | PASS before and after durable append |
| Workspace `*.pyc` and `**/__pycache__` searches | No files |

Current local/production state: the unborn-branch worktree remains intentionally dirty;
no staging or commit action occurred, and no generated firmware output entered Git.
Final review used local files, bounded subprocesses, and ephemeral loopback test
sockets. Public read-only HTTPS occurred during earlier source-lead research. No vendor
executable, ATA, VM, container, USB, device-facing socket, route, interface, DNS,
firewall, VPN, APU/alarm, printer, or production action occurred.

Remaining risks are outer resident `r23`/`r25`, type-3 PC-tag semantics, type-`0xd`
purpose, transition suffix/runtime reliance, nested-payload ownership, exact component/
source/compiler provenance, cross-zlib and independent vintage-inflater compatibility,
package/device authenticity, recovery, physical SoC identity, and device readback. The
next safe action is bounded offline component/provenance and archive comparison. Keep
all rebuilt or modified packages off hardware until separate recovery/authenticity
review and an explicit maintenance checkpoint approve them.

## Complete disassembly inventory and Git staging (2026-09-12)

This section supersedes earlier statements that no staging action occurred. At the
user's explicit request, the reviewed ZUP research is now staged; no commit was
created. The repository is still an unborn `main` branch with a broad index that
predated this request. Existing unrelated index entries and concurrent working-tree
changes were preserved.

`docs/firmware-analysis.md` now answers the disassembly question directly. The bounded
decoder can emit complete linear listings for the confirmed SIP and transition
resident regions and all three checked type-8 mode-0 programs. It also provides exact
private-output commands and distinguishes bank-offset coordinates from packed-output
coordinates. The verified listing sizes are 47,439 SIP resident words, 94,165 SIP-main
packed words, 17,275 SIP-auxiliary packed words, 45,399 transition resident words, and
91,034 transition packed words. This is disassembly plus optional xref and delay-slot
analysis, not decompiled source, recovered symbols, or a complete CFG.

The explicitly selected research paths are `THIRD_PARTY_NOTICES.md`, `TODO.md`,
`WORKLOG.md`, this handoff, `docs/firmware-analysis.md`, `refactor/mipsx_dasm.py`,
`refactor/zup_bank.py`, `refactor/zup_rebuild.py`, their three focused tests, and
`reports/security-2026-09-12-firmware-parsers.md`. `git add .` was not used. The
ignored Cisco package directory, optimized `.zup`, reconstructed banks, generated
instruction listings, and mixed concurrent updater/service files were not newly
selected by this request; unrelated files already in the broad index remain there.

Verification: all five complete listing commands returned exactly the documented line
counts. Temporary private banks were removed. Working-tree, no-index, and cached
whitespace checks passed. No generated bank/disassembly output or Python bytecode was
found in the nonignored project tree, and no ignored package, optimized firmware,
bank, or generated listing is tracked. With `ATA186_TEST_ARTIFACT_DIR` and
`ATA186_TEST_SWEDISH_PROFILE` pointed at the ignored local fixtures, the final gate
passed 208 refactor tests without skips, 67 unit tests, 3 host tests, and 62 focused
firmware tests without skips. The default clean-checkout refactor run separately
passed all 208 discovered tests with 51 expected fixture-dependent skips.

Current local/production state: no commit, remote, vendor execution, ATA contact, VM,
container, USB, device-facing socket, network mutation, APU/alarm, printer, or
production action occurred. Full listings remain reproducible private derivatives.
If tracking those large raw-word listings is desired despite the existing artifact
boundary, require a separate explicit scope and publication/license review first.

## Public ATA Tools release curation (2026-09-12)

This section supersedes earlier firmware-gate statements for release readiness;
older sections remain as historical context. No commit, remote, push, live
interface, route, BPF, QEMU, ATA, DTMF, or device operation occurred in this
batch.

Changed files: `README.md`, `refactor/README.md`, `refactor/FLASHING.md`,
`docs/ata-firmware-maintenance.md`, `docs/firmware-analysis.md`, `LICENSE`
(new BSD-3-Clause per owner selection), `THIRD_PARTY_NOTICES.md`,
`refactor/ata_upgrade_client.py` (docstring only),
`refactor/tests/__init__.py` (docstring only), plus local-only `TODO.md`,
`WORKLOG.md`, this handoff, and
`reports/security-2026-09-12-public-release.md`. No executable logic changed.

Tests: `python3 -B -m py_compile` over all 25 allowlisted files PASS;
`git diff --check` PASS; `tests.unit.test_ata_flash tests.unit.test_dhcp`
21 PASS; public refactor suite 152 PASS with 51 clean-checkout skips;
artifact-backed refactor subset 143 PASS with zero skips, including the
previously failing include-depth vector; full `tests/unit` 67 PASS; full
`refactor/tests` 208 PASS with 51 clean-checkout skips; `tests/host` 3 PASS;
`--inspect`/`--qualify`/`zup_bank` report the pinned
`b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5`,
312 blocks, 319135 bytes, `158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2`,
and `6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0`;
bare `ata_flash.py` and `sata186us.py` remain inert.

Deployment: none. No host route, interface, DNS, filter, VPN, VM, container,
APU, alarm, printer, or production change was made or is authorized here.

Verification: allowlist scans found only expected broadcast, synthetic
documentation, QEMU-default URL, and ignore-list mentions. Public guides no
longer contain fixed bench addresses, device MACs, capture mode, or live QEMU
paths. The exact 25-file allowlist and sizes are recorded in `WORKLOG.md`.
Hardware flash, reboot, registration, ringing, and audio remain unperformed;
Asterisk integration remains future work.

Next safe action: clear the unsafe unborn-branch index without touching the
worktree, stage only the explicit allowlist, review the actual staged diff for
untrusted-input-inbound risks, then commit, add the remote, push, and inspect
the public repository. Do not commit the current broad index wholesale and do
not discard local work.

## Public repository published (2026-09-12)

This section supersedes the pre-publish next action above; earlier sections
remain as historical context. The allowlist correction is recorded here: 27
total files, of which 18 are Python.

Tests: pre-commit release evidence stands for the published commit because the
pushed files match the audited staged snapshot. Post-publish local state was
not re-tested as a release gate.

Deployment: root-commit `032deb7` pushed as `main -> main` to
`https://github.com/kugg/ATA-tools` (PUBLIC, default branch `main`). Remote
`HEAD` and `refs/heads/main` are `032deb72fcf9b766e589595b044ac37c36058d79`.
Remote tree holds exactly the 27 intended paths; no task, report, telephony,
QEMU, `ring_once.py`, `AGENTS.md`, `TODO.md`, `WORKLOG.md`, handoff, or
`zup_launch_trace` entries are published. No host, VM, device, APU, alarm,
printer, or production change occurred.

Verification: `git log`, `git ls-remote`, `gh repo view`, and the recursive
remote tree were inspected from the repository root. `git status` shows
`main...origin/main` with only local-only modifications and untracked private
paths remaining outside the published snapshot.

Concurrent work: the worktree now shows `M docs/firmware-analysis.md` and `M
refactor/README.md` referencing `refactor/zup_launch_trace.c` and
`refactor/tests/test_zup_launch_trace.py` (both untracked). That work was
preserved, not reviewed, not staged, not committed, and not pushed.

Next safe action: review that concurrent trace model separately, then decide
whether a follow-up public commit is wanted. Keep hardware flash, reboot,
registration, ringing, audio, and Asterisk integration as unperformed future
gates. Do not force-push, revert others' work, or publish local records.

## Local-only launch-trace model verified (2026-09-12)

This section does not supersede the published snapshot; it records local-only
follow-up state. No commit, staging, remote, push, vendor execution, ATA
contact, VM, container, USB, device socket, network mutation, APU/alarm,
printer, or production action occurred.

Changed files (all local-only, left unstaged): `refactor/zup_launch_trace.c`
(new), `refactor/tests/test_zup_launch_trace.py` (new),
`docs/firmware-analysis.md` (stale type-6 fix),
`refactor/README.md` (tool/test usage), plus local-only `TODO.md`,
`WORKLOG.md`, and this handoff. The published `main` at `032deb7` is
untouched; no allowlist extension was made.

Tests: strict C11 compile PASS; `test_zup_launch_trace` 21 PASS clean (3
pinned skips) and 21 PASS artifact-backed; full `refactor/tests` 229 PASS
clean (54 skips) and 229 PASS artifact-backed; focused firmware 83 PASS;
`tests/unit` 67 PASS; `tests/host` 3 PASS; private-cache `compileall` PASS;
`git diff --check` PASS. Pinned SIP validator selects main
(`0x61f0752a`); transition reports unsupported marker mismatch; terminals
`0x400031d3`/`0x40000c00`/`0x40003d07` match `parse_launch_table()`.

Verification: local files, bounded subprocesses, and ephemeral loopback test
sockets only. Private banks/binaries/bytecode were removed after the run.

Unresolved risks: outer `r23`/`r25` init, type-3 `0x40000000` meaning,
type-`0xd` purpose, transition suffix reliance, provenance, SoC identity,
device readback, and publication/license review for this C work.

Next safe action: only on explicit owner request, run a separate
scope/test/publication/license review for a follow-up public commit covering
this trace model. Otherwise continue offline component/provenance work.
Hardware service remains a separate explicit checkpoint with no retry.

## Local-only research/ directory (2026-09-12)

Per operator request, full disassembly now persists in owner-only `research/`
(`0700`, files `0600`): five listings at their canonical line counts (47439,
94165, 17275, 45399, 91034) plus a manifest README with commands and hashes.
Banks were rebuilt in a private temp dir outside the repo, hash-verified,
used read-only, and removed afterward. `research/` is untracked and stays
local-only by explicit confirmation; it was not staged, committed, or pushed,
and must not enter any allowlist without a separate publication/license
review. `git diff --check` passes and the public snapshot at `032deb7` is
untouched.

`research/src/` (gitignored via root `.gitignore`, local-only) now holds
byte-identical copies of both C-test files so the tree rebuilds standalone;
strict compile plus a synthetic stdin trace were verified from the copies and
the build temp removed. `.gitignore` itself is modified only in the worktree
and was not staged.

## Component layout follow-up (2026-09-12, local-only)

No staging, commit, push, device, VM, or network action. Offline read-only
survey only, all derivatives local-only.
Changed: `docs/firmware-analysis.md`, `TODO.md`, `WORKLOG.md`, this handoff.
Web UI found as `printf`-style HTML templates in SIP mode-1 data (bank
`0x6cbcc` → span `0x2fbc..0x7b84`; `/dev`, `/rtps` links), shared with
transition (`0x73ce2`/`0x73e42`). Bank fill map: ~90 KiB never-mapped `0xff`
including a `0x11500` hole at `0x2eb00..0x40000`; filename slot at `0x2ea0c`;
984 `0xff` pad past helper end `0x7eb28`; dial-plan-like tail text (described
only); call-control-like strings in nested output `0x2c9d4`. Still no
archive/filesystem container. `git diff --check` passes; public `032deb7`
untouched.
Next safe action: loaded-span semantics, type-`0xd`/type-3 unknowns, and
bootstrap state; web-UI serving behavior stays a device-side question with no
hardware contact authorized here.

## Edit-and-rebuild pipeline (2026-09-12, local-only)

No staging, commit, push, device, VM, or network action. New local-only
`refactor/zup_extract.py` + `test_zup_extract.py` (10 tests): extract a
package to an editable directory (bank, manifest, expanded payloads), compose
edits back with fail-closed validation and in-place repacking, rebuild via
`zup_rebuild.py`, re-verify by re-expansion. Proven on pinned images:
identical round trips plus an edited SIP rebuild reconstructing its edited
bank exactly. Gates: 239 refactor, 67 unit, 3 host, compileall, diff-check
all pass. Public `032deb7` untouched; tracking needs a separate review.

## Decompilation tooling published (2026-09-13)

Per owner selection (tooling public, proprietary results private; exclude all
`.c`; exclude TODO/WORKLOG/AGENTS), a large concurrent staged batch was
reset down to the public tooling and pushed as commit `7b27318`
(`032deb7..7b27318`, 21 files, 2413 insertions) to
`https://github.com/kugg/ATA-tools` (PUBLIC, default branch `main`).

Changed files: `MIPSX_Ghidra_ATA186/` processor module + synthetic smoke
vectors, `refactor/CreateFunc.java`, `DecompileAll.java`/`.py`,
`SeedDisasm.java`, `SeedDisassembly.java`, `analyze_got.py`, `analyze_xrefs.py`,
`build_name_map.py`, `decompile_ghidra.py`, `ghidra_decompile.py`,
`zup_extract.py`, `refactor/tests/test_zup_extract.py`, and `.gitignore`.
The three analyze scripts' hardcoded `/Users/user/devel/ata/research/...`
paths were rewritten to repo-relative `ROOT`; `.gitignore` now ignores all of
`research/` so disassembly dumps, decompiled C, and rename maps cannot be
published accidentally. Trailing whitespace in the staged tooling was trimmed.

Tests: `py_compile` PASS; `MIPSX_Ghidra_ATA186/tests/mipsx_smoke.py` exit 0;
`refactor.tests.test_zup_extract` 12 tests OK with 3 artifact-gated skips on
clean checkout; `git diff --cached --check` PASS; staged-diff scans show no
`/Users/`, `/home/`, bench topology, or credentials.

Deployment: none other than the git commit/push. No host, VM, device, APU,
alarm, printer, or production change; no route/interface/DNS/filter/VPN change.

Verification: remote tree at `7b27318` holds exactly the intended paths; no
`.c`, `research/`, launch-trace test/doc edits, AGENTS/TODO/WORKLOG/handoff,
prserv/QEMU content is published. Uncommitted local-only: the
`zup_launch_trace.c` model, its test, and the launch-trace edits in
`docs/firmware-analysis.md`/`refactor/README.md` await a separate scope
decision (if published later, the test's hard dependency on the `.c` must be
addressed first).

Next safe action: decide the launch-trace scope, then keep hardware flash,
reboot, registration, ringing, audio, and Asterisk integration as unperformed
future gates. No force-push; no revert of concurrent work.

## dhcp.py directly callable again (2026-09-14)

Changed files: `dhcp.py` (parse_options + main + `_config_from_args`),
`tests/unit/test_dhcp.py` (3 new tests), `README.md` (dhcp.py row),
`WORKLOG.md` (this entry). `ata_flash.py` has unrelated pre-existing
uncommitted route-read changes that are NOT part of this work.

Behaviour: dhcp.py stays a library; `run_dhcp(DhcpConfig)` unchanged. Direct
invocation without --apply prints `DRY RUN: no sockets opened. Re-run with
--apply and --interface to offer one DHCP lease.` and exits 0. With
`--apply --interface NAME` it derives the default config from the interface
(server address via scapy.get_if_addr, /24, client = host 10, optional
`--client-address`, optional `--client-mac`, `--lease-seconds`,
`--timeout-seconds`) and runs the bounded single-lease responder. `--apply`
without `--interface` exits 2 with usage.

Verification: `python3 -B -m unittest tests/unit/test_dhcp.py
tests/unit/test_bench_safety.py` -> 26 OK. Full `tests/unit`: 66 OK plus 4
pre-existing `test_ata_flash` NetworkTest failures (default uplink & gateway
override, multiple addresses, current-address/connected-subnet, numeric route
overlap) that reproduce with HEAD dhcp.py; root cause is the uncommitted
`ata_flash.py` `_netstat_route_records` change, not this work.

Local state: no device, host, VM, route, interface, DNS, filter, VPN, APU,
alarm, printer or production change was made. No commit was created.

Next safe action: review the unrelated working-tree `ata_flash.py` route-read
change (it makes its NetworkTest suite fail) before re-running `--apply` on a
bench interface; then, on the bench, `python3 -B dhcp.py --apply --interface
<EN>` with a dry-run check first.

## ata_flash.py Darwin route parse fix resolved (2026-09-14)

The "unrelated working-tree route-read change" described above was completed and
its NetworkTest failures are resolved. The pre-flight crash that the previous
section lists is no longer present.

Changed files: `ata_flash.py` (new `_netstat_route_records` and
`_capture_route_records`; `current_interface_state` now reads routes through the
latter), `tests/unit/test_ata_flash.py` (new `RouteCaptureTest`, 3 tests),
`WORKLOG.md` (this entry).

Root cause: on macOS scapy's PF_ROUTE parser populates
`scapy.conf.route.routes` with corrupted IPv4 netmasks (multicast
`224.0.0/4` -> `240.255.255.0`/`0xF0FFFF00`, connected `192.168.0/16` ->
`0xFFFFFFFF`/`/32`). The strict `_route_network` validator aborted the read-only
preflight before any overlap decision. scapy.arch.unix's netstat-based
`read_routes()` produces the correct masks. The fix validates scapy's records and
falls back to the netstat parser only when a record cannot be parsed, keeping
clean test doubles and non-Darwin platforms unchanged.

Verification (repository root):

| Command | Result |
| --- | --- |
| `python3 -B -m unittest tests.unit.test_ata_flash -v` | 19 PASS |
| `python3 -B -m unittest tests.unit.test_dhcp tests.unit.test_bench_safety -v` | 26 PASS |
| `python3 -B -m py_compile ata_flash.py` | PASS |
| Temp bench venv (scapy 2.7.0) preflight route capture | 22 records parse with correct netmasks; parse crash gone |

Current state: the en28 preflight now fails closed on a genuine condition --
`ata_flash.FlashError: selected subnet overlaps another active route
(192.168.1.0/24)` -- because en28's `/16` netmask numerically covers en0's office
LAN `192.168.1.0/24`. This is not a parser bug. Resolving it requires the
operator to narrow en28 (e.g. to `192.168.2.0/24`); interface/route
reconfiguration is agent-out-of-scope per AGENTS.md. No maintenance checkpoint
entry was recorded in WORKLOG/handoff yet, and physical flashing still requires
one explicit operator-attended approval with routes/NWI snapshots, confirmed
`192.168.2.2`/ATA `192.168.2.10`, free UDP 8000/8500, and no automatic retry.

Next safe action: coordinate the en28 netmask change with the operator, re-run
the read-only preflight under the bench venv, then (only when green and after an
explicit maintenance checkpoint) run `ata_flash.py --apply` with the pinned
`optimized/SHA256SUMS` manifest and operator-attended DTMF, recording
before/change/verify/rollback/outcome in WORKLOG.md.

## Live window attempt 2026-09-14 (fail-closed before DHCP)

The en28 netmask was narrowed to 255.255.255.0; read-only route/NWI snapshots
confirm `192.168.2.0/24` no longer overlaps `192.168.1.0/24`, ATA `192.168.2.10`
(MAC `00:07:0e:36:e5:7b`) is present on en28, UDP 8000/8500 are free, and the
bench-venv preflight returns a green interface state. A maintenance-checkpoint
entry and the exact command were recorded in WORKLOG.md, then the live window was
launched once from this shell.

Result: it exited immediately after printing image/network verification with
`error: DHCP capture could not start; no privilege change was attempted`. The
process made no owned change, kept no listener, and sent no packet or DTMF.
Cause: `/dev/bpf*` are `crw------- root wheel`, so scapy's `sniff` cannot open a
BPF capture from this non-root shell. The earlier successful `dhcp.py --apply`
exchanges were run by the operator in a privileged terminal.

Current state: nothing changed on the host, device, or network. No re-run was
attempted from this shell.

## First hardware upgrade attempt failed (2026-09-14)

The operator ran the identical command in a privileged terminal during an
attended window and reported "Upgrade failed", capturing a tcpdump (13:36-13:37,
en28). It shows: DHCP DISCOVER/REQUEST+OFFER/ACK for `00:07:0e:36:e5:7b` and
`192.168.2.2` replying, ARP announcement/resolution for `192.168.2.10` /
`192.168.2.2` (`00:e0:4c:68:14:df`); then TFTP `RRQ "ATA00070E36E57B.cnf.xml"`
to `192.168.2.2:69` answered only by `ICMP udp port tftp unreachable`; then
repeated 56-byte UDP from the ATA to `192.168.2.2:8000` every ~3s. The mDNS
rows are normal macOS traffic.

Interpretation recorded in WORKLOG: the ATA bootstraps via TFTP fetching a
MAC-named config profile (`ATA00070E36E57B.cnf.xml`) and its loader traffic on
UDP 8000 does not match the KBOX wire format that `sata186us.py`/`ata_flash.py`
implement. The qualified QEMU loopback exercised our own client, not this
device, so the transfer protocol is now contradicted by physical-device traffic;
no image-integrity or network fault is indicated. Nothing was redialed, replayed,
or retried; the window ended by itself, in full compliance.

Next safe action (needs review + separate approval): capture the UDP 69 and UDP
8000/8500 payloads read-only (`tcpdump -XX -s0` in the operator's privileged
terminal) during one fresh attended boot, decode against the vintage
`refactor/cfgfmt.py` profile format and the `upgradecode` research lead, then
decide whether a bounded TFTP-and-loader service is the right path. Until then
no further `100#` firmware attempt should run.

## Device selection frame decoded; KBOX parser fixed (2026-09-14)

The captured `ata_boot.pcap` contained only identical 56-byte KBOX selection
frames from `192.168.2.10` to `192.168.2.2:8000` (retransmitted every ~3s). The
frame decodes cleanly: magic `kbox`, version 1, length 40, checksum `0x064e`
validates, payload platform `0x301`, `(proto<<16)|version = 0x0400|0x0302`
(this ATA runs SCCP 3.2(4)), base_type 0, selector
`ata00070e36e57b 0100 0001 1`. Our parser rejected it at the numeric-token
stage because `int(tok, 0)` raises on Python 3.11 for leading-zero tokens
`0100`/`0001` (legacy frames are `atoi` decimal), so the server never responded
and the ATA kept retransmitting. The vintage C server and our simulator both
use decimal, which is why only a real device frame exposed it.

Fix (in `refactor/sata186us.py` `_parse_kbox_request_with_reason`): parse the
three trailing tokens with `int(tok, 10)`; all other KBOX checksum/framing/
version/printable rules unchanged. Added regression test pinned to the exact
captured frame. Verified: refactor suite 242 OK (57 skipped), unit 73 OK, host
3 OK, regression test passes. The frame now yields
`(0x301, 0x04000302, 0, "ata00070e36e57b", 100, 1, 1)` and matches the pinned
SIP target (platform 0x301, base_type 0), so a live server would now answer
`build_kbox_response(...)` instead of counting the request invalid. Full
details and exact hex in WORKLOG.md.

Interpretation update: the TFTP `ATA00070E36E57B.cnf.xml` RRQ seen earlier is
the ATA's normal SCCP config bootstrap; the upgrade dialogue over UDP 8000 is
indeed the KBOX format this project implements. The device->8000 stage is now
proven; the response URL syntax, data-port (8500) dialogue, and 312-block
delivery remain unproven against hardware.

Current state: no host, network, firewall, DNS, VPN, or device change. No
redial or replay. The server code and one test were modified and are uncommitted
in the intentionally dirty tree.

Next safe action (needs fresh operator approval + maintenance checkpoint): one
new attended live `ata_flash.py --apply` window for the same pinned command,
observing whether the ATA advances past selection to the data port and completes
all 312 blocks; any ambiguity is a stop condition, never permission to redial
or rerun.

## Live SIP transfer served; device acceptance pending (2026-09-14)

A fresh operator-attended live window (same pinned command, sudo) succeeded at
the wire level: image verified, DHCP OFFER+ACK locked `00:07:0e:36:e5:7b` at
`192.168.2.10`, service ready on 8000/8500, and the log reported "Python
firmware response stream complete (blocks=312, payload_bytes=319135)". The
operator overwrote `ata_boot.pcap` with the full capture (364,458 bytes, 630
packets). Independent decode confirms: the 56-byte KBOX selection on 8000 was
answered (144-byte response), and the ATA-8500 dialogue contains exactly one
hello plus 312 block requests with zero invalid frames and unique indices
covering 0..311, matching 319,135 payload bytes. This proves the designed
selection+hello+block dialogue against physical device traffic; it supersedes
the earlier protocol-mismatch concern (root cause: `int(tok, 0)` rejecting the
device's leading-zero legacy tokens, fixed and regression-tested in
`refactor/sata186us.py`).

Current state: the ATA must now reboot and load the SIP image. Not yet proven:
device-reported firmware via `123#` (expect SIP 3.1(0)), registration, ringing,
and audio. A served stream is not a flashed device; these acceptance checks are
the operator's next report. No redial, replay, or automatic re-run. The pcap is
local evidence (root-owned, uncommitted). WORKLOG.md records the full
before/change/verify/rollback/outcome.

Next safe action: the operator runs the identical `ata_flash.py --apply`
command themselves in a privileged terminal (their established `dhcp.py --apply`
pattern), attends the ATA handset, enters `100#192*168*2*2*8000#` once after the
service-ready message, lets the bounded window finish, and verifies with `123#`;
any ambiguity is a stop condition, not permission to redial or rerun. The agent
can observe the private log and coordinate, but the DHCP capture requires the
operator's terminal.

## SIP 3.1(0) confirmed; bench SIP/TFTP tools built (2026-09-14)

`123#` on the handset now reports the correct version (SIP 3.1(0)); the earlier
flash is accepted at the firmware level. The ATA's HTTP admin is up and
unauthenticated (`curl http://192.168.2.10/dev.xml` -> full `ATADev` XML, 80
fields). Current device state: UseTftp=1, TftpURL=0, CfgInterval=3600,
GkOrProxy=0, SIPRegOn=0, SIPPort=5060, MediaPort=16384, IPDialPlan=1,
MAC=00070e36e57b. Profile/registration/audio remain unverified; device boots and
TFTP-RRQs an `ATA<MAC>.cnf.xml` profile (seen unanswered in prior captures).

New offline work (nothing bound to the network yet; all uncommitted):
- `telephony/ATA00070E36E57B.cnf.xml` - bench profile from live `/dev.xml` with
  only GkOrProxy=192.168.2.2, SIPRegOn=1, SIPRegInterval=60 changed.
- `telephony/tftp_profile.py` - bounded RFC1350 octet TFTP server (UDP/69),
  allow-list filenames only, fixed expected client, one transfer at a time,
  bounded run/retransmit, dry-run default, `--apply` to bind (needs root).
- `telephony/sip_bench_proxy.py` - bounded SIP registrar/UAS (UDP/5060+RTP),
  REGISTER->200 OK, INVITE->100/180/200 with PCMU SDP, streamed 440 Hz tone,
  inbound RTP counted not stored, one dialog, bounded call/run, dry-run default.
- `tests/unit/test_tftp_profile.py`, `tests/unit/test_sip_bench_proxy.py` - 32
  offline tests. Suites: unit 105 OK, refactor OK (57 skipped), host 3 OK; both
  new CLIs dry-run exit 0.

Verification commands:
- `python3 -m unittest tests.unit.test_tftp_profile tests.unit.test_sip_bench_proxy`
- `python3 telephony/sip_bench_proxy.py --run-seconds 5` (dry run, no --apply)

Current state: no host network/VPN/firewall/DNS/device change; no redial/replay.
WORKLOG.md records before/change/verify/rollback/outcome.

Next safe action (operator-attended): in a privileged terminal run
`sudo python3 telephony/tftp_profile.py --apply --profile telephony/ATA00070E36E57B.cnf.xml --allow-name SIP00070E36E57B.cnf.xml --run-seconds 180`,
then `python3 telephony/sip_bench_proxy.py --apply --expected-peer 192.168.2.10 --run-seconds 180`,
power-cycle the ATA so it fetches the profile, watch REGISTER on 5060, lift the
handset and dial extension 100, and verify ringing plus the audible repeating
tone (`rtp_tx`/`rtp_rx` counters prove media). Re-check `/dev.xml` (GkOrProxy
and SIPRegOn should read applied) as the profile-application proof. Any
ambiguity is a stop condition, not permission to redial or rerun.

## 2026-09-14 — DHCP TFTP options added; ATA not yet provisioned

Unresolved risk as of this entry: ATA (SIP 3.1.0) never requested TFTP config
at boot because the DHCP reply carried only BOOTP siaddr and no DHCP TFTP option.
Root cause confirmed against sip_example.txt: TftpURL:0 means "use DHCP-provided
TFTP URL"; absent that, no auto-provisioning. Fix committed to the working tree
(not git): dhcp.py now sends option 66 (tftp_server_name) + 150
(tftp_server_address) = 192.168.2.2 in OFFER and ACK.

The bench services to run (all local, bounded):
- sudo python3 dhcp.py --interface en28 --apply          (root; terminal A)
- sudo python3 telephony/tftp_profile.py --apply --profile
  telephony/ATA00070E36E57B.cnf.xml --allow-name SIP00070E36E57B.cnf.xml
  --expected-client 192.168.2.10 --run-seconds 1800      (root; terminal B)
- python3 telephony/sip_bench_proxy.py --apply --expected-peer 192.168.2.10
  --run-seconds 3600 --call-seconds 90                   (non-root; watching)
Then ONE power-cycle of the ATA (operator-attended). Expected at boot: DHCP
OFFER/ACK, then TFTP RRQ of profile, then REGISTER to 192.168.2.2:5060, then a
call to 100 with ringing + repeating tone. If the RRQ still does not arrive,
capture: sudo tcpdump -i en28 -nn -e -s0 -w /tmp/ata_repro.pcap -c 300 during
the same boot and decode what the ATA requests.

Do NOT auto-redial, replay tones, or reprint after ambiguous delivery. No further
manual reboots are allowed once the unit is shelved behind the APU2 network.

## RTP drain fix, hardware gate proven, telephony milestone publication (2026-09-14)

Before: `_rtp_receive()` in `sip_bench_proxy.py` used a blocking UDP recv, so a
peer that never sent media (e.g. phone that only receives) could stall the proxy
loop indefinitely even after the call ended. All remaining hardware gates were
open: profile application, registration, ringing, and audio.

Change:
- `telephony/sip_bench_proxy.py:369`: `rtp_sock.setblocking(False)` after bind so
  the media loop drains non-blocking; `_rtp_tick()` continues even when the receive
  buffer empties. Added `_DrainingSock` regression test and
  `test_rtp_drain_returns_when_buffer_empties` in `tests/unit/test_sip_bench_proxy.py`.
- Hardware gate (operator-attended, isolated bench, en28): power-cycled ATA ->
  DHCP OFFER/ACK (with options 66/150, from prior entry) -> TFTP RRQ served and
  profile applied -> REGISTER -> 200 OK on 5060 -> INVITE -> 100/180/200 with
  PCMU SDP -> two-way audible RTP. The repeating tone is the deliberate pulsed
  440 Hz test tone (300 ms on / 1.2 s off), not rejection.
- README.md rewritten: `telephony/` now the primary tooling directory; added
  installation instructions (`python3 -m venv .venv && pip install -r
  requirements-bench.txt`, scapy 2.7.0 for `dhcp.py --apply` only), bench
  verification workflow, and testing instructions. Roadmap leads with
  "Modern Asterisk integration is the next project."
- Publication sanitization: `refactor/tests/test_sata186us.py` regression frame
  replaced with synthetic `ata000000000001` (checksum 0x597); `tests/unit/test_tftp_profile.py`
  uses `ATA0000000EXAMPLE.cnf.xml` instead of device profile name.
- Decompilation tooling published: `refactor/build_comprehensive_names.py` and
  `refactor/deep_got_analysis.py` — `ROOT = Path(__file__).resolve().parents[1]`
  replaces the prior absolute `/Users/user/...` paths; trailing whitespace stripped.
  These scripts take Ghidra-decompiled C and apply heuristic naming (SIP/transition
  bank functions); they write to `research/` which is gitignored.
- `research/decompiled/named/*` (4 files: AI-derived ASM-to-C of the firmware
   loader, proprietary-feeling Cisco code) explicitly NOT published; unstaged,
   gitignored, local-only. Device identity files (`telephony/ata00070e36e57b.txt`,
   `telephony/ATA00070E36E57B.cnf.xml`) likewise kept local-only.
Network identification corrections (2026-09-14): `getuid` (709 calls) corrected
    to `printf` in `sip_rename_map.json`, `rename_map.json`, `sip_bank_named.c`,
    and `network_identification_report.md`. 15 function definitions renamed: 12 →
    `printf`, 3 → `socket`. No Unix syscalls (`getuid`, `exec`, env vars) exist in
    this Cisco SIP firmware; all identified network functions are C library calls.
    Later 2026-09-14 dispatch table investigation: `printf`, `socket`, `str_copy`,
    `close`, `listen`, `setsockopt` were ALL misidentified — they are indirect call
    stubs `(*(code *)((in_r24 + offset) * 4))()`, not library functions. The firmware
    uses a table-driven dispatcher with `register0x00000074` as the function pointer
    table base, initialized by `sip_dispatch_table_init`. All 1400 `sip_func_XXXXX`
definitions are indirect call stubs.
Later 2026-09-14 dispatch table function identification: applied
      `got_mapping.json` classifications to rename 217 functions across all
      3 destination code files: 175 dispatcher_XXXXXX, 34 str_copy_XXXXXX,
      5 error_handler_XXXXXX, 4 packet_recv_XXXXXX, 3 msg_buffer_handler_XXXXXX,
      and 3 validator functions. Updated sip_rename_map.json (1847 entries),
      rename_map.json (1847 entries), sip_bank_named.c (452 occurrences).
      All misidentified names fully resolved; 0 printf/socket/str_copy/FUN_
      definitions remain.
  - Later 2026-09-15 stack-based dispatch investigation: identified TWO
      dispatch patterns. Table-based `(in_r24 + offset) * 4` uses
      `register0x00000074` as the dispatch table base. Stack-based
      `*(int *)(reg + offset) << 2` (404 total: 230 via register0x00000074
      + 174 via in_r30) uses the SAME struct at `register0x00000074` —
      `in_r30` is an alias for `register0x00000074`. The struct contains
      BOTH dispatch indices (negative offsets: -0x10, -0x18, -0x20, etc.)
      AND dispatch table entries (positive offsets: +4, +8, +0xc, etc.).
      The dispatch index at the negative offset indexes into the dispatch
      table entry at the positive offset. All 404 stack-based dispatch
      functions are already classified in got_mapping.json. Resolution
      approach: trace struct initialization to map dispatch indices →
      dispatch table entries → classified function names.
  - Readability optimization complete (2026-09-15): all 1630
      sip_func_XXXXX functions renamed to classified names in
      sip_bank_named.c and transition_bank_named.c. All 808 indirect
      calls annotated with dispatch table comments.
      sip_bank_named_readable.c generated. readability_report.md
      generated. 0 remaining sip_func_ references. Original
      sip_bank_named.c backed up to sip_bank_named.c.bak.
  - Staged set: 29 files (tools, tests, dhcp, ata_flash, SATA KBOX fix, README,
   decompilation tooling, refactor README update, test sanitization).
   `docs/firmware-analysis.md` and `refactor/README.md` launch-trace diffs
   remain unstaged (local-only).

Verify (repo root):
- `python3 -B -m unittest discover -s tests/unit` -> 119 OK
- `python3 -B -m unittest discover -s tests/host` -> 3 OK
- `python3 -B -m unittest refactor.tests.test_sata186us` -> 26 OK (5 skipped)
- `python3 -B -m py_compile refactor/build_comprehensive_names.py refactor/deep_got_analysis.py` -> OK
- `git diff --cached --check` -> clean exit 0
- Identity scan: no `00070e36e57b`, `/Users/user`, or other device identity in staged diff
- Stray bench proxy processes (pids 82686/82838/82839) confirmed gone

Current state: staged set ready to commit and push. The bench is quiescent; no
processes or listeners remain. Device-specific profile files and the AI-derived
named bank C are local-only (gitignored, not committed).

Next safe action: commit and push the 29-file telephony milestone, then plan
Asterisk integration as the next project. After that, the bench SIP path
(DHCP options 66/150, TFTP profile provisioning, registrar/UAS with PCMU RTP)
is the proven foundation that the Asterisk endpoint will build on.

## Dispatch-target resolution campaign (2026-09-15, local-only)

The 9602 annotated indirect calls in `research/decompiled/named/` cannot be
resolved statically: proven that the 512 KiB bank contains no code-pointer
table (only 24 stray data words). Targets are built at runtime. A local
MIPS-X interpreter (`research/dispatch_resolve.py`, gitignored) executes the
boot tail from the reconstructed RAM image and reached the inflate helper
(~4M steps); it is not yet boot-faithful. Blockers: hardware preset
registers at reset (r13/r27/r2/r10) and the 0x40000000 PC-tag semantics of
the terminal type-3 record (0x400031d3 -> byte 0xc74c). Next safe action:
finish the reset-preset reverse-engineering from the resident tail indices
(0x7fef0 validator return context, 0x7ff60 linked call), then re-run the
emulator to dump slot->target pairs and rewrite annotations as resolved
names. The readability C remains annotation-only until then.

## Dispatch resolution complete for the r24 family (2026-09-15, local-only)

DISPATCH TABLE DOES NOT EXIST: the stubs are pc-relative `jspci r24,disp`
calls (r24 word base 0x33F0280); target = 0x0cf80000 + (0x40a00 + 4*off),
proven by execution (research/boot_run.py + main_run.py: memory = expanded
bank, 1 MiB page mask, SFR @ 0x20000000; entry 0x7ff80 boot or 0xc74c with
launch ABI; validator bypass injects r2=r5=0x0cfc0100). The in_r31 pattern
is the return epilogue (link register), not a return value; 100 epilogues
rewritten as return;. sip_bank_named_readable.c now has 5836 named calls
(824 targets, 253 classified); signatures in research/signatures.json.
Next: r30/S-struct family via emulator RAM snapshot; call-site return-type
derivation from r2.
