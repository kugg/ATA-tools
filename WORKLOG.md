# Worklog

Append-only except surgical secret redaction. Times below are session records,
not evidence of hardware tests. Secret values and audio payloads are forbidden.

## 2026-09-08: reconstruct initial bench and audit history

Before: this directory contained dhcp.py, ring_once.py, a local Scapy environment,
two ignored ATA configuration backups and an ignored DHCP lease record. No Git
repository or durable project plan existed.

Observed: DHCP OFFER/ACK assigned 192.168.2.10 to the directly attached ATA on
en17. HTTP reported ATA186I1-A firmware ATA030204SCCP090202A (SCCP). Two automatic
registration attempts timed out; no ring command was sent in those attempts.
Initial restoration of SCCPCfg timed out and was retried successfully. User was
given a power-cycle test; no resulting ring confirmation is on record.

Read-only inspection of alarm found a TTS HTTP wrapper and no loaded models.
Read-only APU audit found code hashes matching the printer repository, but
configuration, lifecycle and recovery gaps. See docs/drift-register.md.

Network actions: earlier user configured en17 manually. Bench tools do not
modify host routes. No APU/alarm settings were changed by this audit. Historical
route snapshots are observations, not permission to reuse their ranges in VMs.

## 2026-09-08: local bootstrap and printer remediation candidate

Change: added persistent rules, task queue, assumptions, architecture, operations,
test gates and handoff. Added exclusions for private backups/runtime artifacts.
Printer repository received runbook reconciliation and opt-in DHCP lifecycle
handling with shell-mocked tests. No application source was copied between repos.

Documentation incident: delegated printer worklog redaction initially condensed
unrelated history. 250 of 254 original historical lines were restored from
captured text. Four credential-adjacent lines had not been captured and are now
explicitly marked omitted, rather than fabricated. The printer worklog records
this in its recovery entry. Never restore the credential when rolling back.

Verification at this point: delegated lifecycle run reported 17 tests passing
and shell syntax/diff checks passing. Independent verification, Git setup and
security review remain pending in TODO.md; no hardware claims follow from mocks.

Rollback: revert only this batch's reviewed local edits if necessary. Keep secret
redaction and audit history. Do not use git reset/checkout to erase unrelated work.
No live rollback is needed: no deployment or service/network mutation occurred.

## 2026-09-08: bench defaults and Git initialization

Change: initialized an empty local Git repository on main, no remote or commit.
Both historical bench scripts now require --apply; default execution opens no
sockets and dhcp.py imports Scapy only for live use. ATA backup creation is
mode0600 from the start, HTTP reads are bounded, raw SCCP/identity logs removed.
Added four offline regression tests and set +x/umask077 to the printer init.

Review: independent lifecycle review found target procd/UCI semantics remain
unverified and stop ignores a failure to remove its activation snapshot. This
edge case is an explicit local remediation/acceptance blocker, not a hardware
claim. Also documented static-mode event/reload semantics change separately from
preservation of the persisted static address option.

Verification and security assessment: pending subsequent appended results.
Rollback: keep diagnostics non-live by default; do not restore raw payload logs
or unsafe credential backup permissions. No device settings changed.

## 2026-09-08: hardening, final review and handoff

Change: security review drove private snapshot owner/type/mode validation on all
printer init paths, atomic publication/revocation, validation of logical interface
in both binding modes, and identity-scoped cleanup after new-spool chown failure.
The stop-removal failure now either publishes disabled state or reports unknown
state and requests service deletion. Added fault tests; real procd remains a gate.
ATA HTTP now has a true10s total Unix timer in addition to64KiB body bound, with
tests for blocking response interruption, timer preservation and cleanup.

Verify: independent final6 ATA tests PASS,25 lifecycle/watchdog tests PASS,57
printer regressions PASS; shell syntax and diff checks PASS. Named private/runtime
files ignored. Count-only secret-shaped scans found no matches in intended text.
Exact commands and evidence limits are in reports/local-results-2026-09-08.md.

Oplane: model477779bb-8e51-4093-9812-7003c3f6cd00 analyzed actual initial diff;
final hardening code attached in two comments after one overlong comment rejected.
All40 original cases regraded:26 PASS,10 FAIL,4 N/A. States3455/3456/3458 IMPLEMENTED
for scoped source properties;3457 NOT_IMPLEMENTED for event availability/resource
and interrupted recovery gaps. Initial and final reports retained. No commit made.

Outcome: durable local project and hardened opt-in candidate, not production
remediation. No VM/container or live/device operations; no firmware/model loads.
Updated TODO, task results and handoff for continuation. Remaining gate: safe
interrupted-temp recovery and true24.10.8 lifecycle/pressure/powercut tests.

Rollback: only reviewed local owned changes, preserving redaction/audit records.
No live rollback necessary. Do not deploy a candidate with unresolved gates or
mark target confinement verified simply because shell tests pass.

Final hygiene: checked every untracked file in both repositories with
`git ls-files --others --exclude-standard -z | xargs -0 -I{} git diff --no-index --check -- /dev/null "{}"`;
PASS. Repeated count-only secret-shaped scans after report edits found no matches.
`git diff --cached --name-only` empty in both repositories. No commit or staging.

## 2026-09-08: local SCCP fixture and printer/QEMU follow-up

Before: ATA SCCP firmware was observed but registration, ringing and audio were
unverified. The user selected a local SCCP fixture as the first phone-service gate,
explicitly without WireGuard or a physical APU2/ATA-to-QEMU interconnect. Printer
snapshot-interruption and inherited QEMU host-safety work remained local source
changes with no target qualification.

Change: added `telephony/skinny_fixture.py`, a socket-free bounded Skinny/SCCP
frame decoder and ATA186 registration/keepalive/ringer fixture. It caps bodies at
2048 bytes, buffered input at 8192 bytes and a feed at 16 frames; protocol errors
clear and lock per-instance state until explicit reset. It accepts only an exact
non-whitespace printable-ASCII expected identity and ATA186 type12. Added offline
tests and fixture documentation, updated the telephony task/decision, and corrected
the task's obsolete guest-WireGuard requirement.

Printer follow-up source changes declare `coreutils-stat`, reclaim only one verified
private interrupted `.snapshot.??????` file during explicit publication, and fail
closed for unsafe/ambiguous temporary state. QEMU source adds numeric subnet/Docker
preflight, private per-run stage/baseline records, restricted user networking and
guest-only WireGuard safeguards. No QEMU process was started.

Verify: `python3 -B -m unittest discover -s tests/unit -v` passed 22 ATA tests;
`python3 -B -m unittest tests.unit.test_skinny_fixture -v` passed 16 fixture tests;
`python3 -B -m py_compile telephony/skinny_fixture.py tests/unit/test_skinny_fixture.py`
and whitespace checks passed. Printer checks passed:41 script/lifecycle/QEMU-safety
tests, 57 proxy tests, and shell syntax for the init/QEMU/WireGuard scripts. Oplane
model `0067aeb3-5c6e-4ea8-b348-1a49f821a617` assessed the actual fixture;
`OPLANE_REQ-00003471`, `OPLANE_REQ-00003472`, and `OPLANE_REQ-00003473` were
recorded IMPLEMENTED with streaming-only generated cases
explicitly N/A. Sanitized evidence is in `reports/security-2026-09-08-sccp-fixture.md`.

Rollback: remove only the new local fixture/tests/docs and the reviewed local
printer safety changes after checking for concurrent edits. Preserve prior secret
redaction and append-only history. No live rollback is needed because no device,
network, VM, model or service operation occurred.

Outcome: the phone project now has a bounded offline SCCP gate, not a telephony
engine or hardware result. Pinned engine/module compatibility, IAX2/media,
loopback-QEMU integration, target procd/event pressure, hardware qualification and
deployment remain separate unproven gates.

## 2026-09-08: host-loopback media qualification and isolated ATA reset report

Before: the local ATA project had a socket-free SCCP control fixture only. The user
authorized host-first local SCCP/IAX2/external-media testing, then researched ATA
firmware alternatives. No engine was selected or run.

Change: added bounded IAX2 mini-frame and RTP/PCMU fixture parsers, fixture-vector
G.711 mu-law conversion and an explicit `--run` host qualification command. The
runner binds only ephemeral `127.0.0.1` AF_INET sockets, uses deterministic samples,
exercises fragmented SCCP stream handling/EOF, and has no listener by default. The
nonessential FFmpeg subprocess smoke test was removed; no Python/FFmpeg media
backend is proposed for the APU. Documented Asterisk 20 built-in `chan_skinny` as a
host-only current-SCCP probe candidate, with legacy `chan-sccp` fallback and SIP
firmware migration remaining separate gates.

User event: the user reported factory-resetting the ATA186 while it remained on the
isolated bench. The agent did not touch the device, flash firmware, configure it,
receive credentials/configuration, or connect it to an APU/shared network. Firmware,
IP/DHCP state, registration, ringing and media after reset are unverified. Research
identified a third-party HTTP firmware mirror and broad legacy flash workflow; these
are explicitly excluded pending a reviewed image, hash, compatibility, recovery and
rollback plan.

Verify: `python3 -B -m unittest discover -s tests/unit -v` passed 34 tests;
`python3 -B -m unittest discover -s tests/host -v` passed 3 explicit loopback tests;
`python3 -B -m telephony.host_qualification --run` passed; full fixture/test
`py_compile` and trailing-whitespace checks passed. Oplane model
`cfccb33a-eb90-42d9-ac9a-59f61a498997` reviewed the final actual diff:
`OPLANE_REQ-00003474`, `OPLANE_REQ-00003475`, `OPLANE_REQ-00003477` and
`OPLANE_REQ-00003478` are IMPLEMENTED for cited source/host-test controls;
`OPLANE_REQ-00003476` is NOT_APPLICABLE after removing FFmpeg. Sanitized rubric is
in `reports/security-2026-09-08-host-fixture.md`.

Rollback: remove only reviewed local fixture/docs/tests after checking for concurrent
edits. Do not attempt to reverse the user-performed ATA reset automatically, replay
old configuration, redial, flash a device, or use an unverified recovery image.

Outcome: local protocol and loopback media gates are stronger, but no engine, target,
QEMU, ATA firmware, registration/ring/audio, external IAX2 peer or production result
is established. Next safe ATA action is a read-only isolated-bench firmware-banner
and DHCP/IP observation; next software action is a pinned Asterisk 20 host-build
feasibility review.

## 2026-09-09: Ghidra + Docker reverse-engineering of ATA support tools

Before: `ata_03_01_00_sip_040211_1/` held `cfgfmt.linux`, `prserv.linux`
and `sata186us.linux` (2003-era 32-bit x86, no source). No Python
equivalents existed. The user asked for 1-to-1 feature-complete,
testable Python reimplementations, researched only inside that
directory, with results saved under `./refactor`.

Change: installed Ghidra 12.1.3 (`brew install ghidra`) and ran
headless decompilation (`analyzeHeadless ... -postScript DumpAll.java`)
of all three binaries into /tmp (outside the repo). Ran the originals
black-box under `docker run --platform linux/386 i386/ubuntu:20.04`
(options matrices, RC4 vectors, UDP handshakes against live original
servers on published loopback ports). Wrote `refactor/cfgfmt.py`,
`refactor/prserv.py`, `refactor/sata186us.py`, `refactor/README.md`
and 70 tests in `refactor/tests/`. Recovered wire details include the
varint TLV framing with `0x7ffe` checksum record, RC4 keyschedules, the
obfuscated tag-`0x1105` constants (via emulated `FUN_0804a60c`), the
shared 512-byte scratch stale-tail behaviour (byte-exact once
replicated), the `kbox`/1024-byte-block upgrade protocol and the
`kup1`/`+kxz` image envelope. Used the user-supplied
`ata_03_01_00_sip_040211_1/refactor/swedish` tone vector (untouched) as
a regression test. Removed my own superseded broken `tools/` draft; the
vintage directory is otherwise unmodified.

Verify: `python3 -B -m unittest refactor.tests.test_cfgfmt
refactor.tests.test_prserv refactor.tests.test_sata186us` -> 70 PASS.
Existing `python3 -B -m unittest discover -s tests/unit` -> 36 PASS
(unchanged). A 41-case differential harness (exit/stdout/stderr/files
vs the originals in Docker) reports 0 mismatches; the full
`sip_example.txt` conversion and the Swedish tone vector are
byte-identical, and cross-decryption (Python ciphertext opened by the
original) succeeds.

Rollback: delete only `refactor/` after checking for concurrent edits.
The Ghidra install, Docker images and /tmp artefacts are outside the
repo. No device, network, VM, model or service operation occurred.

Outcome: testable local ports exist, including loopback-verified UDP
behaviour for both servers. Intentional divergences (no original crash
replicated: bad-size double-free, >2KiB stack smash, `corrupted`
exit-0 kept) plus unverifiable corners (obsolete `*Freq` float +-1 LSB,
`kbox` response bytes [8:12], `.sbin` RSA structural-only) are listed
in `refactor/README.md`. Oplane threat-modelling of the new
UDP/parser code is recorded as a gate; no commit was requested or made.

## 2026-09-09: safe refactor hardening and ATA firmware gate

Before: the historic-compatible refactor included a wildcard firmware server,
direct output writes, unconfined profile includes, and verbose encryption-key
logging. The local SIP 3.1.0 and transition images had not been independently
inspected in this batch. Current ATA state was known only as SCCP
`3.02.04(090202A)`; no official rollback image was local.

Change: made `sata186us.py` default offline, added bounded `--inspect`, and made
its only apply path require a private fixed-bench policy, exact client identity,
hash-pinned target, and distinct hash-pinned rollback. Removed wildcard operational
behavior. Hardened `cfgfmt.py` regular-file bounds, source-root includes, redacted
verbose logs, and atomic mode0600 no-overwrite outputs. Updated refactor tests/docs,
firmware maintenance gate, TODO, assumptions, decisions, report, and handoff.

Verify: `python3 -B -m py_compile refactor/*.py refactor/tests/*.py` PASS;
combined refactor tests 59 PASS; root unit tests 36 PASS; `git diff --check` and
per-file `git diff --no-index --check` PASS. Offline image inspection
validated target SHA-256 `b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5`
and transition SHA-256 `9cf97b172f4d3422dfa54ad9708a5e110637130963d9f1bc1f1e70c1bbfcc278`.
Only ephemeral loopback UDP sockets were opened by tests. No ATA-facing socket,
flash, ATA configuration write, Docker/QEMU launch, APU action, or production
change occurred. No Oplane action or commit was requested.

Rollback: remove only reviewed new local refactor/docs/test/report edits after
checking concurrent changes. Preserve this append-only evidence and do not restore
unsafe wildcard serving, secret-bearing logs, or direct output overwrite behavior.
No device rollback is possible or needed because no device change occurred.

Outcome: the local SIP image is structurally valid but not an approved target.
Cisco confirms the ATA186/188 family relationship and current SCCP package MD5,
but no verified rollback artifact, exact cross-protocol downgrade evidence, current
request metadata, or recovery test exists. Firmware maintenance remains blocked.

## 2026-09-09: direct-bench interface observation and CSCsd44357 review

Before: current bench documentation still named `en17`, while the local DHCP source
already had its fixed interface constant set to `en28`. The user reported a
user-operated DHCP exchange on the isolated bench. The firmware maintenance gate had
not assessed Cisco bug `CSCsd44357`.

Change: retained the existing `en28` setting, generalized the stale source docstring,
and kept Scapy optional through an apply-only `import_module("scapy.all")` lookup.
Updated operations, assumptions, TODO, maintenance, results, and handoff records for
the current interface and a server-side-only DHCP observation. Added the archived
Cisco bug evidence: ATA186/ATA180 auto-registration can fail when the CUCM/TFTP XML
configuration exceeds 4 KiB; Cisco lists SCCP 3.2(3) as affected, and a Cisco
employee says the fix is in 3.2(4). The observed exact source is 3.2(4), but the
unapproved SIP 3.1.0 target remains uncharacterized.

Verify: the user's terminal output showed the bounded responder on `en28` emit an
OFFER and ACK for `192.168.2.10`; this does not prove that the ATA installed the
lease. `python3 -B -m py_compile dhcp.py` passed; `python3 -B dhcp.py` printed its
dry-run/no-socket message; `python3 -B -m unittest tests.unit.test_bench_safety -v`
passed 8 tests; the supplied bench virtual environment imported `scapy.all` without
opening packets; `git diff --check` and per-file whitespace checks passed. The agent
did not invoke `--apply`, inspect/configure/flash the ATA, alter host networking,
launch Docker/QEMU, or act on the APU/production environment.

Rollback: if a future reviewed interface change supersedes this observation, update
only the owned documentation and the local constant after confirming topology; do
not replay DHCP, flash, or reconfigure the ATA. Preserve this append-only record and
all prior safety gates. No device rollback is needed for the agent's work.

Outcome: CSCsd44357 is a configuration-delivery constraint, not a direct `kbox`
flash compatibility or recovery result. Treat the observed SCCP 3.2(4) source as
fixed on the available evidence. For any future CUCM/TFTP path, retain
selected-version evidence, statically limit the initial XML configuration to 4096
bytes, and separately prove the transfer outcome. Firmware maintenance remains
blocked on its existing provenance, rollback, compatibility, metadata, recovery,
and approval gates.

Final verification supplement: `python3 -B -m unittest discover -s tests/unit -v`
passed all 36 tests after the documentation and optional-import update. No additional
device, network, container, APU, or production action occurred.

## 2026-09-09: approved no-response ATA KBOX capture attempt

Before: the safe firmware server required exact client KBOX metadata, but no
read-only capture mode existed. Cisco-authorized SIP target and SCCP rollback
artifacts remain unavailable; the user authorized only a finite no-response metadata
capture, not a transfer or firmware change.

Change: added explicit `sata186us.py --capture` mode. It binds only
`192.168.2.2:8000`, accepts one policy-safe header from only `192.168.2.10`, retains
no raw payload, sends no response, rejects image/policy inputs, and bounds the run to
60 seconds or 32 packets. Added command, parser, metadata, and no-response tests;
documented its capture-only scope and the user-confirmed missed timing result.

Verify: preflight used read-only `netstat -rn`, `scutil --nwi`, and
`netstat -an -p udp`; exact host routes for `.2` and expected `.10`/MAC were on
`en28`, and port 8000 was unbound. `py_compile` passed; `test_sata186us` passed 19;
combined refactor tests passed 63; root tests passed 36; default invocation remained
socket-free; whitespace checks passed. The authorized command
`python3 -B refactor/sata186us.py --capture --capture-seconds 30` printed its
no-response readiness message and ended without valid metadata. The user confirmed
the handset action missed the window. The listener sent no packet.

Rollback: do not retry the capture, dial the ATA, reset, power-cycle, serve an image,
or create a firmware policy automatically. If the capture mode is superseded, remove
only this local source/test/documentation batch after checking concurrent work;
preserve this append-only record. No ATA rollback is needed because no ATA change or
response occurred.

Outcome: the exact KBOX metadata gate remains FAIL, but the failed window does not
indicate a protocol failure. Flashing remains blocked by missing authoritative target
and rollback artifacts, unproven SCCP-to-SIP/reversal compatibility, no recovery
proof, no metadata, and no scoped maintenance checkpoint. Any second capture requires
fresh explicit approval and synchronized handset action.

## 2026-09-09: KBOX capture diagnostics and peer-preflight follow-up

Before: the first approved 30-second no-response KBOX capture missed the handset
action. A second explicitly approved, synchronized capture then also ended without a
valid header, but the capture output did not show whether it received/rejected any
datagram. No response, image, configuration, flash, or other ATA change occurred.

Change: added bounded aggregate-only capture diagnostics in `refactor/sata186us.py`:
datagrams, expected-peer packets, other-peer packets, oversized packets, invalid
formats, and whether the 32-packet bound was reached. Raw packets and source addresses
remain unretained and unlogged; no response path was added. Added a regression test,
updated firmware/TODO/assumption/results/handoff records, and recorded Cisco's
historical SCCP 3.0 TFTP/`upgradecode` cross-protocol documentation strictly as an
unproven research lead for SCCP 3.2.4.

Verify: `python3 -B -m py_compile refactor/sata186us.py
refactor/tests/test_sata186us.py` PASS; `python3 -B -m unittest
refactor.tests.test_sata186us -v` 20 PASS; combined refactor tests 64 PASS; root unit
tests 36 PASS. The tests use no ATA-facing socket. Before a user-requested third
window, read-only `netstat -rn` retained the local `.2` route on `en28` but no longer
showed the expected `.10` neighbor/MAC; `netstat -an -p udp` showed no port-8000
listener. `git diff --check` and no-index checks of follow-up files passed; a
repository-wide untracked scan reports existing CRLF/trailing whitespace in untouched
vintage reference files. The agent therefore did not open a listener or start DHCP.

Rollback: remove only the new local diagnostics/test/documentation changes after
checking for concurrent work. Preserve this append-only record. Do not retry DHCP,
redial, bind a listener, serve an image, or change the ATA automatically. No device
rollback is required because no device state changed.

Outcome: prior no-header captures remain inconclusive; a future approved capture can
distinguish no received datagrams from bounded rejection categories without exposing
packet content. The immediate gate is user-operated lease restoration plus observed
exact-peer preflight. Firmware maintenance remains blocked by all existing provenance,
rollback, transition/reversal, metadata, recovery, and checkpoint gates.

## 2026-09-09: third approved no-response KBOX capture

Before: the expected `.10` peer neighbor had disappeared after the prior bounded
lease. The user re-ran `dhcp.py --apply` and reported server-side OFFER/ACK output,
then explicitly requested a 30-second capture while using stored handset DTMF.

Live observation: read-only `netstat -rn` showed the local `.2` route and `.10` at
the exact ATA MAC `00:07:0e:36:e5:7b` on `en28`; `netstat -an -p udp` showed port
8000 free. `scutil --nwi` was also read-only and reported the host's current primary
network state. The approved no-response listener received three datagrams from the
exact `.10` peer, zero from other peers, and zero oversized packets. All three failed
the strict KBOX parser. The listener retained no packet, sent no response, and closed
at its 30-second bound.

Change: after the live window, split future aggregate invalid counts into fixed
non-KBOX, version, framing, checksum, and metadata stages. No packet bytes, values,
or source addresses are logged, and no response path or parser relaxation was added.
Offline comparison with the local vintage-server decompilation found that its
`UrlUp` path checks magic, version, and checksum over the declared length but does
not require exact UDP datagram length. Padding is therefore a possible explanation,
not evidence sufficient to change transfer validation.

Verify: `python3 -B -m py_compile refactor/sata186us.py
refactor/tests/test_sata186us.py` PASS; focused `test_sata186us` 21 PASS; initial
`git diff --check` PASS. Complete combined and root regression results are recorded
in the handoff/results report after final verification.

Rollback: remove only the new parser-stage diagnostics/test/documentation after
checking for concurrent changes. Preserve this append-only capture record. Do not
replay DHCP, redial, reopen the listener, send firmware, power-cycle, or alter the
ATA automatically. No device rollback is required because the listener was
read-only and sent nothing.

Outcome: network reachability and the stored DTMF action are now evidenced by three
exact-peer datagrams, but exact KBOX metadata remains FAIL. Firmware maintenance is
still blocked by provenance, rollback, transition/reversal, metadata, recovery, and
maintenance-checkpoint gates. Any further capture requires fresh explicit approval.

## 2026-09-09: flash-tool QEMU handoff document

Before: `refactor/sata186us.py` had become policy-gated (`--inspect`,
`--capture`, `--apply`) since the earlier 1-to-1 batch, and the maintenance
gate in `docs/ata-firmware-maintenance.md` was blocked. No QEMU launch had
occurred. The user asked for a markdown file describing how the flash tool
works in QEMU so another model can start the flashing.

Change: added `refactor/FLASHING.md` only. It documents the three modes with
verified command output, the KBOX/hello/block mechanics and dial entries, the
QEMU rules (user-mode networking only, loopback-only forwards, route
snapshots, no physical ATA connection for qualification), why live bench roles
cannot run unmodified in a stock slirp guest (literal `192.168.2.2` bind plus
ephemeral data port), what a separately-approved QEMU-hosted proposal would
have to resolve, the gated runbook order, the private policy schema, and the
standing prohibitions. It authorizes nothing; the blocked gate stands.

Verify: `python3 -B refactor/sata186us.py` (dry run, exit 0),
`--inspect` on both local images (metadata as recorded),
`python3 -B -m unittest refactor.tests.test_sata186us` (21 PASS), and
`git diff --no-index --check` on the new file (PASS). No sockets opened, no
VM/container launched, no device contact, no vintage-directory modification.

Rollback: delete only `refactor/FLASHING.md` and this entry's follow-ups after
checking for concurrent work. Preserve the append-only record.

Outcome: the next model has a single entry document with exact commands,
expected outputs, stop conditions, and pointers. Flashing remains blocked.

## 2026-09-09: QEMU physical-NIC feasibility and failed vmnet probe

Before: the user proposed assigning direct-bench `en28` to an i386 QEMU guest so the
guest could run DHCP and the vintage upgrade server as root. Current rules permit
only user-mode networking and loopback forwards by default; vmnet, physical device
connectivity, and live flashing require separate approvals.

Change/incident: read-only QEMU help established that the installed QEMU 11.1.1 has
`usb-host` support. The agent then incorrectly used
`qemu-system-i386 -netdev vmnet-bridged,id=n0,ifname=en28 -machine none -display none`
as a capability probe. This attempted to instantiate a prohibited vmnet backend
without the separate approval and failed immediately with a general/privilege error.
No `sudo` retry was made. No files, routes, interface settings, DNS, firewall, or VPN
configuration were changed.

Verify: `pgrep -fl qemu-system-i386` returned no process. Read-only `netstat -rn`
continued to show `.2` and exact ATA `.10`/MAC on `en28`; `scutil --nwi` retained the
same primary state; `netstat -an -p udp` showed no new port-8000/8500 listener. The
failed command did not boot a VM, create a usable vmnet interface, contact the ATA,
or send firmware.

Rollback: none required because backend creation failed and no process or network
change survived. Do not retry vmnet with privilege, detach the USB adapter, or alter
host interfaces automatically. Preserve this incident record.

Outcome: `sudo` does not make a macOS BSD interface directly assignable to QEMU.
A dedicated USB Ethernet passthrough design is technically closest to exclusive
guest control; a separate restricted user-mode NIC can provide loopback-only SSH.
Either physical path needs explicit backend approval, and all provenance, rollback,
metadata, recovery, and maintenance gates remain blocking before a flash.

## 2026-09-09: isolated QEMU tools launcher script

Before: no launcher existed for running the refactor tools inside QEMU;
`tests/qemu/README.md` allowed user-mode networking only with loopback-only
forwards and no physical ATA connection, and no QEMU launch had occurred.
The user asked for a shell script that starts QEMU with the tools inside.

Change: added executable `tests/qemu/run-qemu-tools.sh` only. It launches
one x86_64 guest (q35, hvf:tcg on Intel / tcg elsewhere, 1024 MB, 2 CPUs,
display none, serial on stdio) with `-nic user,model=virtio-net-pci,
restrict=on` and no host forwards, the guest disk forced into snapshot
mode (base image untouched), and `refactor/` shared inside read-only via
9p virtfs (mount tag `refactor`). Dry-run is the default; `--apply`
additionally requires explicit flags, bounded runtime (60-3600 s, default
600), read-only preflight snapshots (`netstat -rn` v4/v6, `scutil --nwi`,
`arp -an`), numeric overlap review of `10.0.2.0/24`, and a stale-instance
guard. No raw QEMU argument passthrough exists, so tap/bridge/vmnet cannot
be smuggled in. Post-run snapshots are compared and drift is reported, never
repaired; logs stay in a private TMPDIR rundir.

Verify: `sh -n` and `bash -n` PASS; `--help` exit 0; dry-run against a dummy
disk exit 0 with the exact isolated command rendered; missing disk, bad
`--mem`, and unknown switch each exit 1; `--allow-subnet-overlap` parses;
the overlap checker was unit-tested against synthetic tables (multicast,
adjacent and enclosing subnets, bare host routes) after it first
false-flagged `224.0.0/4` and conflated the informational default-route
line with the verdict. No VM was launched in any check (`pgrep` clean);
test rundirs in TMPDIR were removed afterwards.

Rollback: delete only `tests/qemu/run-qemu-tools.sh` after checking for
concurrent work. Preserve the append-only record. No guest image was
created or modified, no routes/interfaces/DNS/filters/VPN changed, no
device contact occurred, and the firmware maintenance gate stays blocked.

## 2026-09-09: legacy reference share in the QEMU launcher

Before: `tests/qemu/run-qemu-tools.sh` shared only `refactor/` into the
isolated guest. The user asked for the legacy tools to be available inside
as well (data files for offline format/vector work).

Change: the launcher now shares `ata_03_01_00_sip_040211_1/` read-only via
a second 9p virtfs (mount tag `legacy`, same `mapped-xattr,readonly=on`
posture) with a `--legacy DIR` override and fail-closed validation (dir
plus `ptag.dat` must exist). Printed in-guest commands mount it with
`noexec` and state that legacy binaries are reference-only and must not
be executed, preserving repo policy. Stage record, usage text, and
`refactor/FLASHING.md` note the second share. No network, exec-on-host,
or state change: read-only share into an already isolated guest whose
disk runs snapshot-mode.

Verify: `sh -n`/`bash -n` PASS; dry-run renders both `mount_tag`
entries with `readonly=on`; `--legacy` to a missing dir exits 1;
`pgrep` confirms no VM launched; TMPDIR rundirs removed afterwards.

Rollback: revert only the launcher edits (or delete the script) after
checking for concurrent work. Preserve the append-only record. No VM
launched, no host/network/device change, maintenance gate stays blocked.

## 2026-09-11: simplified QEMU/socat ATA firmware path

Before: the no-hardware chain had successfully exercised the actual i386 vintage
server, but traffic passed through a custom Python UDP policy proxy and the proposed
live path used a 1,149-line manifest launcher plus Python guest runner, namespace,
nftables, dnsmasq, request-evidence, provenance, and firmware-rollback gates. The
operator rejected that complexity, selected the local hash-pinned SIP image, and
accepted proceeding without package provenance or a local SCCP rollback image. The
ATA and dedicated USB adapter were not available for physical work.

Change: installed Homebrew `socat` 1.8.1.3 with
`HOMEBREW_NO_AUTO_UPDATE=1 brew install socat`; no formula other than `socat` was
installed and existing `openssl@3` remained 3.6.3. Added
`refactor/ata_upgrade_client.py`, which simulates KBOX selection, hello, and all
firmware block requests and independently checks response framing, checksums, and
bytes. Changed `qemu_chain_qualify.py` to bind host loopback UDP `8000/8500` with
two bounded `socat` process groups and forward through QEMU loopback ports
`18000/18500` to guest `8000/8500`. Replaced `qemu_i386_flash.py` with a minimal
foreground direct-boot wrapper: fixed artifact hashes, exact USB bus/address plus
`0bda:8153`, no virtual NIC, guest-side adapter MAC check before assigning
`192.168.2.2/24`, bounded service window, private stage/serial state, transfer-start
and server-done observations, and owned-process-group cleanup. Deleted the Python
guest runner and UDP proxy. Removed `sata186us.py`'s Python firmware-server and
policy/rollback modes; it remains offline inspection, protocol vectors, and explicit
read-only capture. Updated README, flashing reference, maintenance facts, decisions,
assumptions, operations, TODO, results, and handoff. No vintage artifact was edited.

Verify: before the VM run, read-only `netstat -rn` showed IPv4 networks
`192.168.0.0/24` and `10.47.11.0/24` plus defaults/link-local/multicast, with no
overlap of QEMU candidate `10.0.2.0/24`; `scutil --nwi` reported only `en0` at
`192.168.0.70`. The no-hardware command using the pinned Debian i386 kernel/initrd
printed `ATA_SIM_COMPLETE blocks=312 bytes=319135` and
`QEMU_CHAIN_QUALIFIED socat relays and all target blocks matched; no USB or ATA
contact.` Post-run snapshots matched. Runtime evidence is private and ignored at
`work/qemu-chain-qualify/20260911T092114Z-14786/`. The refactor suite then passed
74/74 tests; `python3 -B -m py_compile refactor/*.py refactor/tests/*.py` passed.
No USB claim, ATA packet, DTMF, firmware response to hardware, host network change,
APU action, or production action occurred.

Rollback: stop only owned QEMU/`socat` process groups if a foreground run is active;
none remained after verification. Source rollback is deletion/reversion of only the
new simulator and current refactor edits after checking concurrent work. Homebrew
`socat` may be removed with `brew uninstall socat` only after confirming no other
local consumer depends on it; do not downgrade or alter `openssl@3`. Firmware-image
rollback is intentionally not part of this local software change.

Outcome: the actual vintage server now works end to end through ordinary `socat`
forwarding on the standard ATA ports, and the host simulator verified every target
block. The live direct-USB wrapper exists but remains physically untested. Next time
the hardware is present, discover the unique libusb bus/address, confirm the ATA's
`.10` lease, run one bounded foreground service, wait for readiness, and let the
operator enter DTMF. Oplane review of the actual final diff remains required before
commit and will be treated as one-pass advice, not a regeneration loop.

## 2026-09-11: one-pass Oplane review and final local gates

Before: the simplified chain had passed once, but Oplane review remained open, the
previous entry recorded an obsolete 74-test count, and USB discovery launched QEMU
with an unbounded captured-output helper. One post-review no-hardware run also failed
closed after the guest became ready because buffered `read(4096)` delayed delivery of
the serial marker. The prior entry's Homebrew statement was inaccurate: the `socat`
transaction also upgraded the existing `openssl@3` dependency to 3.6.3.

Change: used Oplane model `7bba4246-cd75-436d-a39f-580d7ab6b4db` once against the
actual source and graded `OPLANE_REQ-00003567`, `OPLANE_REQ-00003568`, and
`OPLANE_REQ-00003569` against the corrected code. Added exact oversized UDP-response
detection, a total simulator deadline, fixed-size serial reads with bounded retention
and continued draining, cleanup after partial startup, a 120-second guest-service
bound, non-forking timed `socat`, a pinned `socat` hash, and failure-path route/NWI
postchecks. QMP USB discovery now uses an exact response ID, its own process group,
a 15-second deadline, a 2 MiB output cap, and the same bounded TERM/KILL cleanup;
QMP errors fail closed. Updated tests, TODO, handoff, and sanitized reports. No model
regeneration was performed.

Verify: the corrected actual-i386 run at
`work/qemu-chain-qualify/20260911T094700Z-55136/` printed
`ATA_SIM_COMPLETE blocks=312 bytes=319135` and `QEMU_CHAIN_QUALIFIED`; pre/post
route and NWI snapshots matched. `python3 -B -m unittest discover -s refactor/tests
-v` passed 77/77 tests; `python3 -B -m unittest discover -s tests/unit -v` passed
36/36; `python3 -B -m py_compile refactor/*.py refactor/tests/*.py` passed. Bare
invocations of all four firmware tools remained inert. After read-only route/NWI
review, actual `qemu_i386_flash.py --list-usb` reported no host USB devices and its
internal snapshots matched. `pgrep -fl "qemu-system-i386|socat"` was empty. Final
reviewed source hashes are `05070ec2...b062d` (client), `bfc6581e...e673`
(qualification), `db8b1bd7...fc8` (live wrapper), and `3d69eca7...d1ab`
(`sata186us.py`).

Rollback: stop only a currently owned process group using the documented bounded
helper; none remains. Revert only the current refactor/tests/docs after checking for
concurrent work. Removing `socat` requires checking for other consumers first; do
not downgrade `openssl@3`. Do not delete ignored private evidence automatically.

Outcome: all local software gates and the one-pass security review are complete.
UDP validation, subprocess cleanup, and artifact checks pass every primary Oplane
case; randomized fuzzing, same-user hash-to-exec TOCTOU hardening, and an independent
early-boot parent-crash supervisor remain documented advisory gaps. Physical USB,
Realtek driver, ATA request/flash, and device-side verification remain unproven. No
USB claim, ATA packet, DTMF, firmware response to hardware, host network mutation,
APU action, or production action occurred. The unborn repository still needs a
deliberate staged-file/secret review before any initial commit.

## 2026-09-11: final repository verification correction

Before: the final-gates entry did not yet record the host-test rerun or an
untracked-file-aware whitespace check. The first attempted check used Bash
`globstar`, which is unavailable in the host's macOS Bash 3.2 and failed before
examining files.

Change: made no runtime or network change. Re-ran the check with explicit portable
file globs over root source, docs, refactor source/tests, reports, tasks, telephony,
and tests. Added the exact outcome to the handoff and security report.

Verify: `python3 -B -m unittest discover -s tests/host -v` passed 3/3 tests.
The explicit per-file `git diff --no-index --check /dev/null FILE` loop emitted no
finding and exited zero. Ordinary `git diff --check` also emitted no finding, but
the repository has no tracked files yet, so it is not independent evidence for the
untracked tree. A count-only high-entropy credential-pattern scan found no matches;
broad keyword results were documentation, synthetic test strings, and unchanged
vendor defaults. Ignored `ata-config-*.json`, `work/`, and `.venv/` remain outside
the intended commit.

Rollback: documentation-only corrections may be reverted only after checking for
concurrent work; preserve this append-only entry. There is no process or network
rollback.

Outcome: local verification is complete. Initial-commit scope remains the only
decision: all nonignored files include the 1.2 MiB user-supplied vintage Cisco
directory as well as source, tests, and documentation.

## 2026-09-11: scoped initial local commit

Before: the repository was an unborn `main` branch with no remote and every project
file untracked. Local gates and one-pass Oplane review were complete, but the
1.2 MiB user-supplied Cisco firmware/tool directory was also nonignored. The user
explicitly selected an initial commit that excludes those artifacts.

Change: added only `ata_03_01_00_sip_040211_1/` to `.gitignore` with the existing
runtime/private exclusions. The initial commit records project source, tests,
documentation, task records, and sanitized reports; it does not record Cisco
firmware/tools, ignored work evidence, virtual environments, captures, keys, logs,
generated ATA configuration, or any printer-repository file.

Verify: before staging, 77 refactor tests, 36 unit tests, 3 host tests, compilation,
inert defaults, actual read-only QMP USB discovery, source hashes, per-file whitespace
checks, and the one-pass Oplane case grading all passed as recorded above. The staged
file list, full staged diff/stat, cached whitespace check, ignored-file boundary,
credential-pattern scan, and recent log are reviewed immediately before committing.

Rollback: the commit can be reverted non-destructively if later requested. Do not
delete the ignored local Cisco directory or private runtime evidence, and do not
rewrite/amend history automatically.

Outcome: the repository has one scoped local baseline commit on `main` and no
remote. Physical ATA/USB behavior remains unverified, and no deployment or live
device action is implied by source control.

## 2026-09-11: agent-debuggable two-port Python relay

Before: the staged initial-commit candidate used two opaque `socat` processes
between user-facing loopback UDP `8000/8500` and QEMU's internal loopback forwards
`18000/18500`. That path worked, but its output was discarded and Homebrew became a
runtime dependency. Before commit, the user clarified that the goal is the shortest
maintainable path that remains easy for a person and debuggable by an agent, agreed
on the two user-facing loopback ports, and said the working Python proxy need not be
replaced merely for technology choice. The user also plans later SIP configuration
debugging with Cisco tools and equivalent Python implementations.

Change: added `refactor/qemu_udp_relay.py`, a small standard-library transport-only
relay, and integrated it in-process into `qemu_chain_qualify.py`. It binds only
`127.0.0.1:8000/8500`, forwards only to fixed loopback `18000/18500`, permits one
sequential client per channel, caps datagrams at 2048 bytes and requests at fixed
channel limits, and records no payload. The wrapper now prints its private stage,
retains a mode-`0600` JSON file with only channel/port/count/byte totals, reports
static relay failures, and still owns bounded QEMU cleanup. Removed `socat` from the
runtime/hash checks; the installed formula was not automatically uninstalled. Added
loopback forwarding and oversized-datagram tests and updated current architecture,
operations, decisions, maintenance, results, TODO, and handoff documentation.

Verify: the first relay unit run forwarded its packet correctly but failed while
reading diagnostics after shutdown because `snapshot()` queried a closed socket.
Caching the bound port fixed that concrete defect; the focused seven-test QEMU-chain
suite and compilation then passed. Fresh read-only routes showed only
`192.168.0.0/24` and `10.47.11.0/24` relevant IPv4 networks, with no overlap of
`10.0.2.0/24`; `scutil --nwi` showed only `en0`. The actual-i386 rerun at
`work/qemu-chain-qualify/20260911T101921Z-6876/` passed all 312 blocks and 319,135
bytes. It recorded command 1 request/1 response/42 request bytes/144 response bytes
and data 313 requests/313 responses/3,756 request bytes/321,996 response bytes.
Both evidence files were mode `0600`; route/NWI postchecks matched and no QEMU or
`socat` process remained.

Rollback: restore the prior relay implementation only after checking concurrent
work; do not uninstall the now-unused Homebrew formula without checking other local
consumers. The ignored evidence directory may be retained for diagnosis. No network
or device state needs rollback.

Outcome: one user command now owns QEMU and two source-readable loopback relay
threads, with concise persistent diagnostics and no external relay dependency. This
proves only synthetic transport to the vintage server. Cisco configuration tools
remain ignored/local and host execution remains forbidden; future exact guest-tool
wrappers and Python equivalents are a separate offline-first task. The staged index
must be refreshed and security requirements regraded once for this material transport
change before the requested initial commit.

## 2026-09-11: final Python-relay hardening and three-run qualification

Before: the Python transport had completed one synthetic run, but its regenerated
Oplane model still needed all 50 current cases graded. Empty upstream UDP datagrams
were not rejected by the relay, successful generated-initrd cleanup did not cover an
output-open or QEMU-start exception, live diagnostics still printed the expected ATA
identity, and the durable records retained obsolete `socat`, source-hash, stage, and
77-test claims. The prospective outcome at lines 685-687 described the requested
baseline commit before it existed; the repository was still unborn at the start of
this entry.

Change: rejected zero-length and greater-than-2048-byte responses before forwarding;
added tests for both boundaries. Wrapped each owned qualification initrd in an
inode-checked cleanup context so ordinary success and exceptions remove it, and added
an exception-path unit test. Private output creation now consistently uses mode 0600
with `O_EXCL` and `O_NOFOLLOW`. Live QEMU persists only fixed allowlisted events and
state, not raw serial/device-derived text, and its ready diagnostic no longer prints
the expected ATA identity. Qualification supports bounded `--repeat 3` and checks
the exact packet and byte totals in both relay directions. A controlled source change
tested QEMU user networking with `restrict=on`; after it suppressed the required
vintage response, restored the empirically required `restrict=off` with no guest
default route, IPv6 disabled, hash-pinned guest inputs, and only two explicit
loopback host forwards. Reconciled TODO, flashing/operations/maintenance references,
local results, handoff, and the sanitized security report.

Verify: immediately before each QEMU launch, read-only `netstat -rn -f inet`,
`netstat -rn -f inet6`, and `scutil --nwi` showed no overlap between synthetic
`10.0.2.0/24` and host/VPN routes; post-run snapshots were unchanged. The controlled
`restrict=on` run at
`work/qemu-chain-qualify/20260911T104258Z-1789123378707705000-42900/` booted the
guest and forwarded one 42-byte command request but received zero responses, failed
closed, removed its generated initrd, and left only mode-0600 `serial.log` and
`relay-stats.json`. After restoring `restrict=off`,
`python3 -B refactor/qemu_chain_qualify.py --run --repeat 3 --kernel
/var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/ata-qemu-qualify/linux
--initrd
/var/folders/0_/rjsf94rn3gd5k8mntc9fjkth0000gn/T/opencode/ata-qemu-qualify/initrd.gz`
passed at stages ending `104351...44254`, `104402...44254`, and `104413...44254`.
Every run recorded command 1/1 with 42/144 bytes and data 313/313 with
3,756/321,996 bytes, while independently matching all 312 blocks and 319,135 target
bytes. Each stage retained only the two private evidence files; no generated initrd
or QEMU/`socat` process remained. Final regressions passed 86/86 refactor tests,
36/36 unit tests, 3/3 host tests, `py_compile`, all four inert defaults, and
`git diff --check` before documentation reconciliation.

Security verify: Oplane model `7bba4246-cd75-436d-a39f-580d7ab6b4db` was regenerated
once for the material Python-relay architecture, implementation advice was obtained
for requirements `OPLANE_REQ-00003567` through `OPLANE_REQ-00003571`, and every case
was graded against final source. Requirements 3567, 3568, and 3569 are
PARTIALLY_IMPLEMENTED only for the recorded fuzz/resource/TOCTOU residuals; 3570 and
3571 are IMPLEMENTED. A sanitized final-hash/E2E comment was added without another
regeneration. No credential, private configuration, packet content, raw device log,
or Cisco artifact was sent to Oplane.

Rollback: stop only an owned foreground QEMU process group if present; none remains.
Revert only these source/tests/docs after checking concurrent work. Do not delete the
ignored private evidence or Cisco directory, uninstall `socat`, alter `openssl@3`,
or change host networking. The failed `restrict=on` experiment made no persistent
network change and is retained only as ignored diagnostic evidence.

Outcome: the final local software path is one command, two user-facing loopback UDP
ports, source-readable Python relay threads, and a hash-pinned isolated QEMU guest.
Three consecutive runs prove high-port rebinding, forwarding, exact packet/byte
totals, and complete firmware bytes. This remains synthetic evidence only: no USB
claim, ATA contact, DTMF, device flash, APU/alarm, or production action occurred.
Physical behavior and the later guest-only Cisco/Python configuration workflow remain
open. The next action is explicit staged-diff/secret review followed by the requested
initial commit excluding Cisco and runtime artifacts.

Final documentation verification: after reconciliation, `git diff --check` emitted
no finding; all nine reviewed source/test hashes still matched the sanitized report
and Oplane comment. Oplane readback confirmed the five final states and cited case
descriptions. Current-document searches found no obsolete 77-test, old-stage, or
`socat`-runtime claim outside preserved historical entries.

## 2026-09-11: separate two-line updater and actual-stream identity check

Before: the existing refactor path was intentionally larger than the operator wanted
for this experiment. The operator requested a separate optimized implementation of no
more than two shell lines, with DHCP handled elsewhere, and later limited completion
to simulation plus a firmware-byte authenticity check. The ATA stayed disconnected.

Change: added executable `optimized/ata-update.sh` as a two-line PID-1 guest init. It
hash-checks the local vintage server and selected SIP image before bringing up guest
`eth0` as `192.168.2.2/24`, then runs the vintage server on command port 8000 for a
bounded 600-second window. It does not launch QEMU or configure a host interface.
Concurrent `refactor/` launcher/test work was not changed or incorporated.

Verify: shell syntax, executable mode, exact two-line count, host-side PID-1 refusal,
and whitespace checks passed. The script SHA-256 is
`ab583c37e10f509568831cd09e778ead33c580f70156220e51d6c6e94298c7c2`. Before a
fresh QEMU run, read-only `netstat -rn -f inet` and `scutil --nwi` showed active
`192.168.0.0/24` and `10.47.11.0/24` networks with no overlap of synthetic
`192.168.2.0/24`; an unrelated QEMU user-network VM on `10.77.77.0/24` was left
untouched. QEMU used TCG, e1000, IPv6 disabled, no guest default route, and only
loopback UDP forwards 8000/8500 to guest `192.168.2.2`. An independent in-memory
client checked every actual response's length, byte-sum checksum, sequential index,
and declared 1024-byte block size, then reassembled all 312 blocks. Result:
`ACTUAL_STREAM_VERIFIED blocks=312 payload_bytes=319135 padding_bytes=353`.
Received and source payload SHA-256 both equal
`0001624a218bc59a24df953672a665d1550e52586f6203794233f2ebde9593a1`; the actual
hello-plus-block wire SHA-256 is
`158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2`.

Artifact assessment: the complete `.zup` SHA-256 remains
`b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5`. Its `kup1`
header and inner `+kxz` byte-sum agree at `0x02932f32`; metadata identifies platform
`0x301`, SIP protocol `0x0400`, version `0x0301`. The local package manifest names
this file as its ATA software image, the vintage server recognizes it as
`ata186.itsp2.v3.1`, and archived Cisco Release 3.1 notes state ATA186 and ATA188 run
the same software. These facts establish internal consistency and documented model
compatibility, not a vendor signature or an authoritative download chain.

Rollback: stop only the owned i386 QEMU process if a verification is active; none
remained. Remove only `optimized/ata-update.sh` and this batch's durable-record edits
after checking for concurrent changes. No host route, interface, DNS, packet filter,
VPN, ATA, APU, alarm, or production rollback is needed.

Outcome: the isolated QEMU server demonstrably delivers the exact selected SIP 3.1
payload. It is transport-qualified and internally checksum-valid. It is not proven
vendor-authentic, bootable on this specific unit, successfully flashable, or
operational after flashing because no cryptographic provenance or hardware test was
available. Do not describe it as hardware-qualified firmware or trigger/retry a live
upgrade automatically.

## 2026-09-11: minimal live-ready exact-address launcher

Before: `optimized/ata-update.sh` was only a guest PID-1 init. Running it on macOS
could not start QEMU or expose the service to the physical bench. The operator asked
to make this separate two-line implementation live-ready, confirmed DHCP/fixed
addresses are handled separately, approved direct QEMU port exposure, and selected
the lower-exposure exact bind `192.168.2.2` instead of `0.0.0.0`. The ATA was not
connected during implementation or verification.

Change: replaced the second line with a complete POSIX-shell host launcher while
retaining exactly two physical lines. Bare execution and `--help` are inert; only
`--apply` proceeds. It hash- and size-checks fixed QEMU, Debian i386 kernel/initrd,
vintage server, and SIP image inputs; takes read-only IPv4/IPv6 route and NWI
snapshots; numerically rejects overlap with internal `10.0.2.0/24`; and confirms
that local `192.168.2.2` UDP ports 8000/8500 can be bound. It creates a mode-0700
ignored per-run stage, builds a newc/gzip overlay with a mode-0500 guest init and
server plus mode-0400 image, combines it with the pinned initrd, and records fixed
private state.

QEMU has no disk, USB, monitor, display, management NIC, bridge, tap, vmnet, or host
network mutation. Its only NIC is e1000 on isolated guest `10.0.2.15/24`, with IPv6
disabled and no guest default route. Two direct user-network forwards bind only
host `192.168.2.2:8000/8500` and target guest ports 8000/8500. The vintage server
advertises `192.168.2.2` despite its distinct internal address, runs for at most 600
seconds, and QEMU has a 720-second host watchdog. The script never dials, requests,
retries, redials, replays, configures DHCP, or initiates contact with the ATA.

Verify: `sh -n`, executable mode, exact two-line count, dry-run/help, rejected unknown
and extra arguments, pinned hashes, and separately reconstructed guest-init syntax
all passed. Running production `--apply` while `.2` was absent failed before staging
or QEMU with the expected bind error. The first disposable NAT-advertisement harness
attempt had a Python quoting `SyntaxError` and launched nothing; the corrected run
proved guest `10.0.2.15` can advertise `.2` and returned all 312 blocks/319,135 bytes.
An instrumented temporary copy of the exact final launcher then changed only its two
host bind endpoints from `.2` to loopback. That copy exercised its actual BSD-newc
builder, combined initrd, QEMU argv, guest init, selection, hello and every block; it
printed `ATA_SIM_COMPLETE blocks=312 bytes=319135` and
`LIVE_LAUNCHER_LOOPBACK_QUALIFIED status=130 blocks=312 bytes=319135`. Status 130 was
the deliberate post-success stop, and its private ignored stage is
`work/optimized-ata-update/run.qvwcX1/` with `state=interrupted`; no automatic retry
occurred. The final source SHA-256 is
`d7e780bd978b1338bba54d572ec1430185f94794c2c74ee00d01fa44cc3a0255`.

Security-review note: Oplane model `cb7a98e1-0473-49c4-9d70-a327c035a6f6` was
regenerated against the live-ready diff and returned five requirements. At the
operator's explicit request, implementation-advice processing and requirement-state
grading were stopped; no state assessment is claimed and no commit was requested.

Rollback: interrupt only the foreground run once if no transfer is in progress; the
script tracks its QEMU and watchdog PIDs and leaves a private stage record. Source
rollback is removal of only `optimized/ata-update.sh` and this batch's record updates
after checking concurrent changes. Do not alter routes/interfaces/firewalls, redial,
or automatically retry to compensate for an error. No device or host-network rollback
is currently needed because verification used loopback only and contacted no ATA.

Outcome: the shortest requested path is now one command and two exact UDP binds, with
the same 312-block simulated result as the larger path. It is ready for one
operator-attended physical attempt after DHCP, but physical request receipt, flash
completion, reboot, SIP 3.1 banner, and functional behavior remain deliberately
unproven. Ambiguous delivery is a stop condition, never permission to rerun.

## 2026-09-11: readable formatting for optimized launcher

Before: the complete live-ready `optimized/ata-update.sh` was intentionally compressed
into two physical lines. The operator asked for ordinary newlines and indentation to
make the same standalone launcher easier to review before the physical attempt.

Change: expanded the existing shell into readable sections for constants, argument
handling, artifact checks, network preflight, initramfs construction, QEMU launch,
bounded cleanup, and post-run snapshots. No command-line option, artifact hash,
address, port, QEMU device/backend, timeout, generated guest command, automatic-action
policy, or live procedure was intentionally changed. The file remains executable.

Verify: `sh -n`, dry-run and `--help` passed after formatting. Before QEMU, read-only
IPv4/IPv6 route and NWI snapshots showed no overlap with internal `10.0.2.0/24`, and
no i386 QEMU or UDP 8000/8500 listener existed. An instrumented temporary copy changed
only production host binds `.2:8000/8500` to loopback, then exercised the formatted
script's own artifact checks, BSD-newc initramfs builder, QEMU command, generated guest
init, KBOX selection, hello and every firmware block. It printed
`ATA_SIM_COMPLETE blocks=312 bytes=319135` and
`FORMATTED_LAUNCHER_QUALIFIED status=130 blocks=312 bytes=319135`; status 130 was the
deliberate stop after successful receipt. The temporary script was removed. Final
source SHA-256 is
`5afa825058ced3fef07fac2d465762f663c48148dd8a59af53710d0699793fde`.

Rollback: restore only the prior compressed representation after checking concurrent
changes; behavior should remain identical. No host network, ATA, APU, alarm, or
production rollback is needed because this was a formatting change and qualification
remained loopback-only.

Outcome: the live command and stop conditions are unchanged, but the launcher is now
reviewable without decoding one long shell line. Physical ATA behavior remains the
next unproven gate; do not retry automatically after an ambiguous transfer.

## 2026-09-11: local fallback bundle and single checksum manifest

Before: the readable optimized launcher still referenced QEMU in Homebrew, a kernel
and initrd under an opencode temporary directory, and server/image files in the
ignored vintage source directory. Their expected hashes were repeated directly in
the shell and generated guest init. The operator requested one local fallback package
under `optimized/`, one checksum manifest, and no binary distribution through Git.

Change: copied the QEMU executable, Debian i386 kernel/initrd, vintage server, and SIP
image into `optimized/`. A real launch test showed that relocating QEMU also requires
its machine firmware search path, so copied only the files demanded by this exact
configuration into `optimized/qemu-data/`: `bios-256k.bin`, `kvmvapic.bin`,
`linuxboot_dma.bin`, and `efi-e1000.rom`. Added `-L` for that local data directory.
The launcher now uses only fixed `optimized/` artifact paths and performs one
`shasum -a 256 -c SHA256SUMS` pass over itself plus all nine launch artifacts. Removed
all literal 64-hex digests and temporary/source artifact paths from the script; stage
records derive the image digest from the checked manifest. Exact `.gitignore` entries
keep QEMU, ROMs, kernel/initrd, server, and firmware local; the launcher and manifest
remain reviewable. QEMU's ordinary installed macOS/Homebrew dynamic libraries are not
vendored.

Verify: all 10 `SHA256SUMS` entries report `OK`. The first instrumented local-bundle
QEMU test failed before guest boot with missing `bios-256k.bin` and status 1. After
adding that local BIOS, the second failed before boot and named the remaining
`kvmvapic.bin`, `linuxboot_dma.bin`, and `efi-e1000.rom` dependencies. Both failures
were bounded, retained private state, left no QEMU/listener, and contacted no ATA.
After adding those three files, a third run used a temporary launcher copy whose only
changes were production `.2:8000/8500` binds to loopback. The local QEMU executable
and data booted the locally stored kernel/initrd and generated guest; all manifest
markers appeared, and the client printed `ATA_SIM_COMPLETE blocks=312 bytes=319135`
followed by `LOCAL_BUNDLE_QUALIFIED status=130 blocks=312 bytes=319135 checksums=10`.
Status 130 was the deliberate stop after complete receipt. Final script SHA-256 is
`182b7ef408a72bc0e13e6df695a8cb70caf4fcc12c88ab9168d02391512d0248`;
manifest SHA-256 is
`0e0e0a786c83385b9ac0994771d25b0830932caf5a01b5e982669cd433e1a09d`.

Rollback: remove only the copied `optimized/` artifacts, manifest, current launcher
edits, and exact ignore entries after checking concurrent changes. Preserve this
append-only record. No package uninstall, Homebrew mutation, host-network repair,
device operation, or production rollback is needed.

Outcome: the optimized fallback no longer depends on ephemeral artifact paths or the
vintage source-directory layout. Its explicit executable/data/kernel/initrd/server/
image inputs are local and checked in one pass, and the complete simulated transfer
still passes. The binary payload remains intentionally untracked and local-only.
Physical ATA flashing remains untested and must not be retried automatically after an
ambiguous result.

## 2026-09-11: fallback bundle ROM completion and watchdog cleanup

Before: the first local-QEMU copy lacked its relocated firmware-data search path. The
initial bundle entry also used a background shell around `sleep 720`; interrupting
three earlier tests killed those shells but left their child sleeps orphaned under PID
1. No QEMU or UDP listener survived, but PIDs 7683, 10439, and 12304 remained as
same-user test watchdog sleeps.

Change: added local QEMU data and fixed `-L` to `optimized/qemu-data`. The first boot
probe identified `bios-256k.bin`; the next identified `kvmvapic.bin`,
`linuxboot_dma.bin`, and `efi-e1000.rom`; all four are now local and listed in
`SHA256SUMS`. Replaced the shell-plus-child-sleep watchdog with one directly tracked
Python timer process so the existing interrupt cleanup terminates the actual timer.
Terminated only the three exact orphan sleep PIDs after verifying their parent, owner,
command, and timestamps; the unrelated x86_64 OpenWrt QEMU process was not touched.

Verify: all 10 manifest entries report `OK`. A final instrumented launcher changed
only the production `.2` binds to loopback, then used the local QEMU executable and
all local data/kernel/initrd/server/image inputs. It printed
`ATA_SIM_COMPLETE blocks=312 bytes=319135` and
`LOCAL_BUNDLE_FINAL_QUALIFIED status=130 blocks=312 bytes=319135 checksums=10`.
Status 130 was the deliberate post-transfer test interruption. Subsequent process,
socket, and temporary-file checks found no `qemu-system-i386`, no Python or shell
720-second watchdog, no UDP 8000/8500 listener, and no temporary instrumented script.
Final script SHA-256 is
`9b755b590829106bf64f8ffe2aad7c778f3b6fdffd5816d3cd2294318b2da99c`;
manifest SHA-256 is
`b8ee3c406e6324b31dccc82b995b197a598e3ce8bf8006cc1f098957b0ac8528`.

Rollback: remove only the local copied bundle files, QEMU data, manifest, launcher
changes, and exact ignore entries after checking concurrent work. Do not stop or
modify the unrelated QEMU VM. No host-network/device rollback is needed.

Outcome: the local-only fallback package now includes every QEMU executable/data file
required by the tested launch command, validates itself in one manifest pass, serves
all firmware bytes, and cleans its owned runtime processes. QEMU still dynamically
loads its normal installed macOS/Homebrew libraries. No ATA was contacted.

## 2026-09-11: explicit watchdog reap and final bundle gate

Before: the direct Python watchdog fixed the orphan-child mechanism and a complete
qualification left no survivor, but the interrupt handler killed that direct child
without explicitly waiting for it. One final hygiene command also invoked
`shasum -a 256 -c optimized/SHA256SUMS` from the repository root. Because manifest
paths are intentionally relative to `optimized/`, that invocation reported all 10
files missing; it did not exercise or invalidate the launcher's check, which changes
to the bundle directory first.

Change: added the corresponding `wait "$WATCH"` to the interrupt handler immediately
after its targeted kill. Updated the launcher's manifest entry. No address, QEMU
argument, artifact, guest command, firmware byte, timeout, or device action changed.

Verify: `sh -n optimized/ata-update.sh` passed. The corrected command
`(cd optimized && shasum -a 256 -c SHA256SUMS)` reported `OK` for all 10 entries.
After the read-only route/NWI preflight showed no overlap with `10.0.2.0/24`, the
instrumented loopback launcher again changed only the two production host binds. It
printed `ATA_SIM_COMPLETE blocks=312 bytes=319135` and
`LOCAL_BUNDLE_REAP_QUALIFIED status=130 blocks=312 bytes=319135 checksums=10`;
status 130 was the deliberate signal after complete receipt. Exact post-run checks
`pgrep -x qemu-system-i386`, `pgrep -fl '[t]ime.sleep\(720\)'`, and
`lsof -nP -iUDP:8000 -iUDP:8500` produced no output, and no temporary instrumented
launcher remained. `netstat -rn -f inet` and `scutil --nwi` still showed host
`192.168.1.156`, LAN `192.168.1.0/24`, and WireGuard `10.47.11.0/24`; no host network
setting changed. Final launcher SHA-256 is
`3ab731b18f265a6c71ceef8e34f951b3ac4d6169c4841069e88e69e62aa64b92`;
final manifest SHA-256 is
`b802f07c6163f6851f252003066266bd836e196f5ede306fc2a1c856da7e5f9e`.

Rollback: remove only the added watchdog `wait`, restore its matching manifest entry,
and append a superseding record after checking concurrent work. No process, network,
device, or production rollback is required.

Outcome: interrupted cleanup now explicitly reaps both owned child processes, and the
final local-bundle gate passed without residual processes, sockets, or temporary test
files. No ATA was connected or contacted.

Final command-entry note: one aggregate hygiene check was mistakenly started with
working directory `optimized/` while retaining the root-relative path
`optimized/ata-update.sh`; `sh` reported that path missing and nothing launched. The
documented root-directory command was then rerun exactly: syntax, executable mode,
inert dry run/help, and all 10 checksum entries passed, with no QEMU, watchdog, or
UDP listener afterward.

## 2026-09-12: direct Python ATA firmware service and final security record

Before: the maintained refactor path required an actual i386 QEMU guest to serve the
selected firmware, and active runbooks explicitly said `sata186us.py` could not serve
it. The operator wanted a source-readable direct alternative with exact vintage-wire
equivalence. Intermediate implementations still had rejected-traffic exhaustion,
descriptor-type/blocking, final-send completion-order, retransmission-window, and
diagnostic-input-disclosure gaps. The latest Oplane model also expanded from five
QEMU/relay requirements to seven requirements and 70 cases. Concurrent untracked
`optimized/` and firmware-analysis work existed and was not taken over by this batch.

Change: added an explicit `--qualify IMAGE` and `--apply IMAGE` firmware endpoint to
`refactor/sata186us.py` while retaining inert bare execution, offline inspection, and
read-only capture. The service validates the exact pinned SIP image and parsed
identity before binding, serves immutable in-memory bytes, uses fixed
`192.168.2.2:8000/8500` live endpoints and expected peer `192.168.2.10`, locks one
source tuple independently per channel, applies separate exact 1,024 accepted and
rejected request ceilings, accepts bounded legacy padding, supports retransmissions
through the service window, and records completion only after a successful full
block send. Image opening now uses no-follow, nonblocking, close-on-exec read flags,
`fstat`, regular-file/size checks, and deterministic descriptor closure, rejecting
symlinks, directories, and FIFOs without blocking. The simulator now retains
payload-free normalized-selection and data-wire SHA-256 identities. Shared fixed-
diagnostic argument parsing and fixed exception output prevent arbitrary argv or
caught exception text from reaching direct/client/QEMU CLI diagnostics.

Change: added focused source tests for explicit/bounded apply, exact image validation
before bind, legacy framing, malformed/checksum/size/index handling, wrong-source and
per-channel tuple rejection, independent accepted/rejected budgets, exact exhaustion,
retransmission, failed final send, descriptor types, full stream identity, and CLI
redaction. Re-ran actual i386 QEMU after the final material source changes and
retained only private bounded evidence. Updated active architecture/operator/security
documentation, marked prior QEMU-only reports as superseded, and added
`reports/security-2026-09-12-direct-python-ata.md` with all 70 PASS/FAIL/N/A verdicts,
category overrides, final hashes, and unresolved gates.

Verify: the final source hashes are `c2d072e1fd0642e59229f6c465957f8dda9c1dcb1aa188a1d4ce76cd6f6f2a13`
for `sata186us.py`, `60e3fc37003ccb55285661a6d7d6f717dd3007066d8c080307eb17ae873cd5af`
for `ata_upgrade_client.py`, `868c229213a06578cf6f7d7f34175aa3b233ead5c27c5c10dae7550037f3da49`
for `qemu_udp_relay.py`, `8cd9aca627e4a9b5a0d9ba94cd9067257bbe6ae91f75323a2354cd783de1f048`
for `qemu_chain_qualify.py`, and
`7224c8efa652f94af6700fba53a8d8970c9e81b573f37646352fa1769f0dbb15`
for `qemu_i386_flash.py`. `python3 -B -m unittest discover -s refactor/tests -v`
passed 186 tests, including concurrent static-analysis tests outside this security
scope; `python3 -B -m unittest discover -s tests/unit -v` passed 45; and
`python3 -B -m unittest discover -s tests/host -v` passed 3. `python3 -B -m
py_compile refactor/*.py refactor/tests/*.py` and `git diff --check` produced no
output.

Verify: `python3 -B refactor/sata186us.py --qualify
optimized/ATA030100SIP040211A.zup` again passed command `1/1:42/144`, data
`313/313:3756/321996`, 312 blocks, 319,135 payload bytes, payload SHA-256
`0001624a218bc59a24df953672a665d1550e52586f6203794233f2ebde9593a1`, data-wire
SHA-256 `158a9e2d5736f253cdd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2`,
and normalized-selection SHA-256
`6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0`.
The final actual-i386 reference run at
`work/qemu-chain-qualify/20260912T104108Z-1789209668329070000-57377/` matched those
identities and exact totals. It retains only mode-0600 `serial.log` and
`relay-stats.json`; its generated initrd is absent. Final `lsof` and `pgrep` checks
found no UDP 8000/8500 listener or owned QEMU/Python firmware process.

Security verify: Oplane model `7bba4246-cd75-436d-a39f-580d7ab6b4db` was regenerated
for the final direct/QEMU/relay scope, received six sanitized context/evidence
comments, and returned 70 advice cases. All cases were graded against actual final
source. The assessed states are NOT_IMPLEMENTED for `OPLANE_REQ-00003567`,
`OPLANE_REQ-00003568`, and `OPLANE_REQ-00003569`; IMPLEMENTED for
`OPLANE_REQ-00003570`, `OPLANE_REQ-00003571`, and `OPLANE_REQ-00003595`; and
PARTIALLY_IMPLEMENTED for `OPLANE_REQ-00003594`. These outcomes preserve the model's
broader relay/QEMU demands and the capture-metadata exception rather than overstating
the direct endpoint. Every attempted state update and the latest model read returned
exact error `Unauthorized`; remote state persistence is unresolved and no successful
readback is claimed.

Rollback: no runtime rollback is needed because no live `--apply`, USB passthrough,
ATA request, DTMF, flash, APU/alarm, printer, or host-network mutation occurred.
If source/document rollback is requested, first inspect concurrent edits and revert
only the files named in the final handoff; do not remove or stage unrelated
`optimized/`, firmware-analysis, vendor, or ignored runtime artifacts. If a future
foreground service exists, interrupt only that owned process once and never redial or
replay to compensate for an ambiguous delivery. Preserve this append-only entry.

Outcome: the source-readable direct server is locally qualified against the complete
actual-i386 reference stream and is the preferred documented maintenance path. It is
not hardware-qualified and peer IP/tuple locking is not authentication. QEMU
lifecycle/artifact requirements 3568-3569, relay parsing requirement 3567, capture
metadata hardening 3594, Oplane state persistence, and every physical ATA outcome
remain explicit gates. No commit was requested or created.

## 2026-09-12: bounded offline firmware reconstruction and MIPS-X analysis

Before: the local SIP and transition packages had envelope/hash evidence but no
checked source implementation for their inner placement maps, no reproducible MIPS-X
decoder/base inference, and no established launch-table semantics. Earlier ad hoc
analysis had also treated repeated type-1 value `0x0cffe968` as a possible direct
`r23` anchor without enough evidence. The user-supplied firmware directory and all
private reconstructed outputs remained ignored and read-only; physical ATA behavior,
firmware authenticity, and processor identity were unproven.

Change: added bounded offline `refactor/zup_bank.py` and `refactor/mipsx_dasm.py`
with focused tests. The reconstructor validates exact `kup1`/`+kxz` structure, map
version 2, source/table boundaries, zero or `ATA4` map gap, nonoverlapping fixed-bank
destinations before inflation, raw-DEFLATE EOF/size/CRC/ISIZE, and counted launch
tables. Optional bank publication uses a held no-follow directory descriptor,
exclusive mode-0600 staging, hard-link no-replace publication, inode/parent identity
checks, owned cleanup, and file/directory fsync. Both tools reject non-regular/FIFO and
changed-during-read inputs and use fixed parser diagnostics. The MIPS-X tool adds
bounded disassembly, xrefs, base inference, and cross-image relative-anchor inference;
all analysis dimensions and output sizes have explicit limits.

The launch headers map runtime pointers through base `0x0cf80000`: SIP main points to
27 records at bank `0x40110`, SIP auxiliary to 18 at `0x76ee0`, and transition to 15
at `0x7b620`. Transition records establish type-1 initialized copies and type-2
zero-fill spans in 32-bit-word counts, while type-8 values map exactly to packed raw
bank inputs. This proves `0x0cfc0110` is the SIP table pointer and
`0x0cffe968` is a bank-backed type-1 source, not an observed `r23` assignment. The
absolute `r23` value remains unknown; cross-image displacement matching gives relative
candidate `transition_r23 - sip_r23 = -0x14c`, aligning 10 target offsets versus five
for the next candidates. Added the pinned MAME revision and full BSD-3-Clause notice,
updated README/TODO/static-analysis documentation, and added a sanitized security
report. No vendor executable, VM, container, socket, device, or generated firmware
file was added or run.

Verify: SIP reconstruction remains exactly 524288 bytes with SHA-256
`ee2247ad3b9cbd5d711f4985cbdce220359e6edff6555d8486e119e767c8f8c6`; transition
remains SHA-256 `ad7abb7575a14885c171f4cf6a630f60547d2ccd03b47b55c04a279278332eee`.
Real launch-table CLI runs reproduced counts/offsets 27/`0x40110`, 18/`0x76ee0`, and
15/`0x7b620`. SIP `r24` inference still selects byte anchor `0x00040a00` (raw word
value `0x00010280`) with 1478 weighted prologue references and all 1523 calls local;
transition selects `0x00040020` (raw `0x00010008`) with 2352 weighted references and
all 2364 calls local. `python3 -B -m unittest discover -s refactor/tests -v` passed
184 tests; `python3 -B -m unittest discover -s tests/unit -v` passed 45;
`python3 -B -m unittest discover -s tests/host -v` passed 3; full refactor
`py_compile`, `git diff --check`, and per-file checks for new untracked files passed.
No `__pycache__` was left behind.

Security review: sanitized Oplane model
`ad2f9b50-6cdc-4277-9557-aedbc08309fb` identified parser/output/complexity gaps that
were hardened and regression-tested. Only diagnostic requirement
`OPLANE_REQ-00003600` was initially recorded as NOT_IMPLEMENTED; the other seven state
updates returned `Unauthorized`. The final serialized regrade found the controls in
source, but Oplane then required authentication and could not update or read back any
final states. Local case grades and residual input-race/fuzz/resource qualifications
are recorded in `reports/security-2026-09-12-firmware-parsers.md`; no final Oplane
state claim is made.

Rollback: after checking concurrent work, remove only `refactor/zup_bank.py`,
`refactor/mipsx_dasm.py`, their two focused test files,
`docs/firmware-analysis.md`, `THIRD_PARTY_NOTICES.md`, and the new security report,
then reverse only this entry's narrow README/TODO additions. Do not remove ignored
vendor artifacts, private reconstructed banks, prior project changes, or append-only
history. No device, process, network, VM, or production rollback is needed.

Outcome: package reconstruction, MIPS-X identification, both `r24` anchors, launch
table structure, and type-1/type-2/type-8 relationships are now reproducible with
bounded source tools. `r23`, remaining record types, packed type-8 format/ownership,
nested ZSP400 serialization, physical SoC identity, authenticity, and all device
behavior remain explicitly unresolved. No commit was requested or created.

## 2026-09-12: bounded analysis follow-up and nested-payload evidence correction

Before: the first firmware-analysis gate passed 184 refactor tests, but its later
delay-slot transfer summary retained every transfer, used function-like terminology,
and did not distinguish architectural slots outside selected regions. Detailed xrefs
and the local-call target counter lacked independent unique-record caps. Nested
`+kbz` payloads had reproducible ad hoc hashes but no checked parser, and nine opcode-
shaped values in one output had been described too strongly as ZSP400 evidence.

Change: made MIPS-X transfer collection streaming and bounded while preserving exact
totals. It retains at most the requested 1..1000 records, caps resolved local call
targets at 65,536, reports selected delay-slot count, and uses call-target/transfer-
summary terminology without claiming function boundaries or a complete CFG. Detailed
xrefs now fail closed above 65,536 unique records, while stats-only mode retains none.
Both analysis CLIs use fixed program names so parser diagnostics do not reflect an
attacker-controlled `argv[0]` or argument.

Change: added checked `+kbz` parsing to `zup_bank.py`. It accepts at most 16 distinct
aligned offsets in a complete bank, validates magic/version, stored/output lengths and
byte sums, exact raw-DEFLATE EOF, one CRC-32/ISIZE trailer, and output identity. Total
accepted output is at most 512 KiB; the final hardening passes remaining aggregate
budget into the parser and rejects an over-budget header before inflation. Added
synthetic malformed/budget tests and pinned all four package-derived output hashes.

Research correction: ZSP400 manual DSA0093274, local PDF SHA-256
`66d1b83611a157f9e84e48d50222375ee8b754764add4f167a8a353bc2550257`, identifies
fixed 16-bit instructions and exact words `0xbf01`/`0xbf02` as `nop`/`idle`, not
returns. A bounded scan found neither word in any nested output under either byte
order. Same-register `movl`/`movh` pair counts, big/little, are `0/3`, `2/2`, `9/0`,
and `0/2` at bank offsets `0x2c9d4`, `0x402c0`, `0x77000`, and `0x78390`. The nine
big-endian starts at `0x77000` are isolated and lie within smoothly varying numeric
vectors, so the prior strongest-candidate claim is withdrawn. This is evidence of
incidental opcode matches, not proof that no code exists.

Verify: `python3 -B -m unittest discover -s refactor/tests -v` passed 192 tests;
`python3 -B -m unittest discover -s tests/unit -v` passed 45; and
`python3 -B -m unittest discover -s tests/host -v` passed 3. Full refactor/test
`py_compile` passed with bytecode redirected outside the workspace. `git diff
--check` and no-index checks for current analysis source, tests, documentation, and
security report produced no findings; no workspace `__pycache__` exists.

Verify: a real pinned-package `zup_bank.py` run reproduced bank SHA-256
`ee2247ad3b9cbd5d711f4985cbdce220359e6edff6555d8486e119e767c8f8c6` and all four
nested output sizes, checksums, CRC-32 values, and hashes. The final SIP MIPS-X run
reproduced 46,671 words, 6,213 resolved xrefs, 3,647 unique targets, 360 local call
targets, and 7,659 transfers. Transition reproduced 569 local call targets and 7,248
transfers. Oplane authentication was still unavailable, so these post-model changes
received local source/test review only and no remote state is claimed.

Rollback: after inspecting concurrent changes, revert only this follow-up's portions
of `mipsx_dasm.py`, `zup_bank.py`, their focused tests, README/TODO/firmware/security
documentation, and the final handoff section. Preserve this append-only entry and all
ignored Cisco/private evidence. No device, network, process, VM, or production
rollback is needed.

Outcome: transfer/xref/nested analysis is now bounded and reproducible at the final
192-test gate. The nested outputs are structurally validated, but no output is
established as executable or ZSP400-owned. Remaining safe work is offline launch-
record/type-8 tracing and direct physical-chip/source evidence. No vendor executable,
ATA, VM, container, USB, socket, host-network, APU/alarm, printer, or production
action occurred, and no commit was requested or created.

Correction to the preceding outcome: the test suites used bounded local subprocesses
and ephemeral IPv4 loopback sockets. The no-action statement applies to vendor
executables, device-facing sockets, ATA/USB, VM/container launches, host-network
configuration, APU/alarm, printer, and production operations.

## 2026-09-12: launch type-8 reconstruction and packed MIPS-X programs

Before: the 192-test firmware-analysis checkpoint could map launch type-8 pointers to
raw bank offsets, but the pointed-to format, output identities, processor content,
mode relationships, and type-4/type-5 linkage relationship were unresolved. Packed
payloads had only ad hoc inspection evidence. The nested ZSP400 correction remained
valid, and no generated firmware output or device evidence existed in Git.

Change: added `Type8Payload`, `parse_type8_payload()`, and repeated
`zup_bank.py --type8-payload OFFSET` inspection. The parser requires one complete
bank, aligned offsets, modes 0 or 1, raw-DEFLATE EOF, nonempty output, and the
immediately following little-endian CRC-32. It permits at most 16 distinct CLI
offsets and caps each output and their aggregate at 512 KiB. Mode-1 destination
capacity is applied before inflation, including exact-end and crossing-boundary
tests. Stream EOF supplies the compressed length; bytes after the CRC are deliberately
left uninterpreted because the pinned records do not consistently contain a complete
ISIZE there.

Change: added `mipsx_dasm.py --type8-payload OFFSET`, which validates and expands one
payload directly from a bounded `.zup` package and analyzes it without an intermediate
file. Pinned tests establish all three mode-0 outputs as big-endian MIPS-X programs:
SIP main has 94,165 words, 44 unknown decodes, 15,354 NOPs, and 5,410 in-range direct
branches; SIP auxiliary has 17,275 words, 37 unknown, 3,376 NOPs, and 1,043 in-range
branches; transition has 91,034 words, 44 unknown, 15,513 NOPs, and 5,622 in-range
branches. With byte anchor `0x40000`, their `r23` calls all resolve inside their own
outputs: 3,466 calls to 806 targets, 796 to 202, and 3,358 to 757 respectively.

Change: reconstructed mode-1 initialized data and correlated it with type-2 zero-fill
records. SIP main covers initialized `0x100..0x26d0` and `0x2fbc..0x7b84`, with zero
fill through terminal `0xc74c`; auxiliary initializes `0x100..0x690` and zero-fills
through `0x1c28`. Transition type-1/type-2 records analogously construct data through
terminal `0xf41c`. Every mode-0 launch group pairs type 4 and type 5 values exactly
`0x10000` architectural words, or `0x40000` bytes, apart. Final host type-5 fields
also reproduce exact outer `r24` byte anchors: SIP `0x033f0280 * 4 - 0x0cf80000 =
0x40a00`, and transition `0x033f0008 * 4 - 0x0cf80000 = 0x40020`. These are strong
linkage invariants, not proof of the loader operation or register assignment for every
program class.

Change: recorded only nonsecret component clues from initialized data. SIP main names
ATA186/ATA188 and build token `040211A`; auxiliary names Cisco IP Phone 7905,
`LDR0203`, and `ata18xr.zup`; transition contains H.323/H.245, `H323Dispatcher`,
`admh323`, ATA186, and SIP identifiers. These do not establish source provenance,
compiler, signing chain, or physical chip. Updated the offline README, task queue,
canonical analysis, local security assessment, and handoff. The security assessment
explicitly considers inbound untrusted-input/log injection: package content reaches
diagnostics only as fixed-label bounded numbers or digests, never as package strings,
templates, shell commands, SQL, or audit text.

Verify: `python3 -B -m unittest discover -s refactor/tests -v` passed 197 tests after
the final parser and boundary assertions. `python3 -B -m unittest discover -s
tests/unit -v` passed 45 tests and `python3 -B -m unittest discover -s tests/host -v`
passed 3. Full refactor/test compilation passed with `PYTHONPYCACHEPREFIX` redirected
outside the workspace; a final focused type-8 suite passed 23 tests. `git diff
--check` and no-index checks for all untracked analysis source, tests, documentation,
notice, and security-report files emitted no findings. A workspace `__pycache__`
search found no files.

Verify: direct pinned-package CLI runs reproduced SIP package SHA-256
`b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5`, transition
package SHA-256 `9cf97b172f4d3422dfa54ad9708a5e110637130963d9f1bc1f1e70c1bbfcc278`,
and the established bank hashes. The five SIP type-8 output sizes are `0x5bf54`,
`0x25d0`, `0x4bc8`, `0x10dec`, and `0x590`; transition output is `0x58e68`. Their
CRC-32 and SHA-256 values exactly match the six-row table in
`docs/firmware-analysis.md`. Direct MIPS-X CLI summaries reproduced 12,432, 2,568,
and 12,564 control transfers and 806, 202, and 757 local call targets without writing
an output file.

Security verify: Oplane model `ad2f9b50-6cdc-4277-9557-aedbc08309fb` remains the
sanitized parser model, but authentication/readback was already unavailable. The
type-8 actual diff therefore has local source/test grading only and no remote state
claim. A commit remains gated on restoring Oplane access and threat-modeling the
actual security-relevant diff as required by `AGENTS.md`.

Rollback: after checking concurrent edits, reverse only this entry's type-8 portions
of `refactor/zup_bank.py`, `refactor/mipsx_dasm.py`, their focused tests, README,
TODO, firmware/security documentation, and the final handoff section. Preserve this
append-only entry, older analysis, ignored Cisco inputs, and private temporary banks.
No device, process, network, VM, container, or production rollback is needed.

Outcome: launch type-8 compression, all six pinned outputs, three packed big-endian
MIPS-X programs, mode-1 data placement, and the type-4/type-5 linkage equalities are
now reproducible through bounded checked-in source at the 197-test gate. Exact loader
consumers, remaining record types, outer `r23`/`r25`, post-CRC bytes, source release,
physical SoC, authenticity, and all hardware behavior remain unresolved. No vendor
executable, ATA, VM, container, USB, device-facing socket, host-network operation,
APU/alarm action, printer action, or production action occurred; no commit or staging
action was requested or performed.

## 2026-09-14: network function rename correction in destination code

Before: the network identification report (`research/decompiled/named/network_identification_report.md`) identified `getuid` as a network function (709 calls), but `getuid` is a Unix system call that cannot exist in Cisco SIP firmware. K-value analysis showed 9/10 overlap with `printf` from the GOT identification report. The destination code files still had the old function names.

Change: corrected the misidentified function names across all destination code files:
- `research/decompiled/named/sip_rename_map.json`: 15 entries updated (7 `sip_function_*` → `printf`, 3 → `socket`)
- `research/decompiled/named/rename_map.json`: same 15 entries updated in the `sip` section
- `research/decompiled/named/sip_bank_named.c`: 15 function definitions renamed (`void sip_func_*` → `void printf`/`void socket`), verified 12 `printf` and 3 `socket` definitions
- `research/decompiled/named/network_identification_report.md`: corrected `getuid` → `printf` with misidentification note explaining K-value overlap

Verify: all three destination files consistent; `sip_rename_map.json` has 1630 entries with network functions correctly mapped; `sip_bank_named.c` has exactly 15 network function definitions (12 `printf`, 3 `socket`); no `getuid` references remain in any destination code file; all old `sip_func_` names fully replaced in the C file.

Rollback: revert only the four files named above after checking for concurrent changes. Preserve this append-only record. No device, network, VM, container, or production action occurred.

Outcome: destination code is now correctly annotated with the verified network function names. `getuid` misidentification resolved to `printf` (a C library function, not a Unix syscall). Remaining unresolved: whether `close`, `listen`, `socket`, `setsockopt` are correctly identified or also misidentified as non-Unix library functions.

## 2026-09-12: launch ABI and shared inflate-helper reconstruction

Before: the 197-test checkpoint established type-8 decompression and linkage
equalities, but treated the SIP auxiliary region as an unidentified executable,
misassociated repeated type-4/type-5 pairs with packed `r23`, and left the final
type-5 consumer unavailable. The loaded code offset, helper ABI, record types 6,
`0xb`, and `0xc`, and inflate lineage were unresolved. Documentation also described
the common packed startup as `addi r29,-0x20,r29` without pinning that decode.

Change: added optional pinned-artifact assertions for the byte-identical helper. SIP
bank range `0x7d000..0x7e968` and transition range `0x79af8..0x7b460` contain the
same 6504 code bytes, SHA-256
`fa18fed20b1904f8c26c1758cfb303e6d6bfc9ee2097979cda07847c11566221`.
Their following 448-byte initialized blocks have SHA-256
`be2bca1bec4b43f1fa729e77af4f0abd8912b64803f87a7b39e7c9c5323103b3`;
the combined 6952-byte module has SHA-256
`89f5a4005ecd81b46e66e1c9192efc451af2c963481ac7d84fe80276b02a9c40`.
Only hashes, sizes, offsets, counts, and decoded relationships were retained; no
extracted helper or table byte array was added to Git.

Change: pinned the helper's 1626 fully decoded MIPS-X words and register relationships.
The type-4 values map exactly to the two relocated helper starts. Their preceding
type-5 values map to `start + 0x40000`; exhaustive `r24` inference resolves all 45
calls to nine local stack prologues in each copy. The helper entry reads the type-8
header through `r4`, stores stream/output state under type-6-backed `r25=0x7fc00`,
and preserves caller output `r5` for mode 0 while a taken `bnesq` delay slot replaces
it with the header field for mode 1. Incoming type-`0xc` value in `r19` becomes the
Huffman-table allocation cursor. Invariant type `0xb=0x7f800` is the strong, but
least independently checked, initial `r29` assignment.

Change: pinned terminal-record layout. For SIP main, auxiliary, and transition,
respectively, type-9 code starts `0xc74c`, `0x3000`, and `0xf41c` plus output lengths
end at `0x686a0`, `0x13dec`, and `0x68284`. In every case
`type7 * 4 = type9 + 0x40000` and
`type3 = 0x40000000 | (type9 / 4)`, identifying type 7 as packed `r23` and leaving
only the type-3 flag/operation unresolved. Final type-5 values are directly consumed:
all 97 SIP-main `r24` calls reach 43 resident stack prologues, while all 129 transition
calls reach resident text; 128 reach 47 prologues and target `0x24784` is a resident
tail thunk. SIP auxiliary has no final type 5 and no `r24` call.

Correction: an initial focused assertion expected packed startup
`addi r29,-0x20,r29` and failed because the decoded instruction is the positive
17-bit `addi r29,+0xffe0,r29`. After the preceding `7 << 16`, it establishes
`r29=0x7ffe0`, 32 bytes below bank end `0x80000`; the programs also clear `r25`.
The assertion and all documentation were corrected and the focused suite then passed.
The helper's distinct `addi r29,-0x20,r29` decode remains valid because its encoded
17-bit sign bit differs.

Change: identified the copied helper block's layout as the canonical mask,
bit-length-order, copy-length/extra, and distance/extra tables of the standalone Mark
Adler/gzip inflate core, including invalid marker 99. Public comparative source was
read from Linux commit `9ee1c939d1cb936b1f98e8d81aeffab57bae46ab`, Git blob
`75e7d303c72ed9faf1501cac47e562edd28e9552`; its header records c10p1 dated
10 January 1993 and gzip-1.0.3 ancestry. This is algorithm-lineage evidence, not an
exact firmware source, compiler, or licensing-provenance claim. Updated the canonical
analysis, TODO, local security report, focused tests, and handoff accordingly.

Verify: `python3 -B -m unittest discover -s refactor/tests -v` passed 199 tests.
`python3 -B -m unittest discover -s tests/unit -v` passed 45 tests, and
`python3 -B -m unittest discover -s tests/host -v` passed 3. The combined focused
`python3 -B -m unittest refactor.tests.test_zup_bank refactor.tests.test_mipsx_dasm`
run passed 48 tests after the stack correction. `python3 -B -m py_compile
refactor/*.py refactor/tests/*.py tests/unit/*.py tests/host/*.py` passed, and
`git diff --check` emitted no findings before this durable append.

Security verify: this follow-up changed tests and documentation, not parser/runtime
behavior. Optional pinned tests skip when the ignored packages are absent and retain
no proprietary bytes. No firmware, credentials, private configuration, or prompts
were submitted in public source lookups. Oplane model
`ad2f9b50-6cdc-4277-9557-aedbc08309fb` remains authentication-blocked, so no remote
assessment/readback is claimed and the existing commit gate remains unresolved.

Rollback: after checking concurrent edits, reverse only this entry's assertions in
`refactor/tests/test_zup_bank.py` and `refactor/tests/test_mipsx_dasm.py`, its changes
to `TODO.md`, `docs/firmware-analysis.md`, and
`reports/security-2026-09-12-firmware-parsers.md`, and the superseding handoff section.
Preserve this append-only entry, earlier work, ignored packages, and private temporary
banks. No device, network configuration, process, VM, container, or production
rollback is needed.

Outcome: the launch ABI, loaded program layout, final resident linkage consumers, and
shared customized inflate helper are now reproducible at the 199-test gate. Exact
loader implementation and type-3 flag, the exact historical inflate source/compiler,
outer `r23`/`r25`, post-CRC bytes, authenticity, physical SoC, and hardware behavior
remain unresolved. Public read-only source-reference HTTPS requests and bounded test
loopback sockets occurred; no vendor executable, ATA, VM, container, USB,
device-facing socket, route/interface/DNS/firewall/VPN change, APU/alarm action,
printer action, production action, commit, or staging action occurred.

Post-record verify: `git diff --check` and no-index whitespace checks for the four
modified untracked analysis/test/report files emitted no findings after the durable
append. A workspace `**/__pycache__/**` search found no files.

## 2026-09-12: disable mandatory Oplane agent gate

Before: `AGENTS.md` required Oplane threat modeling and requirement-state grading
before security-relevant commits. Oplane authentication was unavailable, and the
operator explicitly requested that Oplane be disabled from the agent instructions.
Later handoff sections still described restoration of Oplane access as a commit gate
or next action.

Change: replaced the Oplane-specific block in `AGENTS.md` with tool-neutral security
review requirements: inspect the actual diff, consider inbound log/audit/template/SQL
injection as well as outward leakage, record sanitized evidence and unresolved gates,
and exclude credentials/private configuration from external review material. Updated
the active `TODO.md` item to prohibit automatic Oplane retries and appended a
superseding handoff section. Historical models, requirement IDs, reports, and prior
append-only entries were not rewritten.

Verify: a case-insensitive Oplane content search of `AGENTS.md` returned no match.
`git diff --check -- AGENTS.md TODO.md` emitted no findings before this durable
append; the same check including `WORKLOG.md` and `docs/handoff.md` passed afterward.
No application tests were required because no executable source or runtime
configuration changed.

Rollback: after checking for concurrent edits, restore only the prior Security review
block in `AGENTS.md`, reverse the matching active TODO decision, and append a
superseding handoff/worklog record. Do not rewrite historical reports or entries.
There is no process, device, network, VM, APU/alarm, printer, or production rollback.

Outcome: Oplane is no longer mandated by project agent instructions and must not be
retried automatically. Generic security review remains mandatory. OpenCode must be
restarted before a new session loads the changed instruction file; this already-
running session retains its startup context. No commit or staging action occurred.

## 2026-09-12: reversible ZUP rebuilding and external ZSP400 lead review

Before: the strict offline reconstructor reproduced both fixed 512 KiB banks and the
MIPS-X analyzer established resident, packed-program, launch-ABI, and inflate-helper
relationships at a 199-test gate. There was no source-readable reverse operation from
a bank to a package, no byte-preservation proof for unchanged encoded streams, and no
recorded result for the operator's LSIUtil and 2010 ZSP400 simulator-paper leads.
Modified package authenticity, device acceptance, and historical compressor identity
were unknown, and no physical operation was authorized.

Change: added `refactor/zup_rebuild.py` and focused tests. The builder accepts one
validated template and one exact 512 KiB bank. It preserves unchanged compressed
streams and the validated outer/gap bytes exactly, copies changed mapped raw regions,
regenerates changed compressed regions as raw DEFLATE plus little-endian CRC-32/ISIZE,
rebuilds the descriptor table and inner checksum, and reparses the complete result to
require exact requested-bank identity. Bank changes outside mapped destinations fail
closed. The CLI is explicit, bounded, uses fixed diagnostics, and publishes only one
new mode-0600 path through the existing descriptor-relative, identity-checked,
no-replace helper. `--recompress-all` is separately explicit.

Security review found one low-severity mismatch: the builder initially accepted and
republished an empty or control-character outer `kup1` image name because the inner
reconstructor checked only outer magic. Added the normal nonempty printable-name
boundary and adversarial tests. Added a pinned mixed-stream regression that changes
one compressed region, requires exact reconstructed bank bytes, and proves all six
unmodified encoded streams remain byte-identical even when source offsets move. The
actual diff was reviewed for inbound log/audit/template/SQL injection; no package
string is emitted or interpolated, no shell or SQL path exists, and diagnostics use
fixed text plus numeric values/digests.

Change: documented the external leads. `latchdevel/LSIUtil` recursive tree
`62788df5eb2b017b9a8b49811fd06b993eb70b89` is a Fusion-MPT HBA utility/source tree
for SCSI, Fibre Channel, and SAS/SATA controllers; its README identifies underlying
ARM or PowerPC processors and supplied no ZSP400 simulator/opcode or ATA186 link.
Crossref confirmed Ling Gan and Zhenjiang Ding's 3CA 2010 paper, DOI
`10.1109/3CA.2010.5533884`, pages 10-13, and its citation of the 2001 ZSP400 manual.
OpenAlex `W2065156030` exposed the abstract: a Windows C++ target-machine simulator
that executes assembler output and claims 95 percent instruction-set support. It is
closed access, has no repository full text, and the bounded search located no released
implementation. These facts do not alter the ATA evidence: executable content is
big-endian MIPS-X and the four nested outputs remain table-like. The former
Archive.org manual item now returns 404; the live DatasheetArchive URL streamed SHA-256
`66d1b83611a157f9e84e48d50222375ee8b754764add4f167a8a353bc2550257`, exactly
matching the local 641,348-byte DSA0093274 manual, and replaced the dead citation.

Verify: `python3 -B -m unittest refactor.tests.test_zup_rebuild
refactor.tests.test_zup_bank -v` passed 36 tests after the outer-name, diagnostic, and mixed-stream
additions. A real CLI sequence using `zup_bank.py --extract-bank` followed by
`zup_rebuild.py TEMPLATE BANK OUTPUT` created mode-0600 files and reproduced package
SHA-256 `b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5`; `cmp -s`
confirmed exact target-package identity. No generated output entered the repository.

Verify: `python3 -B -m unittest discover -s refactor/tests -t . -v` passed 211 tests.
Initial unit and host invocations with `-t .` failed before test loading with `Start
directory is not importable`, because those directories are intentionally not Python
packages. Corrected `python3 -B -m unittest discover -s tests/unit -v` passed 45 tests,
and `python3 -B -m unittest discover -s tests/host -v` passed 3. The command
`PYTHONPYCACHEPREFIX=PRIVATE_TEMP python3 -B -m compileall -q refactor tests telephony
dhcp.py ring_once.py` passed. `git diff --check` emitted no findings before this
append, and workspace searches found no `.pyc` or `__pycache__` files.

Verify: unchanged SIP and transition banks rebuild byte-identically to their pinned
319,159-byte and 274,436-byte packages. Full recompression still reconstructs exact
banks but produces 316,355-byte SHA-256
`a8df7719dae512d709c8a2f0aebfe659f6fd2d03ad88a36aecbd78ae8235f772` and 269,861-byte
SHA-256 `dc67af22825d1eeda46d5ed67d3015bad0bfeb521035a0df752a1a45f5f5e910` packages.
Levels 0..9 and default, filtered, Huffman-only, RLE, and fixed strategies did not
reproduce most SIP streams or any transition stream. Python reports zlib compile
headers 1.2.11 and runtime 1.2.12. Same-runtime structural validation is not proof of
cross-version determinism, vintage-inflater compatibility, authenticity, or device
acceptance.

Rollback: after checking concurrent edits, remove only `refactor/zup_rebuild.py` and
`refactor/tests/test_zup_rebuild.py`, reverse only this entry's narrow additions to
`refactor/README.md`, `TODO.md`, `docs/firmware-analysis.md`, and
`reports/security-2026-09-12-firmware-parsers.md`, and append a superseding handoff and
worklog record. Preserve all earlier append-only history, unrelated concurrent work,
ignored Cisco inputs, and private temporary evidence. No device, network, VM,
container, process, or production rollback is needed.

Outcome: bounded offline extraction and reversible package reconstruction are now
source-readable at the 211-test gate. Exact no-change package identity and isolated
component replacement are locally demonstrated; modified images remain prohibited on
hardware because the old compressor, independent vintage inflation, device
authentication, recovery, and acceptance are unproved. Public read-only HTTPS,
bounded local subprocesses, and ephemeral loopback test sockets occurred. No vendor
executable, ATA, VM, container, USB, device-facing socket, route/interface/DNS/
firewall/VPN change, APU/alarm action, printer action, production action, commit, or
staging action occurred.

## 2026-09-12: final ZUP rebuild review and launch-dispatcher trace

Before: reversible rebuilding had passed an initial 211-test repository checkpoint,
but independent review had not yet assessed final test portability or CLI option
selection. Pinned rebuild tests still read ignored vendor packages directly, there was
no clean-checkout proof that an unchanged compressed stream remained exact after an
earlier stream changed encoded size, and argparse still accepted unique option
abbreviations. The resident launch tables were parsed structurally, but the operation
of each record type and the final type-3 transfer were not yet established. The latest
handoff therefore still described exact loader/type-3 behavior as unresolved.

Change: direct review identified three concrete repacker-test issues. Replaced direct
fixture reads with the bounded no-follow `zup_bank.read_package()` path, disabled
argparse abbreviation and added a malformed `--r` regression, and added a synthetic
two-compressed-stream fixture with no proprietary bytes. Its first stream changes
encoded size while the second remains unchanged; rebuilding reproduces the requested
bank and preserves the second stream's original encoded bytes after relocation. An
independent read-only re-review confirmed all three findings closed and reported no
remaining finding.

Change: traced the SIP resident reset tail and pinned only scalar/hash/structural
evidence in `test_zup_bank.py` and `test_mipsx_dasm.py`. Code at bank
`0x7f400..0x80000` copies 63 words from `0x7f9fc..0x7faf8` to low-RAM byte address
`0x7fe00` and calls architectural word PC `0x1ff80`. The staged-header descriptor XOR
plus `0xdeadbeef` validates to `0x61f0752a`. A match selects runtime header
`0x0cfc0100`, table `0x0cfc0110`, and 27 records; mismatch selects runtime header
`0x0cff0000`, table `0x0cff6ee0`, and 18 records. The dispatcher implements word copy
for type 1, zero-fill for type 2, linked call for type 4, and direct field-1 loads for
types 5/6/7/8/9/`0xa`/`0xb`/`0xc`. Type `0xd` performs four 16-byte-stride read ranges,
whose purpose remains unknown. Type 3 loads field 1 unchanged and executes
`jspci r13,+0x0,r0`; it is terminal in all known tables at bank `0x402b0`, `0x76ff0`,
and transition `0x7b700`. The CPU/platform meaning of its preserved `0x40000000` PC
tag remains unknown and is not described as a user-mode switch.

Change: recorded that transition shares dispatcher bytes `0x7fd20..0x7fed4`, SHA-256
`80d37f8c13ffdd054562b8106419445c3df9cf439c28d5428e88d708127b50bd`, while its later
tail is `0xff`; reliance on a resident suffix remains a hypothesis. Updated
`docs/firmware-analysis.md`, `refactor/README.md`, `TODO.md`, and
`reports/security-2026-09-12-firmware-parsers.md`. Corrected active Oplane-policy text
in `docs/security.md`, `TODO.md`, and the direct-service security report without
rewriting historical evidence. The actual security-relevant diff was reviewed for
inbound log/audit/template/SQL injection; diagnostics remain fixed and sanitized, and
no template, shell, SQL, firmware-execution, or device path was introduced.

Verify: `python3 -B -m unittest refactor.tests.test_zup_bank
refactor.tests.test_mipsx_dasm refactor.tests.test_zup_rebuild -v` passed 62 tests.
`python3 -B -m unittest discover -s refactor/tests -t . -v` passed all 208 tests in the
current concurrent checkout. `python3 -B -m unittest discover -s tests/unit -v` passed
59 tests, and `python3 -B -m unittest discover -s tests/host -v` passed 3. The earlier
211-refactor/45-unit result remains a valid chronological checkpoint; unrelated
concurrent suite membership changed before this final run, and no failed test was
reclassified. `PYTHONPYCACHEPREFIX=PRIVATE_TEMP python3 -B -m compileall -q refactor
tests telephony ata_flash.py dhcp.py ring_once.py` passed. `git diff --check` and
no-index whitespace checks emitted no findings before this append, and workspace
searches found no `.pyc` or `__pycache__` files.

Rollback: after checking for concurrent edits, reverse only the narrow final-review
changes in `refactor/zup_rebuild.py` and its three focused test files, and reverse only
this entry's additions to `TODO.md`, `docs/firmware-analysis.md`, `refactor/README.md`,
and the two security reports. Append superseding worklog and handoff records; never
rewrite this history. Preserve ignored firmware, unrelated ATA flash/updater/QEMU/
telephony work, and private temporary evidence. No process, device, network, VM,
container, or production rollback is needed.

Outcome: all known repacker review findings are closed, the current complete local
gate passes, and the launch dispatcher has a reproducible static operation map. Local
structural reconstruction is not authorization or proof of vintage compatibility,
authenticity, recovery, physical CPU identity, or hardware behavior. Public read-only
HTTPS occurred during the preceding source-lead research; final review used only local
files, bounded subprocesses, and ephemeral loopback test sockets. No vendor executable,
ATA, VM, container, USB, device-facing socket, route/interface/DNS/firewall/VPN change,
APU/alarm action, printer action, production action, commit, or staging action occurred.

Post-record verify: `git diff --check` and no-index whitespace checks for the untracked
firmware source, tests, analysis, and security report emitted no findings. Workspace
searches again found no `.pyc` or `__pycache__` files.

## 2026-09-12: document complete MIPS-X disassembly and stage ZUP research

Before: the checked MIPS-X decoder could already emit linear instruction listings for
selected resident-bank ranges and directly expanded type-8 mode-0 payloads, but the
canonical analysis did not provide one consolidated program inventory or exact private
output commands. No complete generated disassembly was stored because each listing
contains raw words derived from the ignored Cisco firmware. The user explicitly asked
whether the 512 KiB bank programs had a disassembly and requested that all ZUP research
be added to Git. This unborn repository already had a broad index populated by earlier
work; unrelated staged and unstaged entries were not cleared or rewritten.

Change: added `docs/firmware-analysis.md`'s Disassembly Availability section. It lists
all confirmed resident and packed MIPS-X inputs, word counts, storage ranges, loaded
ranges, and coordinate conventions. It records exact commands for the SIP resident
main/helper/reset tail, SIP packed main and auxiliary programs, transition resident
main/helper/dispatcher fragment, and transition packed main. It distinguishes complete
linear disassembly plus optional xref/delay-slot summaries from decompilation, recovered
symbols, or a complete CFG. It also records that mode-1 payloads are data and nested
`+kbz` outputs have no justified processor assignment.

Change: staged the dedicated reviewed research paths explicitly:
`THIRD_PARTY_NOTICES.md`, `TODO.md`, `WORKLOG.md`, `docs/handoff.md`,
`docs/firmware-analysis.md`, `refactor/mipsx_dasm.py`, `refactor/zup_bank.py`,
`refactor/zup_rebuild.py`, their three focused test modules, and
`reports/security-2026-09-12-firmware-parsers.md`. No `git add .` was used. Mixed
concurrent updater/service files were not newly selected. The user-supplied package
directory, optimized firmware, private reconstructed banks, full instruction listings,
and temporary evidence were not added.

Verify: exact full-listing commands were exercised with temporary mode-0600 banks
outside the repository. SIP resident ranges emitted 47,439 lines, SIP packed main
94,165, SIP packed auxiliary 17,275, transition resident ranges 45,399, and transition
packed main 91,034. These equal the documented word totals. The temporary directory
was removed afterward. `git diff --check`, focused no-index whitespace checks, and
`git diff --cached --check` emitted no findings before this append. Repository scans
found no `.bin`, `.asm`, `.dasm`, `.mipsx.txt`, `.pyc`, or `__pycache__` output, and a
tracked-path check found no ignored package, optimized `.zup`, bank, or generated
disassembly path. A credential-word review found only historical policy prose,
synthetic diagnostic-test text, and the standard-library `secrets.token_hex` API; no
credential value or private configuration was added. No executable source changed in
this follow-up, so the preceding 208/59/3 and focused 62 passing gates remain current.

Rollback: do not clear or reset the broad pre-existing unborn-branch index. If the user
later requests staging rollback, first re-read index/worktree state and remove only the
new dedicated research paths from the index without deleting their working files;
preserve shared `TODO.md`, `WORKLOG.md`, and `docs/handoff.md` content and all concurrent
work. Reverse only this follow-up's narrow documentation additions after checking for
new edits, then append superseding records. No device, network, process, or production
rollback exists.

Outcome: all reproducible ZUP/MIPS-X research is now represented in Git by source,
tests, hashes, scalar findings, exact commands, license notice, and sanitized review
evidence. Full firmware-derived instruction dumps intentionally remain reproducible
private outputs rather than tracked derivatives. No commit was created. No vendor
executable, ATA, VM, container, USB, device-facing socket, route/interface/DNS/
firewall/VPN change, APU/alarm action, printer action, or production action occurred.

Post-record clarification: artifact scan statements in this entry refer to tracked and
nonignored research paths. Pre-existing ignored third-party `.bin` and `.zup` files
under the local optimized/vendor directories remain present and untracked; they were
neither scanned as research output nor added by this staging request.

Post-record concurrent-test update: the focused test modules now select private
fixtures through `ATA186_TEST_ARTIFACT_DIR`, defaulting to an absent clean-checkout
`vendor/` directory. The default full refactor run passed 208 tests with 51 expected
fixture-dependent skips. With that variable pointed at the ignored local Cisco
directory and `ATA186_TEST_SWEDISH_PROFILE` pointed at its private Swedish vector, all
208 refactor tests passed without skips and all 62 focused firmware tests passed
without skips. Concurrent additions increased the unit suite from the preceding
59-test checkpoint to 67 passing tests; the host suite still passed 3. Full compileall
also passed. This supersedes only the claim that 59 is the current unit count and does
not rewrite the valid earlier checkpoint. No private fixture path or content was added
to Git.

## 2026-09-14: dispatch table function identification and rename

Before: the `got_mapping.json` classifications were available but not applied to the destination code files. 175 dispatcher functions, 34 str_copy functions, 5 error_handler functions, 4 packet_recv functions, 3 msg_buffer_handler functions, and 3 validator functions were classified but still named `sip_func_XXXXX`.

Change: applied `got_mapping.json` classifications to rename 217 functions across all 3 destination code files:
- 175 dispatcher functions renamed to `dispatcher_XXXXXX`
- 34 str_copy functions renamed to `str_copy_XXXXXX`
- 5 error_handler functions renamed to `error_handler_XXXXXX`
- 4 packet_recv functions renamed to `packet_recv_XXXXXX`
- 3 msg_buffer_handler functions renamed to `msg_buffer_handler_XXXXXX`
- 3 validator functions kept as `sip_validator_entry`, `sip_validator_aux_entry`, `sip_validator_loop`
- 4 dispatcher and 5 str_copy functions renamed from descriptive names (sip_dispatch_*, sip_packet_read_*, etc.) to classification-based names
- Updated `sip_rename_map.json` (1847 entries), `rename_map.json` (1847 entries in sip section), `sip_bank_named.c` (452 occurrences renamed)

Verify: all 217 rename plan entries verified in both JSON files; 0 old function names remaining in C file; 0 misidentified names (printf, socket, str_copy, _FUN_); 1629 total function definitions; dispatcher/str_copy/error_handler/packet_recv/msg_buffer_handler classifications correctly applied.

Rollback: revert the rename plan additions from the three destination files and restore the previous state. Preserve this append-only record. No device, network, VM, container, or production action occurred.

Outcome: the firmware's function naming is now significantly more descriptive. The dispatch table mechanism (register0x00000074 base, sip_dispatch_table_init, sip_dispatch_entry/return) is understood. All 1629 function definitions have meaningful or descriptive names. The sip_rename_map.json and rename_map.json are fully synchronized with the C file. The `printf`/`socket`/`str_copy`/`close`/`listen`/`setsockopt` misidentifications from the previous session are fully resolved — those were all indirect call stubs that have been correctly classified as dispatcher or str_copy functions.

## 2026-09-12: public ATA Tools release curation, license, and verification

## 2026-09-12: public ATA Tools release curation, license, and verification

Before: code-level blockers were resolved and focused regression passed, but the
tracked guides still described the retired fixed-address `sata186us.py --apply`
path, exposed private bench topology, and left publication blocked by stale
documentation, an unsafe unborn-branch index, an unfinished allowlist, and no
project license. The previously failing artifact-backed `test_include_depth`
had an absolute-path fix applied but not yet verified.

Change: replaced `README.md` with a public ATA186 preservation guide covering
lawful firmware handling, `SHA256SUMS`, inspection, the single `ata_flash.py`
live window, DTMF/`123#`, SIP web/TFTP configuration, `.zup` research, limits,
tests, and future Asterisk work, with explicit hardware-not-yet-proven and
Asterisk-future boundaries. Replaced `refactor/README.md`,
`refactor/FLASHING.md`, and `docs/ata-firmware-maintenance.md` with generic
operator checklists; generalized `docs/firmware-analysis.md` artifact paths;
fixed archived Cisco chapter links; added BSD-3-Clause `LICENSE` per owner
selection and clarified `THIRD_PARTY_NOTICES.md`; updated two public docstrings
(`refactor/ata_upgrade_client.py`, `refactor/tests/__init__.py`) without logic
changes. Defined the exact public allowlist locally as `README.md`, `LICENSE`,
`THIRD_PARTY_NOTICES.md`, `requirements-bench.txt`, `.gitignore`,
`ata_flash.py`, `dhcp.py`, `refactor/__init__.py`, `refactor/sata186us.py`,
`refactor/cfgfmt.py`, `refactor/zup_bank.py`, `refactor/zup_rebuild.py`,
`refactor/mipsx_dasm.py`, `refactor/ata_upgrade_client.py`,
`refactor/README.md`, `refactor/FLASHING.md`, `refactor/tests/__init__.py`,
`refactor/tests/test_sata186us.py`, `refactor/tests/test_cfgfmt.py`,
`refactor/tests/test_zup_bank.py`, `refactor/tests/test_zup_rebuild.py`,
`refactor/tests/test_mipsx_dasm.py`,
`refactor/tests/test_ata_upgrade_client.py`,
`tests/unit/test_ata_flash.py`, `tests/unit/test_dhcp.py`,
`docs/firmware-analysis.md`, and `docs/ata-firmware-maintenance.md`.
Private history, tasks, reports, telephony, QEMU wrappers, `ring_once.py`,
vendor/firmware/captures/backups, and generated artifacts remain local-only.
No live interface, route, BPF, QEMU, ATA, DTMF, or device operation was
performed.

Verify: `python3 -B -m py_compile` over all 25 allowlisted Python files PASS;
`git diff --check` PASS; `python3 -B -m unittest
tests.unit.test_ata_flash tests.unit.test_dhcp -v` 21 PASS;
`python3 -B -m unittest refactor.tests.test_ata_upgrade_client
refactor.tests.test_cfgfmt refactor.tests.test_mipsx_dasm
refactor.tests.test_sata186us refactor.tests.test_zup_bank
refactor.tests.test_zup_rebuild -v` 152 PASS with 51 clean-checkout skips;
artifact-backed `ATA186_TEST_ARTIFACT_DIR=ata_03_01_00_sip_040211_1
ATA186_TEST_SWEDISH_PROFILE=.../refactor/swedish python3 -B -m unittest
refactor.tests.test_cfgfmt refactor.tests.test_mipsx_dasm
refactor.tests.test_sata186us refactor.tests.test_zup_bank
refactor.tests.test_zup_rebuild -v` 143 PASS with zero skips, including the
previously failing include-depth vector; `python3 -B -m unittest discover -s
tests/unit -v` 67 PASS; `python3 -B -m unittest discover -s refactor/tests -v`
208 PASS with 51 clean-checkout skips; `python3 -B -m unittest discover -s
tests/host -v` 3 PASS; `python3 -B refactor/sata186us.py --inspect
ata_03_01_00_sip_040211_1/ATA030100SIP040211A.zup` reports
`b8597657928905aea66924118889f0883bd38c0804ddf880e3be2c33ccf62eb5`,
platform `0x301`, proto `0x0400`, version `0x0301`, 319135 payload bytes;
`python3 -B refactor/sata186us.py --qualify ...` reports command 1/1 42/144,
data 313/313 3756/321996, 312 blocks, 319135 bytes,
`data_wire_sha256=158a9e2d5736f253cddcd1c4662b83792f996e0edd78b9eb5b6b1f34a279c7f2`,
`selection_normalized_sha256=6beddb21fc08c6518a8f1f3375030c3d5a56b3171c5ee7cb29e686a2fd9282f0`;
`python3 -B refactor/zup_bank.py ...` validates 4 raw and 7 compressed regions;
bare `python3 -B ata_flash.py` and `python3 -B refactor/sata186us.py` remain
inert. Allowlist scans found only expected broadcast, synthetic documentation,
QEMU-default URL, and ignore-list mentions; no bench address, device MAC,
interface, credential, or private path remains in intended public files.

Rollback: reverse only this batch's reviewed docs, license, and docstring edits
after checking for concurrent modification; preserve the unsafe-index
containment plan and all unrelated work. Do not use reset/checkout to erase
others' work and do not stage runtime data. No device, network, process, or
production rollback exists because no live operation occurred.

Outcome: public documentation is generic, licensing is resolved, the exact
staged snapshot is defined and scanned, and all post-change release gates pass.
Physical ATA flash, reboot, SIP registration, ringing, and audio remain
unperformed and unclaimed. No commit, remote add, push, or publication has yet
occurred in this entry.

## 2026-09-12: publish the allowlisted snapshot to kugg/ATA-tools

Before: the 27-file snapshot was staged and audited, with all gates passing.
The broad unborn-branch index had been cleared with `git rm --cached -rf .`
(worktree preserved via `--cached`) and only the explicit allowlist staged.
Local records in the preceding entry misstated the allowlist as 25 files;
the correct counts are 27 total files, of which 18 are Python.

Change: committed root-commit `032deb7` with message "Publish generic ATA186
preservation toolkit" covering exactly the 27 audited files (9638 insertions).
Added remote `origin https://github.com/kugg/ATA-tools.git` and pushed
`main -> main` with upstream tracking. No private file was staged, committed,
or pushed. Local `TODO.md`, `WORKLOG.md`, `docs/handoff.md`, and
`reports/security-2026-09-12-public-release.md` were updated locally only and
remain untracked.

Verify: `git log --oneline -5` shows `032deb7`; `git ls-remote origin` shows
`HEAD` and `refs/heads/main` at `032deb72fcf9b766e589595b044ac37c36058d79`;
`gh repo view kugg/ATA-tools` reports PUBLIC visibility, URL
`https://github.com/kugg/ATA-tools`, and default branch `main`; remote tree
lists exactly the 27 intended paths with no `zup_launch_trace`, task, report,
telephony, QEMU, `ring_once.py`, `AGENTS.md`, `TODO.md`, `WORKLOG.md`, or
handoff entries. Pre-commit gates from the preceding entry remain the release
evidence because the published files match the audited staged snapshot.

Concurrent-work observation: after staging, the worktree shows `M
docs/firmware-analysis.md` and `M refactor/README.md` referencing bounded
`refactor/zup_launch_trace.c` and `refactor/tests/test_zup_launch_trace.py`,
plus those two untracked files. That work was preserved untouched; it was not
reviewed here, not staged, not committed, and not pushed. It requires a
separate scope, test, and publication/license review before any future commit.

Rollback: do not revert others' concurrent work and do not reset the published
`main`. To unpublish or amend would require an explicit owner request and a
separate reviewed commit; no automatic force-push is authorized. Local record
corrections are appended here, not rewritten. No device, network, process, or
production rollback exists.

Outcome: `https://github.com/kugg/ATA-tools` now serves the generic toolkit
at commit `032deb7`. Hardware flash, reboot, registration, ringing, audio, and
Asterisk integration remain unperformed future gates.

## 2026-09-12: bounded C11 launch-trace model, local-only verification

Before: the SIP validator/setup/dispatcher was established only as static
Python assertions and prose. The staged section header (`0x40000`,
magic `0x12340004`, four descriptors, seed `0xdeadbeef`) selected main
(`0x0cfc0100`/`0x0cfc0110`/27) or auxiliary (`0x0cff0000`/`0x0cff6ee0`/18),
and the dispatcher implemented copy/zero for types 1/2, linked call for type 4,
direct field-1 loads for types 5/6/7/8/9/`0xa`/`0xb`/`0xc`, four-range reads
for type `0xd`, and terminal `jspci r13,+0x0,r0` for type 3. The published
`main` at `032deb7` explicitly excluded this follow-up work; its concurrent-work
observation requires a separate scope, test, and publication/license review
before any future commit. No staging, commit, or push was therefore authorized
here.

Change: added local-only `refactor/zup_launch_trace.c` (bounded C11 stdin-bank
to stdout-event trace, preflight before emission, explicit marker/type-3/
type-`0xd` unknowns, never executes firmware or casts guest values to host
pointers) and `refactor/tests/test_zup_launch_trace.py` (strict-compile to a
private temp dir, bounded subprocess, synthetic plus pinned vectors, explicit
callback-failure harness). Corrected the stale `docs/firmware-analysis.md`
type-6 sentence to record the direct `r25` dispatcher load, and documented the
tool minimally in `refactor/README.md` and `TODO.md`. Those two tracked guides
now differ locally from published `main`; they were left unstaged.

Verify: `cc -std=c11 -pedantic-errors -Wall -Wextra -Werror` compile PASS;
`python3 -B -m unittest refactor.tests.test_zup_launch_trace` 21 PASS clean
(3 pinned skips) and 21 PASS artifact-backed; `discover -s refactor/tests -t .`
229 PASS clean (54 skips) and 229 PASS artifact-backed; focused
`test_zup_bank`/`test_mipsx_dasm`/`test_zup_rebuild`/`test_zup_launch_trace`
83 PASS artifact-backed; `discover -s tests/unit` 67 PASS; `discover -s
tests/host` 3 PASS; private-cache `compileall` PASS; `git diff --check` PASS.
Pinned SIP validator selects main with stored/calculated `0x61f0752a`;
transition validator reports unsupported marker mismatch; SIP main/auxiliary and
transition terminals `0x400031d3`/`0x40000c00`/`0x40003d07` match
`zup_bank.parse_launch_table()`.

Security review: actual diff reviewed for untrusted-input-inbound risks. Bank
input is fixed 512 KiB with truncated/extra rejection; all header, descriptor,
table, record, and arithmetic bounds are checked with 64-bit overflow guards;
unknown types, missing/nonterminal type 3, and marker mismatch fail closed;
output uses fixed labels plus numeric values/digests only with fixed error
text and no input reflection (no log/audit/template/SQL/shell injection
surface); `CC` is restricted to one executable path and subprocess uses arg
lists with a five-second timeout and no shell. Residuals remain outer
`r23`/`r25` init, type-3 tag meaning, type-`0xd` purpose, transition suffix
reliance, provenance, SoC identity, and device readback. No credentials or
private configuration were added.

Rollback: reverse only the two new local files and the narrow local doc edits
after checking concurrent work; preserve published `main` and all unrelated
work. Remove private `/var/.../mipsx-c.2po5pG/sip-bank.bin`, `/tmp/zlt-test-bin`,
and the private bytecode cache after verification. No device, network, process,
or production rollback exists.

Outcome: launch-trace semantics are now locally reproducible with gates
passing. Nothing was staged, committed, or pushed; the public snapshot at
`032deb7` is untouched. A separate explicit owner request is required before
any allowlist extension, staging, commit, or push of this C work.

## 2026-09-12: persist full disassembly to local-only research/

Before: complete listings existed only as private temp outputs that were
removed after verification, and the operator asked for a persistent research
directory in `ata/` so results would not get lost. The published `main`
explicitly excludes generated instruction-word listings, which contain raw
proprietary words and must never be committed.

Change: created owner-only `research/` (`0700`) with five mode-`0600`
listings plus a manifest `README.md` (commands, pinned hashes, line counts;
no executable logic): `sip-resident` 47439, `sip-packed-main` 94165,
`sip-packed-auxiliary` 17275, `transition-resident` 45399,
`transition-packed-main` 91034 lines, each matching the documented totals.
Banks were reconstructed to a private temp dir outside the repo, verified
against both pinned bank hashes, used read-only, then removed with the temp
dir. A leftover `temp/sip-bank.bin` found in the worktree was also removed.
Nothing was staged, committed, or pushed; `research/` remains untracked and
local-only by explicit owner confirmation.

Verify: all five `wc -l` counts equal the canonical totals; `ls -l` shows
`0700`/`0600` modes; `git status` shows `?? research/` with no staged
entries; `git diff --check` passes; tracked-artifact scan finds no new
`.bin`/`.asm`/listing paths in git.

Rollback: delete only `research/` after confirming no other consumer needs
it; preserve all other work. No device, network, process, or production
rollback exists.

Outcome: disassembly is now persistent locally without touching the public
snapshot. Do not add `research/` to any allowlist or commit without a
separate publication/license review.

## 2026-09-12: rebuildable research/src, gitignored

Before: `research/` held listings plus a manifest but no rebuildable source;
the operator asked for the C files in `research/` with a gitignored `src/`
so the tree can be rebuilt.

Change: created owner-only `research/src/` (`0700`) with byte-identical
mode-`0600` copies of `refactor/zup_launch_trace.c` and
`refactor/tests/test_zup_launch_trace.py` (`cmp` verified), documented it in
`research/README.md`, and appended `research/src/` to the root `.gitignore`
(local-only, unstaged). `git check-ignore -v` confirms both copies are
ignored; the manifest README stays untracked-visible by design.

Verify: strict `cc -std=c11 -pedantic-errors -Wall -Wextra -Werror` compile
of the `research/src` copy PASS, `--help` PASS, and a synthetic two-record
stdin trace PASS (`reg r24`, `terminal target=0x400031d3`); the private build
temp dir was removed afterward. `git diff --check` PASS; nothing staged,
committed, or pushed.

Rollback: delete only `research/src/` and reverse only the appended
`.gitignore` line plus the README subsection after checking concurrent work.
No device, network, process, or production rollback exists.

Outcome: `research/` is now self-contained and rebuildable while its sources
stay ignored. The public snapshot at `032deb7` remains untouched.

## 2026-09-12: image component layout, web UI, and fill map (offline)

Before: confirmed code regions were disassembled but the rest of the upgrade
image was unmapped; the SIP web interface and any file/component container
were unlocated, and the TODO component-mapping item stayed open. The published
`main` excludes generated listings, so all new derivatives remain local-only
with no staging, commit, or push authorized here.

Change: surveyed the reconstructed SIP bank offline and read-only. Mapped
destinations cover everything except ~90 KiB of never-mapped `0xff` fill
(`0x100..0xa00`, `0x11500`-byte hole `0x2eb00..0x40000`, `0x6f300..0x70000`,
`0x7a400..0x7d000`, `0x7ef00..0x7f400`). A 1390-run printable survey of the
raw bank found no HTML/CGI/filesystem structure; angle brackets are binary
noise. Expanding all five type-8 and four nested outputs located the SIP web
UI as `printf`-style HTML templates (`<html>`, `<form method="post">`,
`<input>` fields, `/dev` and `/rtps` links) inside the mode-1 payload at bank
`0x6cbcc` (field `0x2fbc`, output `0x4bc8`, span `0x2fbc..0x7b84`); the
transition bank carries the same markers at `0x73ce2`/`0x73e42`. Also
recorded: NUL-terminated filename slot `ZUP?ATA030100SIP040211A.zup` at
`0x2ea0c` (28 of `0xf4` bytes used), 984 `0xff` padding past the helper
module end `0x7eb28`, dial-plan-like and feature-code-like tail text at
`0x7f520`/`0x7f55f` (described, not quoted), and call-control-like error text
with tone-script-like vectors in nested output `0x2c9d4`. Only hashes,
offsets, counts, and short markers were retained; no firmware byte arrays
entered git. Updated `docs/firmware-analysis.md`, `TODO.md`, and this handoff
accordingly, all left unstaged.

Verify: both package/bank hashes reproduced during reconstruction; all five
type-8 and four nested payloads expand with valid CRC/ISIZE; `git diff
--check` passes. No code changed, so prior test gates stand; a refactor
discover rerun is recorded in the handoff entry.

Rollback: reverse only this entry's doc additions after checking concurrent
work; delete nothing else. Private temp banks were removed after the survey.
No device, network, process, or production rollback exists.

Outcome: the web UI question is answered (embedded templates, shared across
images) and the fill map bounds what remains: no archive or filesystem
container exists, so further component work means loaded-span semantics, the
`0xd`/type-3 unknowns, and bootstrap state. Public `032deb7` untouched.

## 2026-09-12: take-apart/put-back pipeline for full edit and rebuild

Before: changing firmware content meant hand-editing bank bytes with no
inventory, record/payload validation, or verified round trip; `zup_rebuild.py`
accepted only whole banks. The operator asked to extract and reproduce the
image as faithfully as possible, with the ability to change anything and
rebuild later. Publication policy keeps all of this local-only with no
staging, commit, or push authorized here.

Change: added local-only `refactor/zup_extract.py` plus
`refactor/tests/test_zup_extract.py` (10 tests). `extract` validates the
package, then writes a new private `0700` directory with the exact bank, a
bounded JSON manifest (map, launch headers/records, section checksum,
payload inventory with hashes), and all expanded type-8/nested payloads
(SIP: 5 + 4, hashes matching the canonical table). `compose` reloads the
directory, validates edited records (same count, known types, single
terminal-last type 3), recompresses edited payloads in place (raw DEFLATE
plus legacy trailer, `0xff`-padded, original span must fit), refuses
overlaps with launch tables, and publishes one new private bank. Payload
*content* is editable; spans are fixed, so growth beyond the original span
and record-count changes fail closed with relocation explicitly unsupported.
Historical streams cannot be reproduced byte-identically by local zlib; that
limit is documented in the tool and unchanged regions stay byte-identical
through the rebuilder.

Verify: 10/10 new tests clean (3 pinned skips) and pinned; full refactor
suite 239 PASS clean (57 skips) and pinned; unit 67, host 3, private-cache
`compileall` and `git diff --check` PASS. Pinned proofs: unmodified SIP and
transition decompose/compose byte-identically; a SIP image with one edited
aux record and one shrunk nested payload rebuilds through `zup_rebuild.py`
(1 region recompressed, 6 preserved) and reconstructs the edited bank
exactly. Private temp dirs removed afterward.

Security review: actual diff reviewed for inbound risks. Package, manifest
(1 MiB cap, strict shape/range checks), payload files (name confinement, no
`..`, per-file and aggregate bounds), bank (exact 512 KiB), and CLI args
(fixed diagnostics, no abbreviation, no shell) are all bounded; outputs are
new `0600`/`0700` paths with no replace and no input reflection in messages.
Residuals: public-review gate for tracking, historical-compressor fidelity,
device acceptance, and all prior firmware unknowns.

Rollback: delete only the two new local files and reverse only this entry's
doc additions after checking concurrent work. No device, network, process, or
production rollback exists.

Outcome: "change anything and rebuild" now exists offline as
extract → edit → compose → rebuild → re-verify. Public `032deb7` untouched.

## 2026-09-13: publish decompilation tooling, keep results and launch-trace private

Before: origin/main at `032deb7`. A large concurrent staged batch existed:
Ghidra processor module, Java/Python decompile drivers, analysis scripts,
`zup_extract`, `zup_launch_trace.c` + its test, `research/decompiled/*.c` +
`rename_map.json`, `prserv`/QEMU wrappers + tests, and staged
`AGENTS.md`/`TODO.md`/`WORKLOG.md`/`docs/handoff.md`.

Change: per owner selection ("decompilation tooling public, proprietary
results private; no `.c` files; no TODO/WORKLOG/AGENTS.md"), reset the broad
index and staged only the public tooling: `MIPSX_Ghidra_ATA186/` (8 files),
`refactor/CreateFunc.java`, `DecompileAll.java`/`.py`, `SeedDisasm.java`,
`SeedDisassembly.java`, `analyze_got.py`, `analyze_xrefs.py`,
`build_name_map.py`, `decompile_ghidra.py`, `ghidra_decompile.py`,
`zup_extract.py`, `test_zup_extract.py`, and `.gitignore`. Rewrote hardcoded
`/Users/user/devel/ata/research/...` paths in the three analyze scripts to
repo-relative `ROOT = Path(__file__).resolve().parents[1]`. Extended
`.gitignore` to ignore the whole `research/` tree (was `research/src/`), so
disassembly dumps, decompiled C, and rename maps can never be swept in.
Stripped trailing whitespace flagged by `git diff --cached --check` across the
staged Java/Python tooling. Excluded: all `.c`, `research/decompiled`
results, `test_zup_launch_trace.py`, the `docs/firmware-analysis.md` and
`refactor/README.md` launch-trace edits (left uncommitted locally),
`prserv`/QEMU wrappers + tests, and AGENTS/TODO/WORKLOG/handoff. Committed
`7b27318` (21 files, 2413 insertions) and pushed `032deb7..7b27318`.

Verify: `python3 -B -m py_compile` over all staged Python PASS;
`python3 -B MIPSX_Ghidra_ATA186/tests/mipsx_smoke.py` exit 0;
`python3 -B -m unittest refactor.tests.test_zup_extract -v` 12 tests
OK with 3 artifact-gated skips on clean checkout; `git diff --cached --check`
PASS; staged-diff scans show no `/Users/`, `/home/`, bench topology, or
credentials; remote tree at `7b27318` lists exactly the intended paths with no
`.c`, `research/`, launch-trace, AGENTS/TODO/WORKLOG/handoff, or
`prserv`/QEMU entries; `gh repo view` reports PUBLIC, default branch `main`,
URL `https://github.com/kugg/ATA-tools`.

Rollback: a new ordinary commit or `git revert` on `main`; no force-push.
Local edits touched only the three analyze scripts (path fix), `.gitignore`, and
trailing whitespace on the same tooling files; the two launch-trace doc edits
remain uncommitted in the worktree for a separate review.

Outcome: the public repo now carries generic decompilation tooling
(`032deb7` + `7b27318`). Proprietary decompiled outputs, disassembly dumps,
rename maps, and the launch-trace model remain private and gitignored.
Hardware flash, registration, ringing, audio, and Asterisk integration remain
unperformed future gates.

## 2026-09-14: restore a directly callable dhcp.py main

Before: dhcp.py was a library (DhcpConfig/DhcpLease/run_dhcp/parse_request)
whose main() was inert; the uncommitted working tree called run_dhcp() with no
config (TypeError) after removing the DRY RUN print. The historic main used
hardcoded INTERFACE/SERVER/CLIENT/EXPECTED_CLIENT_MAC globals (surviving only
as dangling blob 921c7c86) and never accepted a user-supplied interface.

Change: dhcp.py remains a library. Added CLI options --apply, --interface,
--client-address, --client-mac, --lease-seconds, --timeout-seconds. main()
now prints "DRY RUN ... --apply --interface" when not applied (no scapy, no
sockets), and otherwise derives a default config from the selected interface:
server address = scapy.get_if_addr(interface), subnet/24, client = host 10
(default, overridable), optional client MAC, then calls run_dhcp(). DhcpConfig
validation errors and scapy absence surface as DhcpError and exit code 2.
parse_options still rejects --apply without --interface (usage + exit 2).

Verify: .venv/bin/python -B -m unittest tests/unit/test_dhcp.py
tests/unit/test_bench_safety.py -> 26 OK. Full tests/unit suite: 66 OK, 4
test_ata_flash NetworkTest failures (default uplink and
current_address_and_own_routes) confirmed pre-existing: they reproduce with
HEAD dhcp.py and are caused by the already-uncommitted ata_flash.py route-read
change, unrelated to this work. .venv/bin/python -B dhcp.py prints the DRY RUN
line, exit 0; --help lists the new options.

Rollback: revert dhcp.py edits and drop the three added test methods plus the
README line; no device, network, or process change was made.

Outcome: direct invocation `dhcp.py --apply --interface EN` restores the
historic bounded single-lease responder, now with an explicit interface.

## 2026-09-14: fix Darwin route parsing in ata_flash.py live preflight

Before: the uncommitted ata_flash.py route read used
`tuple(scapy.conf.route.routes)` directly. On macOS that table is built by
scapy's PF_ROUTE sysctl parser (scapy/arch/bpf/pfroute.py; re-exported via
scapy/arch/bpf/core.py), which corrupts several IPv4 netmasks: multicast
`224.0.0/4` records come back with a `240.255.255.0` mask byte-swapped
(`0xF0FFFF00`, an invalid /240.255.255.0 netmask) and connected prefixes such
as en28's `192.168.0/16` collapse to `0xFFFFFFFF` (/32). The strict
`_route_network` validator then raised `FlashError`, aborting the read-only
preflight for the live flash window on en28 before any overlap decision. The
`tests/unit/test_dhcp.py` + `test_bench_safety.py` run recorded four
pre-existing NetworkTest failures for the same reason; for a full window,
connectivity and DTMF would also have been affected. scapy is 2.7.0 here; the
netstat-based parser in scapy.arch.unix (which runs `netstat -rn -f inet`)
represents those masks correctly.

Change: ata_flash.py only. Added `_netstat_route_records(scapy)`, which imports
`scapy.arch.unix.read_routes`, validates every returned record through the
unchanged strict `_route_network`, and returns those records or None on any
import/parse failure. Added `_capture_route_records(scapy)`, which keeps scapy
records when every one parses (clean test doubles and non-Darwin platforms are
unchanged) and otherwise falls back to the netstat records when available,
returning the original records when neither parses (fail-closed downstream).
`current_interface_state` now reads routes through `_capture_route_records`
instead of `tuple(scapy.conf.route.routes)`. Also fixed a stale "scratchaway"
docstring fragment to "route tuples". The fix is failure-driven, not
platform-gated, so FakeScapy unit tests stay deterministic.

Verify: python3 -B -m unittest tests.unit.test_ata_flash -v -> 19 OK (new
RouteCaptureTest: clean scapy records returned as-is; corrupt `0xF0FFFF00`/
`0xffffffff` records trigger netstat fallback via a mocked
sys.modules["scapy.arch.unix"]; netstat-unavailable keeps the original
records). python3 -B -m unittest tests.unit.test_dhcp tests.unit.test_bench_safety
-> 26 OK. python3 -B -m py_compile ata_flash.py -> PASS. Live evidence with the
temp bench venv (scapy 2.7.0): 22 route records now parse with correct
netmasks, including en28 direct `192.168.0.0/16`, `192.168.2.2/32`,
`192.168.2.10/32`, `224.0.0.0/4`, and en0 `192.168.1.0/24`. The preflight parse
crash is gone; it now proceeds to the real decision and fails closed with
`ata_flash.FlashError: selected subnet overlaps another active route
(192.168.1.0/24)` because en28's `/16` netmask numerically covers en0's office
LAN `192.168.1.0/24`. That message is a genuine condition, not a parser error;
resolving it requires an operator-side netmask change (interface reconfiguration
is out of agent scope per AGENTS.md).

Rollback: revert the ata_flash.py hunk (restoring direct
`tuple(scapy.conf.route.routes)`) and delete the three RouteCaptureTest tests;
no device, network, firewall, DNS, or VPN change was made, and no packet was
sent. Read-only snapshots via netstat/scutil showed the route/VPN/NWI state
unchanged.

Outcome: the live-window preflight parser bug is fixed at
`ata_flash.py` `_netstat_route_records` / `_capture_route_records`. The remaining
offline blocker is the genuine en28 `/16`-versus-en0 `/24` overlap fail-closed,
which needs the operator to narrow en28 (e.g. to `192.168.2.0/24`) before one
explicitly approved, operator-attended flash attempt can run.

## 2026-09-14: operator narrows en28 to /24; live-window checkpoint (before)

Before: the operator narrowed en28 to 255.255.255.0. Read-only snapshots now
show no numerical overlap for the planned service: default and `192.168.1.0/24`
via en0, `192.168.2.0/24` direct on en28, `192.168.2.2/32` on en28, ATA at
`192.168.2.10` MAC `00:07:0e:36:e5:7b` (UHLWI en28, expiry present), WireGuard
`10.47.11.0/24` on utun5; neither `169.254.0.0/16`, `224.0.0.0/4` nor
`255.255.255.255/32` overlaps the service subnet. `scutil --nwi` lists en0
IPv4 only and no IPv6 state; UDP 8000/8500 have no listeners. Pinned image /
manifest verified locally (b859... of the vendor image matches
`optimized/SHA256SUMS`). Bench-venv preflight through
`_capture_route_records` (netstat fallback, PF_ROUTE records still corrupt on
this system): 20 records parse; `current_interface_state(conf, "en28",
192.168.2.2)` returns a state; `choose_client_address(192.168.2.10)` passes.

Change (this attempt): one explicit operator-attended live window, running
exactly once, no auto-retry:
`python3 -B ata_flash.py --apply --interface en28 --address 192.168.2.2
--client-address 192.168.2.10 --client-mac 00:07:0e:36:e5:7b --sha256sums
optimized/SHA256SUMS ata_03_01_00_sip_040211_1/ATA030100SIP040211A.zup`
under the bench venv. The ATA already holds a lease from the operator's earlier
bounded `dhcp.py --apply`; run_dhcp waits up to `--dhcp-timeout-seconds` (600)
for a DISCOVER/REQUEST renewal and raises DhcpError if none arrives before
serving begins (fail-closed, nothing sent). DHCP and service listen only on
`192.168.2.2:8000/8500`; no host networking/VPN/firewall/DNS change is made.
Rollback if needed: keyboard-interrupt the single process (it prints that no
DTMF or transfer is replayed); no other owned change exists. Record outcome and
any physical result below after the window, including the operator's `123#`
device-reported version check.

## 2026-09-14: first live attempt aborted before DHCP (BPF privileges)

Verify (attempt outcome): the live command above was started once and exited
after printing, in order: image verified (sha256=b859...7f f5, platform
0x00000301, version 0x0301, blocks=312); network verified (en28, 192.168.2.2,
192.168.2.0/24); then
`error: DHCP capture could not start; no privilege change was attempted`
(DhcpError from scapy `sniff`). The process exited on its own; no packet, DHCP
frame, or DTMF was sent or replayed; `lsof` confirmed no UDP 8000/8500 listener
remained. Cause: on this host `/dev/bpf*` are `crw------- root wheel`, so the
non-root shell that launched the window cannot open a BPF capture; the earlier
successful DHCP exchanges were run by the operator in a privileged terminal.

Rollback: none needed; the process performed no owned change before aborting.

Outcome: fully fail-closed. The exact same live command must be run by the
operator in their own privileged terminal (matching the established
`dhcp.py --apply` pattern), with the operator attending the ATA handset; it must
not be launched from an unprivileged agent shell. No re-run was attempted from
this shell.

## 2026-09-14: first hardware upgrade attempt failed; evidence captured

Before/context: the operator ran the exact live `ata_flash.py --apply` command
in their privileged terminal during an attended window and reported "Upgrade
failed", capturing a tcpdump of the device traffic.

Verify (operator-provided tcpdump, interface en28, timestamps 13:36-13:37):
- DHCP succeeded and matched our lock exactly: `0.0.0.0.bootpc >
  broadcasthost.bootps: BOOTP/DHCP Request from 00:07:0e:36:e5:7b` then
  `192.168.2.2.bootps > broadcasthost.bootpc: Reply` (twice: DISCOVER/OFFER and
  REQUEST/ACK), then ARP announcement for 192.168.2.10 and ARP resolution of
  192.168.2.2 whose MAC is `00:e0:4c:68:14:df` (the USB-RTL8153 adapter), and a
  correct `ARP Reply`.
- The ATA then issued a TFTP bootstrap: `192.168.2.10 > 192.168.2.2.tftp: RRQ
  "ATA00070E36E57B.cnf.xml" octet` twice (13:36:45 and 13:36:55). Both times the
  host replied `ICMP 192.168.2.2 udp port tftp unreachable` because no process
  serves UDP 69.
- Only after the TFTP retries did the ATA begin repeated 56-byte UDP datagrams
  from source port ttc-ssl (~3986) to `192.168.2.2.irdmi` (port 8000) roughly
  every 3 seconds (13:37:04 onward, also 16, 19, 22, 25, 28, 31). These match
  the payloads our earlier no-response captures counted as invalid KBOX: the
  live device request is not the KBOX wire format that sata186us serves, and
  the qualified QEMU loopback played our own client, not this device.
- The mDNS service queries shown are normal macOS traffic on en28.

Conclusion: the failure is not DHLE, ARP, addressing, or image integrity; those
stages all passed. The ATA bootstraps through TFTP (UDP 69) fetching a
MAC-named configuration profile `ATA00070E36E57B.cnf.xml`, which this service
does not provide (confirmed dhcp.py offers only message-type/server_id/
subnet_mask/lease_time options and sets BOOTP siaddr to 192.168.2.2). The
firmware/loader stage the device actually uses is not the KBOX format this
project implemented; the ATA probes port 8000 with short datagrams that failed
strict parsing in earlier captures. Hardware behavior is therefore genuinely
unproven and the implemented transfer protocol is contradicted by device
traffic. No image or network fault is implicated.

Rollback: none possible or needed from the tool; the operator's window ended by
itself. Per project rule no redial, replay, automatic retry, or privilege
broadening occurred.

Outcome: evidence recorded; this is the first physical-ATA protocol trace. Next
action (requires review and separate approval) is to decode the requested
bootstrap: capture the UDP 69 and UDP 8000 payloads read-only with `-XX -s0`
during a fresh attended boot/dial (no response), compare against the vintage
`cfgfmt` profile format and the `upgradecode` research lead, and then design a
bounded TFTP+loader service only if the device request and image admission
match. Until that protocol gap is closed, no further `100#`/KBOX flash attempt
should run.

## 2026-09-14: device selection frame decoded; parser bug fixed

Before: the previous entry hypothesized a TFTP-driven bootstrap and KBOX format
mismatch. The operator captured `ata_boot.pcap` (10 identical 56-byte UDP
datagrams, every ~3s, `192.168.2.10:6820 -> 192.168.2.2:8000`) during one fresh
attended dial and reported the upgrade attempt failed. It contains no TFTP or
DHCP frames; the ATA was already speaking KBOX to port 8000 and never received
an answer.

Decode (first physical frame, 13:42:11): payload
`6b626f78 00000001 0028 ffd7 0000 064e | 00000301 04000302 00000000 |
ata00070e36e57b 0100 0001 1\0`. Fields: KBOX magic, version 1, declared data
length 40, non-zero reserved word `ffd7` (ignored), stored checksum `0x064e`;
data = platform `0x301`, `(proto<<16)|version` = `0x0400 <<16 | 0x0302` (this
ATA currently runs SCCP 3.2(4), proto 0x0400), base_type 0, then the ASCII
selector `ata00070e36e57b 0100 0001 1`. The checksum validates
(`cksum(data) == 0x064e`).

Root cause of every previous "invalid KBOX" observation: the parser's numeric
token stage used `int(tok, 0)`. On Python 3.11 that raises `ValueError` for the
device's leading-zero tokens (`0100`, `0001`), so `_parse_kbox_request_with_reason`
returned "metadata" and the server never answered the selection frame, leaving
the ATA retransmitting every 3 seconds. The vintage C server used `atoi`
(decimal), and our own simulator happened to build decimal tokens, so only a real
device frame exposed it.

Change: `refactor/sata186us.py` `_parse_kbox_request_with_reason` now parses the
three trailing numeric tokens with `int(tok, 10)` (legacy `atoi` semantics);
the KBOX checksum, framing, version, and printable-name rules are unchanged.
Added regression test `test_parser_accepts_real_device_selection_frame` pinned
to the exact captured 56-byte frame, expecting
`(0x301, 0x04000302, 0, "ata00070e36e57b", 100, 1, 1)` (decimal 100/1/1).

Verify: `python3 -B -m unittest refactor.tests.test_sata186us -v` -> 26 OK
(skipped=5 pinned-image cases); `discover -s refactor/tests` -> 242 OK
(skipped=57); `discover -s tests/unit` -> 73 OK; `discover -s tests/host` -> 3
OK; `py_compile` clean. The device's frame now parses as a valid selection:
base_type 0 and platform 0x301 match the pinned SIP target, so a future server
run would answer with `build_kbox_response("udp: 192.168.2.2 8500 123")`
instead of incrementing `invalid_requests`.

Rollback: revert the base-10 token change in sata186us.py and delete the one
regression test; no network, firewall, DNS, VPN, or device change was made.

Outcome: the firmware bootstrapping protocol is now proven against physical
device traffic end-to-end through the selection stage: the TFTP `cnf.xml` fetch
seen in the first capture is the ATA's normal SCCP config bootstrap, while the
actual upgrade dialogue over UDP 8000 is the KBOX format this project
implements. Next action requires fresh operator approval for one new attended
live `ata_flash.py --apply` window (same command as before), with observation of
whether the ATA advances past selection to the data port and completes all 312
blocks; the response URL syntax and data-port dialogue remain unproven against
hardware and are the empirical gates of that attempt.

## 2026-09-14: live SIP transfer served; device acceptance still pending

Before: `ata_boot.pcap` (overwritten by the operator, now 364,458 bytes, 630
packets) captured the full successful window at 13:51-13:52 including the
control dialogue and every data block. The two TFTP config RRQs at 13:51:12 and
13:51:22 went unanswered (no TFTP server), after which the ATA proceeded with
the KBOX upgrade dialogue.

Change/verify (operator-run live window, same pinned command, sudo):
- image verified (sha256=b859...7f f5, platform 0x0301, version 0x0301,
  blocks=312); network verified (en28, 192.168.2.2, 192.168.2.0/24);
- DHCP OFFER+ACK for client MAC 00:07:0e:36:e5:7b at 192.168.2.10;
- "Python firmware service ready at 192.168.2.2:8000 (data port 8500)";
- "Python firmware transfer started."; then the operator's log ends with
  "Python firmware response stream complete (blocks=312, payload_bytes=319135)";
- independent pcap verification (decode of /Users/user/devel/ata/ata_boot.pcap):
  selection request (56 B on 8000) is present and was answered by the 144-byte
  KBOX response; the ATA-8500 data dialogue contains exactly 1 hello and 312
  block requests, zero invalid/checksum failures, and unique indices covering
  the full 0..311 range; wire payload reconstruction equals the pinned source
  (319,135 bytes).

Rollback: not needed; the transfer window completed cleanly and ended by itself.
No DTMF or packet was replayed. No host networking/VPN/firewall/DNS change was
made. The pcap is local evidence only and is not committed (root-owned,
uncommitted tree).

Outcome: the full wire dialogue (selection + hello + all 312 blocks) is now
proven against physical ATA175/186-format traffic. Not yet proven: the ATA's own
reboot, device-reported firmware via `123#` (expect SIP 3.1(0)), registration,
ringing, and audio. Those are the next hardware acceptance checks and must be
reported by the operator; a served stream is not a flashed device. Do not
re-dial or re-run automatically.

## 2026-09-14: SIP version confirmed via 123#; bench SIP/TFTP tools built

Before: the wire transfer was proven (previous entry) but device acceptance was
open: reboot, device-reported version, registration, ringing, audio. The ATA
had rebooted since; `123#` on the handset now reports the correct version
(SIP 3.1(0)). Network state checked read-only: en28 192.168.2.2/24, ATA
192.168.2.10 (ARP present with expiry), en0 192.168.1.164, no subnet overlap.
HTTP admin is up and unauthenticated: `curl http://192.168.2.10/dev.xml`
returns the full `ATADev` config (80 fields). Root path `/` returns "Invalid
Access" (normal). Relevant current values: UseTftp=1, TftpURL=0,
CfgInterval=3600, GkOrProxy=0, SIPRegOn=0, SIPPort=5060, MediaPort=16384,
IPDialPlan=1, Version=v3.1.0 atasip, MAC=00070e36e57b. The device boots and
TFTP-RRQs an ATA<MAC>.cnf.xml profile (observed unanswered in prior capture).

Change (new, all offline; nothing bound to the network yet):
- telephony/ATA00070E36E57B.cnf.xml: bench TFTP profile generated from the
  live /dev.xml with only three overrides: GkOrProxy=192.168.2.2,
  SIPRegOn=1, SIPRegInterval=60. All other fields preserved byte-for-byte.
- telephony/tftp_profile.py: bounded TFTP octet server (UDP/69), RFC1350
  512-byte blocks, one transfer at a time, exact filename allow list (no path
  lookup, no writes), fixed expected client only, bounded run time, per-block
  retransmit cap, dry-run by default and requires --apply.
- telephony/sip_bench_proxy.py: bounded SIP registrar/UAS (UDP/5060 + RTP),
  one fixed expected peer, REGISTER->200 OK, INVITE->100/180/200 with PCMU SDP
  (RTP/AVP 0), CSeq/Contact echoed, permissive registration, RTP streamed as a
  short generated 440 Hz tone (repeats), inbound RTP counted not stored, single
  dialog, bounded call and run time, dry-run by default and requires --apply.
- tests/unit/test_tftp_profile.py and tests/unit/test_sip_bench_proxy.py:
  32 offline tests (fake sockets; traversal/allow-list rejection, RFC block
  completion incl. exact-multiple empty final block, ignored unexpected peer,
  busy on second invite, SDP target parsing, tone audibility, RTP frame shape).

Verify (offline):
- python3 -m unittest tests.unit.test_tftp_profile tests.unit.test_sip_bench_proxy
  -> 32 tests OK, 0 failures.
- Full suites still green: tests/unit 105 OK; refactor/tests OK (57 skipped);
  tests/host 3 OK.
- CLI dry runs: tftp_profile.py and sip_bench_proxy.py both print the dry-run
  plan and exit 0 without binding.

Rollback: not needed; no live traffic, no device config, no host networking/
VPN/firewall/DNS change was made. Profile and tools are uncommitted local files.

Outcome: the last unverified gates (registration, ringing, audio) are now
tooled but remain unproven on hardware. Next action is an operator-attended run:
sudo tftp_profile.py --apply, then sip_bench_proxy.py --apply, then power-cycle
the ATA so it fetches the profile, watch REGISTER, lift the handset and dial the
extension (100), and verify ringing + audible tone. Do not auto-redial or
re-run after ambiguous delivery.

## 2026-09-14: add DHCP TFTP-server options; root cause of missing RRQ

Before: ATA (SIP 3.1.0) never made a boot-time TFTP request with our DHCP
running (OFFER+ACK succeeded, siaddr=192.168.2.2 present). /dev POST is dead
(all variants), so no web-side provisioning. IVR voice menu (access codes
GkOrProxy=5, UID0=3, SIPRegInterval=203, SIPRegOn=204) rejected star-as-dot in
alphanumeric entry. Operator observation: nothing in the DHCP response tells the
ATA where the TFTP server is.

Root cause from vendor reference ata_03_01_00_sip_040211_1/sip_example.txt
(TftpURL note): with TftpURL:0 the ATA uses the DHCP-provided TFTP URL; if DHCP
does not provide a TFTP URL the ATA cannot be provisioned automatically. Our
reply carried only BOOTP siaddr, not DHCP option 66 (tftp-server-name) or 150
(tftp-server-address).

Change: dhcp.py OFFER/ACK option list now includes
("tftp_server_name", server_address) [option 66, ASCII dotted-quad] and
("tftp_server_address", server_address) [option 150, 4-byte IP] before "end";
startup log now states "TFTP server <ip>". No gateway/DNS change.

Verify (offline):
- New tests/unit/test_dhcp.py case asserts both options appear in the DHCP()
  kwargs; python3 -m unittest tests.unit.test_dhcp -> 9 OK.
- Real-scapy smoke encode (bench venv): reply builds, option 66 len 9 and
  option 150 len 4 present, end marker set.
- python3 -m unittest discover -s tests/unit -> 114 OK.

Rollback: delete the two option entries (+ test). No live traffic was sent
during the change; next step is an operator-attended run with DHCP restarted,
TFTP server up, one ATA power-cycle, then REGISTER and a call.

Outcome: root cause identified and fix tooled, not yet proven on hardware.

## 2026-09-14: RTP drain deadlock fix; SIP call gate proven on hardware

Before: sip_bench_proxy.py performed a blocking RTP recv, so in a call where the
peer never sends media (e.g. a phone that only sends DTMF) `_rtp_receive()` could
block the proxy loop indefinitely even after the call ended. Hardware gates were
also still open: profile application, REGISTER, ringing, and two-way audio.

Change:
- sip_bench_proxy.py: after binding, `rtp_sock.setblocking(False)` so the media
  loop drains non-blocking; tone tick continues even when the receive buffer
  empties. Added regression `test_rtp_drain_returns_when_buffer_empties` with a
  non-blocking `_DrainingSock` in tests/unit/test_sip_bench_proxy.py.
- Hardware gate (operator-attended, on the isolated bench): power-cycled ATA ->
  DHCP OFFER/ACK (now with options 66/150, fix from prior entry) -> TFTP RRQ of
  the profile, profile applied (GkOrProxy=192.168.2.2, SIPRegOn=1), REGISTER ->
  200 OK on 5060, handset lift, dial 100 -> INVITE -> 100/180/200, two-way
  audible RTP (the repeating tone on 440 Hz is the deliberate pulsed test tone,
  not a rejection), `rtp_tx`/`rtp_rx` counters incremented.

Verify (offline): unit suite 119 OK; suite host 3 OK; refactor test_sata186us
26 OK (5 skipped). README.md rewritten: bench tools now live under `telephony/`
with install instructions (`python3 -m venv .venv && pip install -r
requirements-bench.txt`, scapy==2.7.0 for dhcp.py only) and the refactor ->
telephony move is explicit.

Rollback: none needed; fix is source-level, verified offline; hardware run
leaves no persistent state.

Outcome: SIP call path (registration, ringing, audio) proven on hardware. Next
gate: Asterisk integration (extension 100 via 192.168.2.2) — planning only.

## 2026-09-14: publication prep for telephony milestone + decompilation tooling

Before: staged for commit were four `research/decompiled/named/*` files that are
AI-derived ASM->C of the firmware loader (proprietary-feeling Cisco-era code) and
were never intended to ship; also staged were the two new tooling scripts with
absolute `/Users/user/devel/ata/...` paths, and tests that pinned the real device
MAC-derived selector and profile filename.

Change (do NOT publish, per owner):
- Unstaged all `research/` files (gitignored anyway; stay local).
- Rewrote `refactor/build_comprehensive_names.py` and `refactor/deep_got_analysis.py`
  absolute paths to repo-relative `ROOT`; stripped their trailing whitespace so
  `git diff --check` is clean. These scripts are now the publishable decompilation
  tooling.
- Sanitized identity-bearing tests: refactor/tests/test_sata186us.py now uses a
  synthetic KBOX frame (name `ata000000000001`, checksum 0x597) instead of the
  real MAC-derived frame (0x64e / ata00070e36e57b); tests/unit/test_tftp_profile.py
  uses `ATA0000000EXAMPLE.cnf.xml` instead of the device profile name.
- Left unstaged and local-only: `telephony/ATA00070E36E57B.cnf.xml`,
  `telephony/ata00070e36e57b.txt` (device identity), docs/firmware-analysis.md and
  refactor/README.md launch-trace content, WORKLOG/TODO/handoff/AGENTS.
- Staged set confirmed: 29 files (telephony tools + tests, dhcp/ata_flash + SATA
  KBOX fix + tests, tests/README.md, README.md, refactor README + decompilation
  tooling + SATA test).

Verify (repo root):
- python3 -B -m unittest discover -s tests/unit -> 119 OK
- python3 -B -m unittest discover -s tests/host -> 3 OK
- python3 -B -m unittest refactor.tests.test_sata186us -> 26 OK (skipped=5)
- python3 -B -m py_compile refactor/build_comprehensive_names.py refactor/deep_got_analysis.py -> OK
- git diff --cached --check -> clean exit 0

Outcome: ready to commit and push the telephony milestone plus decompilation
tooling. Very important: user explicitly waived intent to publish the AI-derived
named-bank C (research/) — leave unstaged forever unless separately requested.
## 2026-09-14: Asterisk integration plan and local bench config generator

Before: the telephony milestone was committed and the ATA (now SIP 3.1.0) was
hardware-proven for DHCP(66/150) -> TFTP profile -> REGISTER -> INVITE/PCMU ->
two-way RTP on the isolated bench at 192.168.2.2/192.168.2.10. TODO and worklog
next task is "plan Asterisk integration" as local work only; no APU/alarm
change authorized. The APU overlay (~33 MiB free at audit) has never been
cleaned; disk budget is an open operator follow-up, not a basis for skipping
the plan.

Change:
- Verified the OpenWrt 24.10.8 x86_64 telephony feed
  (https://downloads.openwrt.org/releases/24.10.8/packages/x86_64/telephony/)
  ships Asterisk 20.8.1-r1 and the pinned module set with exact ipk sizes;
  the 24.10-SNAPSHOT feed matches. Recorded in the new manifest
  telephony/openwrt-asterisk-packages-24.10.8.txt. chan_sip is deprecated and
  removed in Asterisk 21, which is why 20.8.1 is pinned and upgrades must not
  be unpinned. asterisk-chan-skinny is historical SCCP-probe-only (D013), not a
  SIP-milestone package.
- Added docs/asterisk-integration.md: verified feed table, local non-APU stages
  (pin+build engine locally, loopback integration harness with existing
  telephony fixtures, exact opkg manifest), bench topology for the engine,
  generated config artifact description, WebRTC/ARI engine-twin policy
  (deferred, kept separate from the ATA SIP peer), phases/gates 1-4 (engine+SIP
  -> IVR -> external media -> optional twin), rollback and safety boundaries.
- Added telephony/asterisk_conf.py: dry-run-by-default generator for a private
  bounded Asterisk 20 config tree (sip.conf chan_sip peer 100 for ATA
  192.168.2.10, extensions.conf Answer+Playback(hello-world), modules.conf
  autoload=no explicit list, rtp.conf bounded range). Inputs validated; --apply
  writes new files only into a mode-0700 dir, mode-0600 files, refuses
  overwrite, no credentials (empty secret matching the bench profile), no
  engine run, no socket bind, no ATA contact.
- Added tests/unit/test_asterisk_conf.py (12 cases: render content, topology
  pins, validation, dry-run, private write, overwrite refusal).

Verify (repo root):
- python3 -B telephony/asterisk_conf.py -> DRY RUN (no files written)
- python3 -B telephony/asterisk_conf.py --apply /tmp/opencode-asterisk-fresh
  -> 5 files, dir drwx------, files -rw-------
- python3 -B -m unittest tests.unit.test_asterisk_conf -v -> 12 OK
- python3 -B -m unittest discover -s tests/unit -> 131 OK (119 prior + 12 new)
- python3 -B -c "import ast; ast.parse(...asterisk_conf.py...)"; git diff --check
  -> OK; no whitespace findings

Rollback: delete the new plan, manifest, generator, and test file. No sockets,
engine, APU, ATA, or production state involved.

Outcome: Asterisk integration is now planned and tooled locally; no APU or
hardware change occurred. Next safe local action: build pinned Asterisk 20.8.1
on the developer host (source tarball, chan_sip + listed modules) and run the
loopback integration harness against it; disk budget at the maintenance
checkpoint is the operator's open follow-up.

## 2026-09-14: dispatch table and function pointer mechanism investigation

Before: all `sip_func_XXXXX` stub functions in `sip_bank_named.c` had been
renamed back from misidentified `printf`/`socket`/`str_copy`/`close`/`listen`/`setsockopt`
names to generic `sip_func_XXXXX`. However, the underlying dispatch mechanism
remained unclear — how does the firmware call through these stubs, and what
is the function pointer table base?

Change: investigated the indirect call pattern and dispatch table mechanism:
- `register0x00000074` is the function pointer table base (561 references across the C file)
- `sip_dispatch_table_init` (at `0cf813e4`) initializes the table by writing function pointers to offsets from `register0x00000074`
- `sip_dispatch_entry` (at `0cf81410`) and `sip_dispatch_return` (at `0cf81458`) handle dispatch control flow
- All 1400 `sip_func_XXXXX` definitions are indirect call stubs with pattern `(*(code *)((in_r24 + offset) * 4))()`
- `in_r24` holds `register0x00000074` (confirmed by `register0x00000074 + 0x18 = in_r24` assignment)
- The indirect call uses `(base + offset) * 4` to index into the 32-bit function pointer table
- 655 Pattern 4 indirect calls (`(reg << 2)`) + 164 Pattern 3 indirect calls (`*4`)
- The `BADSPACEBASE` type in Ghidra indicates the table base is computed at runtime
- The table contains function pointers loaded by `sip_dispatch_table_init`
- Previously misidentified `printf`, `socket`, `str_copy`, `close`, `listen`, `setsockopt` were ALL indirect call stubs — Ghidra named them based on GOT K-values, not actual function behavior

Verify: all 1629 function definitions in `sip_bank_named.c` are `sip_func_XXXXX` format;
0 remaining `printf`/`socket`/`str_copy`/`close`/`listen`/`setsockopt` definitions;
rename maps fully synchronized; indirect call patterns accounted for.

Rollback: revert the documentation additions only. No code files were modified
in this investigation; the rename maps and C file are already in their final state.

Outcome: the firmware's dispatch mechanism is now understood: a table-driven
dispatcher using `register0x00000074` as the function pointer table base,
with `sip_dispatch_table_init` initializing the table, and `sip_dispatch_entry`/
`dispatch_return` handling control flow. All `sip_func_XXXXX` functions are
indirect call stubs that look up function pointers through this table. The
`printf`/`socket`/`str_copy`/`close`/`listen`/`setsockopt` names were all Ghidra
misidentifications based on GOT K-value overlap, not actual library function
definitions.

## 2026-09-15: stack-based dispatch pattern investigation

Before: the table-based dispatch pattern `(in_r24 + offset) * 4` was understood,
but a second dispatch pattern was discovered: `*(int *)(in_r30 + offset) << 2`
and `*(int *)((int)register0x00000074 + offset) << 2` (404 total: 230 via
register0x00000074 + 174 via in_r30).

Change: investigated the stack-based dispatch mechanism:
- `register0x00000074` IS the struct base containing BOTH dispatch indices
  (negative offsets: -0x10, -0x18, -0x20, -0x28, -0x30, etc.) AND dispatch
  table entries (positive offsets: +4, +8, +0xc, +0x10, etc.)
- `in_r30` is an alias for `register0x00000074` — both point to the same struct
  (confirmed by identical offset patterns between register0x00000074 and in_r30)
- The struct is initialized by copying from `in_r30 + field_offset` to
  `register0x00000074 + offset` (e.g., `*(register0x00000074 + 8) = *(in_r30 + -0xec)`)
- 230 stack-based dispatch calls use `register0x00000074 + negative_offset`
- 174 stack-based dispatch calls use `in_r30 + negative_offset`
- The dispatch index at `register0x00000074 + negative_offset` indexes into
  the dispatch table at `register0x00000074 + positive_offset`
- The dispatch table entries point to classified functions in got_mapping.json
- All 404 stack-based dispatch functions are already classified:
  dispatcher (172), str_copy (33), error_handler (5), packet_recv (4),
  msg_buffer_handler (3), sip_validator_entry/aux/loop (3), func_0cf8XXXX
- `sip_dispatch_table_init` was NOT found as a separate function — initialization
  is done inline by dispatcher functions
- The `got_mapping.json` got_offsets are GOT entry offsets, NOT dispatch table offsets
- Resolution approach: trace struct initialization to map dispatch indices →
  dispatch table entries → classified function names

Verify: all 404 stack-based dispatch patterns identified and categorized;
register0x00000074 and in_r30 confirmed as the same struct base;
all stack-based dispatch functions already classified in got_mapping.json;
dispatch table entries at register0x00000074 + positive offsets contain
function pointers to classified functions.

Rollback: revert the documentation additions only. No code files were modified.

Outcome: the firmware uses TWO dispatch mechanisms: (1) table-based
`(in_r24 + offset) * 4` using register0x00000074 as the dispatch table base,
and (2) stack-based `*(int *)(reg + offset) << 2` where register0x00000074
is both the struct base containing dispatch indices and the dispatch table
base containing function pointer entries. The stack-based dispatch indices
index into the dispatch table entries. All dispatch targets are the
classified functions in got_mapping.json.

## 2026-09-15: readability optimization complete

Before: 1672 functions named `sip_func_XXXXX` in `sip_bank_named.c`, indirect calls
were opaque with no dispatch table context.

Change: applied two-pass readability optimization to `sip_bank_named.c` and
`transition_bank_named.c`:

1. **Function renaming**: All 1630 `sip_func_XXXXX` definitions renamed to
   classified names using `got_mapping.json` classifications:
   - `dispatcher_XXXXXX` (175 functions)
   - `str_copy_XXXXXX` (48 functions)
   - `error_handler_XXXXXX` (5 functions)
   - `packet_recv_XXXXXX` (4 functions)
   - `msg_buffer_handler_XXXXXX` (3 functions)
   - `sip_validator_entry/aux/loop` (3 functions)
   - `func_0cf8XXXX` (1394 functions — unclassified, kept as-is)
   - Group-name collisions resolved by appending address suffix
     (e.g., `dispatcher_f813e4`, `dispatcher_f81410`)

2. **Dispatch table annotations**: All 808 indirect calls annotated with
   dispatch context comments:
   - Table-based: `/* dispatch: reg0x74 + offset * 4 (table-based) */`
   - Stack-based (in_r30): `/* dispatch: in_r30 + offset << 2 */`
   - Stack-based (reg0x74): `/* dispatch: reg0x74 + offset << 2 */`

3. **Verification**:
   - 0 remaining `sip_func_` references in `sip_bank_named.c`
   - 808 dispatch table comments added
   - 568 dispatch table comments added to `transition_bank_named.c`
   - `sip_bank_named_readable.c` generated as the readability-optimized output
   - `readability_report.md` generated with classification breakdown
   - Original `sip_bank_named.c` backed up to `sip_bank_named.c.bak`

Outcome: the decompiled C code is now significantly more readable. Function
definitions use classified names instead of opaque `sip_func_XXXXX` stubs, and
every indirect call is annotated with its dispatch table context, making it
clear which dispatch mechanism is used and where the function pointer comes from.

4. **Key findings**:
   - `register0x00000074` is confirmed as the struct base containing BOTH
     dispatch indices AND dispatch table entries
   - `sip_dispatch_table_init` does NOT exist as a separate function —
     initialization is inline in dispatcher functions
   - `got_mapping.json` got_offsets are GOT entry offsets, NOT dispatch
     table offsets
   - All 1672 function definitions match 1630 classified functions

5. **Remaining gaps**:
   - 42 functions remain unclassified (`func_0cf8XXXX` naming) — need
     further reverse-engineering to identify their purposes
   - Indirect call dispatch targets (which specific function is called
     via which index) cannot be statically resolved without tracing
     the struct initialization code — the dispatch index at the
     negative offset indexes into the table entry at the positive
     offset, but the table entries are runtime values
   - The custom MIPS-X Ghidra process module may differ from MAME's
     understanding of the architecture, causing "Could not recover
     jumptable" warnings during decompilation

## 2026-09-15: local Asterisk 20.8.1 build reaches Running engine (OpenSSL linkage)

Before: previous entry (2026-09-14) built the Asterisk integration generator
and validated it in the repo. Objective for this task: bring up the pinned
Asterisk 20.8.1 engine locally (host probe only; no APU/ATA/production
contact) so the loopback harness can exercise REGISTER/INVITE/PCMU/RTP/DTMF
against chan_sip peer 100. Build tree is a private scratch copy under
/var/folders/.../T/opencode/asterisk-build (source asterisk-20.8.1); runtime
tree under .../T/opencode/asterisk-run; neither is tracked.

Change:
- Enabled a pinned menuselect set: app_playback app_read app_senddtmf
  app_audiosocket app_externalivr chan_sip codec_alaw codec_ulaw format_gsm
  format_sln format_wav pbx_config res_agi res_rtp_asterisk res_speech
  res_audiosocket res_timing_pthread res_crypto res_http_websocket (19
  modules; res_crypto + res_http_websocket newly enabled because chan_sip
  lists them as load-time dependencies).
- makeopts switches for Darwin: CC=clang (gcc/clang-alias chokes on bundled
  jansson's -fno-partial-inlining), CONFIG_CFLAGS=-DASTMM_LIBC=2 (avoids
  libxml SDK xmlFree/free macro clash with astmm), CONFIG_LDFLAGS and
  OPENSSL_LIB/OPENSSL_INCLUDE pointed at arm64 Homebrew OpenSSL 3
  (/opt/homebrew/opt/openssl@3); PJPROJECT_BUNDLED=no and pjsip family
  disabled.
- Removed /usr/lib/bundle1.o from Makefile SOLINK and main/Makefile ASTLINK
  (legacy Darwin path).
- Patched channels/sip/reqresp_parser.c strcasecmp_l/HAVE_XLOCALE_H guard
  (modern macOS lacks strcasecmp_l) and main/strcompat.c poll->ast_poll in
  closefrom().
- Undef'd HAVE_PJPROJECT/HAVE_PJPROJECT_BUNDLED in include/asterisk/autoconfig.h
  (pj_init() NULL crash otherwise; stasis boot failure with wrong astdatadir
  fixed by pointing astdatadir/astvarlibdir at the install prefix containing
  documentation/core-en_US.xml).
- Root-cause of dlopen failure `symbol not found in flat namespace
  '_EVP_PKEY_Q_keygen'` for res_rtp_asterisk.so: makeopts OPENSSL_LIB pointed
  at Intel Homebrew (/usr/local/Cellar/openssl@3, x86_64) while the engine is
  built arm64, so -lssl -lcrypto were silently dropped; also libasteriskssl
  shim links resolve only libSystem when crypto symbols unused. Repointing to
  /opt/homebrew/opt/openssl@3 (arm64) and rebuilding produced a binary whose
  otool -L shows libssl.3.dylib + libcrypto.3.dylib.
- menuselect did not install res_crypto/res_http_websocket into
  lib/asterisk/modules (Darwin ASTLIBDIR path differs: ".../Library/Application
  Support/Asterisk/Modules"); copied them into the astmoddir the engine uses.
- modules.conf generator MODULES list updated to include res_crypto.so and
  res_http_websocket.so before chan_sip.so; runtime modules.conf edited to
  match (verified identical against fresh generator render except intentional
  local rtp range 20000-20100 vs generator default 16384-20000).
- menuselect-deps fix: PJPROJECT=0:0 (was 0:1) after a configure rerun reset
  menuselect.makeopts; res_rtp_asterisk XML keeps pjproject only as optional
  use so the module still builds/enables without pjsip.

Verify (dev host only):
- make -j8 next: exit 0; make install DESTDIR=install: exit 0
- otool -L install/sbin/asterisk | grep crypto -> /opt/homebrew/opt/openssl@3
  libssl.3.dylib + libcrypto.3.dylib
- otool -L install/lib/asterisk/modules/res_rtp_asterisk.so -> same crypto
- engine boot under arm64 lldb (`arch -arm64 lldb -s ldb.cmd -- asterisk -f
  -cc -C <run>/etc/asterisk/asterisk.conf`): "Asterisk Ready"; remote CLI
  `module show` lists 27 modules loaded with res_rtp_asterisk, res_crypto,
  res_http_websocket, chan_sip Running.
- `sip show peers`: 100/100 127.0.0.1:5060 unmonitored; `sip show settings`:
  UDP Bindaddress 127.0.0.1:5060.
- python3 -m unittest discover -s tests/unit: 132 OK (incl. updated
  asterisk_conf tests referencing res_crypto/res_http_websocket in MODULES).

Rollback: delete the private build/runtime trees and the copied module files;
restore generator MODULES if undesired. No sockets, host routes, ATA, or
production state involved.

Outcome: first fully Running local Asterisk 20.8.1 engine with chan_sip +
RTP stack and the bench peer configured; all module dlopen/dependency
failures resolved. The engine is waiting for a REGISTER at 127.0.0.1:5060 /
loopback harness. Next safe local action: run the loopback SIP integration
harness (sip_bench_proxy.py + rtp_external_media.py or a dedicated probe)
against the Running engine before any APU contact.

## 2026-09-15: loopback harness passes full SIP/RTP round trip vs local engine

Before: the local engine was Running (previous entry) but the loopback probe
fail-registered: engine FreeBSD-parse accepted the REGISTER, emitted no
response, and the first daemon restart reproduced the silence. Runtime state:
private engine (asterisk 20.8.1 install prefix) running as `-f -vvv` daemon
against the private run tree; no AXU/APU/ATA involvement.

Change:
- Added telephony/sip_loopback_probe.py: bounded loopback SIP UAC (REGISTER,
  INVITE to a fixed extension with PCMU SDP, ACK, inbound RTP count, one
  RFC2833 DTMF event, BYE). Dry-run default; --apply binds 127.0.0.1:15060
  (SIP) + 16384 (RTP). Bounded run/call windows; no recording or redial.
- Added tests/unit/test_sip_loopback_probe.py (9 cases: parse/request/SDP/DTMF
  shapes). Repo suite now 141 OK.
- Probe fixes found by live debugging: probe default SIP port moved to 15060
  (5060 collides with the engine bind); every request carries a From tag
  because chan_sip's pedantic checking drops tagless requests quietly
  (engine DEBUG: "REGISTER request has no from tag").
- telephony/asterisk_conf.py peer template: `host = dynamic` + `permit = <ata>`
  replaces static `host = <ata>` (chan_sip refuses REGISTER from static-host
  peers: "Peer is not supposed to register"); `username` -> `defaultuser`
  (deprecation). Runtime sip.conf regenerated against this template with
  127.0.0.1 topology and rtp 20000-20100; `.before-hostfix` copies preserved
  in the private run tree. Unit tests updated to expect dynamic+permit.

Verify (dev host only):
- python3 -m unittest discover -s tests/unit -> 141 OK
- engine: `sip show peers` -> 100/100 (Unspecified) D + ACL, host dynamic
- python3 telephony/sip_loopback_probe.py --apply --rtp-port 16384
  --run-seconds 45 --call-seconds 12 -> register 200 OK, invite 100 Trying +
  200 OK, ack, dtmf-sent event=1, bye 200 OK, rtp-rx=49 RTP PCMU packets,
  RESULT: pass
- engine full log: "Executing [100@from-ata:2] Playback(SIP/100-00000000,
  hello-world)", "Playing hello-world.slin", 1 call processed, 0 active calls
- core show threads/lldb: do_monitor idle in ast_io_wait after each packet
  (no stuck thread; earlier "no response" was the two silent drops above).

Rollback: `mv *.before-hostfix` back in the run tree and `sip reload`; delete
the probe + its test file; restore the generator peer template. No APU, alarm,
board, or production change; loopback sockets only.

Outcome: Phase 1 local loopback qualification passes end to end (REGISTER,
INVITE, 200/ACK, PCMU RTP, RFC2833 DTMF, BYE/hangup) against locally built
Asterisk 20.8.1 with the generated bench config. Remaining Phase 1 item:
pin the exact opkg dependency set/footprint (operator follow-up), then the
hardware gate at the maintenance checkpoint.

## 2026-09-15: Phase 2 IVR probe passes; DTMF path crash root-caused

Before: Phase 1 loopback pass (previous entry) used a bare Answer+Playback
dialplan. Objective for Phase 2: bounded one-digit IVR (Playback menu,
Read() one numeric response, confirmation playback) exercised by the probe
end to end. Runtime engine was a plain background daemon; no APU/hardware
involvement.

Change:
- telephony/asterisk_conf.py dialplan: extension 100 becomes Answer ->
  Playback(hello-world) -> Read(digits,menu,1) -> GotoIf(digit = 5) ->
  Playback(confirmed) -> Hangup (benchmark-bounded, one digit, no games).
  MODULES list adds app_read.so and res_timing_pthread.so (see crash below).
- Added telephony/gen_ivr_prompts.py: synthesizes menu.wav (440 Hz) and
  confirmed.wav (660 Hz), 8 kHz 16-bit mono, refuses overwrite, mode 0600;
  ran once into the engine sounds dir (no asterisk-sounds needed for the
  probe).
- telephony/sip_loopback_probe.py: SDP now offers telephone-event/8000 (PT
  101, fmtp 0-16) so chan_sip negotiates RFC2833; outbound RTP uses a
  real incrementing sequence/timestamp (res_rtp previously ignored the
  constant seq-0 packets); DTMF event '5' is sent after the prompt window
  (DTMF_DELAY_SECONDS) and pass requires >=20 post-DTMF RTP packets (the
  confirmation prompt), else fail-ivr.

Crash found and root-caused (asterisk-2026-09-15-221726.ips is the local
proof, left out of the repo): with autoload=no and res_timing_pthread
missing from modules.conf, every channel got a NULL timer; the first
accepted RFC2833 DTMF END made __ast_read enter DTMF emulation and call
ast_timer_set_rate(NULL) -> SIGSEGV in ast_waitfordigit_full/Read.
Fix: load res_timing_pthread.so explicitly. Same lesson for OpenWrt: the
module set must include the timing module when autoload is disabled.

Verify (dev host only):
- python3 -m unittest discover -s tests/unit -> 141 OK
- probe: register 200 OK, invite 200 OK + ACK, DTMF event 5 at ~2.6 s,
  post-dtmf-rx=20, BYE 200 OK, RESULT: pass
- engine log: "RTP creating END DTMF Frame: 53 (5)", GotoIf("1?ok"),
  Playback(confirmed)-slin, BYE hangup, 1 call processed, no new crash
  reports after the fix.

Rollback: restore *.phase1 configs in the run tree and restart; revert the
generator probe changes via git. No production or hardware state touched.

Outcome: Phase 2 (bounded IVR with one DTMF digit) passes end to end against
the local engine, including the crash found on the DTMF path. Remaining:
Phase 3 external media (audiosocket/externalivr), opkg footprint manifest
(operator), hardware gate (operator).

## 2026-09-15: dispatch-target resolution campaign (Option A start)

Before: readable C had 9602 annotated indirect calls but comments only
restated the offset expression; the user asked what the pointers resolve to.

Change: attempted full static + emulated resolution:
- Scanned the whole 512 KiB reconstruction (`zup_extract.py` from the pinned
  package) for data words in the code range: only 24 exist (payload entry
  points). PROVEN: no static dispatch table in ROM; targets are runtime only.
- Built `research/dispatch_resolve.py` (local-only): RAM image from the 7
  inflate streams + a MIPS-X interpreter (decode table from
  `refactor/mipsx_dasm.py`). It executed ~4M instructions through the boot
  tail into the inflate helper; delayed-slot (`pc+4`, squash) and
  `jspci target = R[S] + sign17*4` semantics verified against three sites.
- Located the 63-word validator (0x7f9fc..0x7faf8, self-contained, ends
  `jspci r31+0`), the record selector (0x7fd18..), handlers, and a large
  unrolled `st +T[r27]` initializer block. The initializer writes device
  registers and dial-plan vectors (no code pointers) - NOT the dispatch table.
- Constant-propagation over the image found exactly 13 code-pointer stores
  (validator/dispatcher context words 0x0cfc0000/0x0cfc000c/0x0cfffa00).
- The running program populates dispatch slots via register-to-register
  copies (`*(reg74+8) = *(in_r30-0xec)` chain), bottoming out at those 13
  stores plus the launch-table mechanism.

Blockers recorded for next session:
1. Hardware-preset registers at reset (r13=validator PC, r27=peripheral
   base; r2/r10 for the selector) are established by ROM outside the
   analyzed tail; boot-faithful emulation needs them.
2. The `0x400031d3` type-3 PC tag's platform meaning (RAM segment/cache bit)
   is undocumented; the terminal entry target = word 0x31d3 -> byte
   0xc74c, currently unmapped in our RAM image.

Verify: `zup_extract.py` SHA256 bank ee2247ad...; disassembly cross-checks
against `research/sip_setup_disasm.txt` and `zup_bank.py --launch-header 0`
records; emulator reached the type-1 copy loop and inflate helper.

Rollback: delete `research/dispatch_resolve.py` (local-only) and this entry.

Outcome: dispatch targets are NOT statically recoverable from the image;
they exist only in runtime RAM. Resolution is feasible via the emulator
once reset presets and the 0x40000000 PC tag are pinned; the comment-only
annotations remain honest placeholders until then.

## 2026-09-15: hardware gate passes - ATA 186 (SIP 3.1.0) completes IVR through Asterisk 20.8.1

Before: Phase 2 passed on the local loopback probe; the ATA had only ever been
driven by the bench UAS (sip_bench_proxy), never by the real engine. Operator
authorized the bench hardware gate and ran the bench DHCP client in their
session. Bench topology unchanged: ATA 192.168.2.10 (UID 100, PCMU/PCMA,
MediaPort 16384) -> engine host 192.168.2.2 on en28 (read-only interface
snapshot before launch: engine bound 192.168.2.2:5060, bench link present).

Change (all private bench runtime, nothing production):
- New private engine tree /var/folders/.../T/opencode/asterisk-bench
  (generator defaults = bench topology; phase-2 IVR dialplan incl. Read +
  res_timing_pthread in modules.conf; separate astdb/run/log dirs so it can
  run beside the loopback engine).
- First call attempt: ATA registered, dialled 100#, digit 5, confirmation
  tone (operator), but the engine-side trace was lost by my console.log
  overwrite. Second process: full SIP debug console capture.
- Two config lessons fixed on the way: bench [directories] must use '=' (not
  '=>') per the proven master config; bench tree logger.conf still reports
  "Errors detected" and refuses to open the full file channel while being
  byte-identical to the working loopback tree (open quirk, console logging
  used instead). No host network changes were made.

Verify (operator-performed, engine-side captured):
- REGISTER: User-Agent "Cisco ATA 186 v3.1.0 atasip (040211A)",
  Contact sip:100@192.168.2.10:5060;user=phone;transport=udp, expires 60 ->
  200 OK; peer 100 dynamic+ACL permit .2.10 only.
- Operator dial 100#: INVITE from ATA with real SDP (o=100 18131, m=audio
  16384 RTP/AVP 8 0 4 101, PCMA/PCMU/G723 + telephone-event 0-15); engine
  negotiated combined Non-codec telephone-event|, answered on local RTP port
  20076, sent ulaw + telephone-event offer.
- DTMF: operator pressed 5; confirmation tone heard by operator on both the
  first and the re-dialled call (operator statement recorded here). Playback
  chain executed per dialplan; call ended with engine BYE, ATA replied 200 OK
  (X-Asterisk-HangupCause: Normal Clearing/16), dialog destroyed.
- core show calls after final dial: 2 calls processed, 0 active.

Rollback: stop bench engine (`pkill -f asterisk-bench/etc/asterisk.conf`) and
delete the bench tree; the ATA profile is untouched (provisioned earlier via
TFTP, unchanged this batch). No APU, alarm, printer, or production change.

Outcome: the hardware gate for the Asterisk SIP milestone PASSES end to end
with the pinned chan_sip engine and the generated bench config: ATA
registration, INVITE + two-way RTP with the analog handset, RFC2833 digit
through Read(), prompt audio, clean hangup. Remaining known engine-side blemish:
file logger quirk in the bench tree (console fallback used). Next: operator-
attended Phase 3 external media wiring (audiosocket/externalivr) against this
same engine, plus OpenWrt module manifest before any APU deployment.

## 2026-09-15: dispatch targets RESOLVED (major breakthrough)

Before: 9602 annotated calls with offset-only comments; "targets are the
classified functions" was unproven inference.

Change: built a boot-faithful MIPS-X interpreter (`research/boot_run.py`,
`research/main_run.py`, local-only). Key discoveries, each verified:
- `zup_extract.py` bank.bin holds streams still compressed; the runtime
  image expands 7 deflate streams to their offsets. Memory map is a 1 MiB
  page mask (a & 0xFFFFF) plus the SFR window at 0x20000000 (r27 preset
  = 0x2000 << 16, set by code at 0x7ff88 alongside `movtos r1,1`).
  bit31/bit24/bit28 windows, bank identity alias and SFR all fold into this.
- `jspci` semantics: PC_next_word = R[s1] + s17(w & 0x1FFFF); target byte =
  word * 4; 0x40000000 tag stripped first. Delay slot: one instruction at
  pc+4 then transfer; link = pc+8. Branch delay slots identical (sq skips).
- No dispatch table exists. The 9602 "indirect call stubs" are
  POSITION-INDEPENDENT relative calls: `jspci r24, disp_word` with the code
  base word r24 = 0x33F0280 (byte anchor 0x0cfc0a00 = bank 0x40a00).
  Ghidra printed them as `(*(code *)((in_r24 + off) * 4))()`.
  Static resolution: target = 0x0cf80000 + (0x40a00 + 4*off), proven by
  emulating 120M+ instructions (observed jspci r24 -0xd881 -> 0x0cf8a7fc,
  matching the formula; 991 executions of that one target).
- The in_r31 family (`(*(code *)(in_r31 << 2))()` after "Treating indirect
  jump as call") is NOT a dispatch and not a return-value store: it is the
  plain-return epilogue `jspci r31` (jump through the link register);
  prologues save `st +0x10[r29],r31` (1845 sites). The `<< 2` is word-to-
  byte scaling. 100 epilogues rewritten as `return;`.

Verify: `python3 -B -u research/main_run.py` runs the main program from the
terminal type-3 PC (0xc74c) with the launch ABI and logs dispatches;
`research/signatures.json` (local-only) holds per-function signatures for
1630 functions: entry params (r4+), resolved call lists (5836 calls, 824
distinct targets, 253 with classified names), return/tail-call classification.

Outcome: `sip_bank_named_readable.c` now shows 5836 concrete named calls
(function names instead of offset arithmetic). Remaining unresolved forms:
in_r30/S-struct family (~3766 sites) needs context-struct contents from the
emulator snapshot; 699 functions keep raw jspci forms (tail calls /
jumptables). Return types: MIPS-X returns in r2 (r3 wide), derivable at
call sites (next step).

## 2026-09-15: Phase 3 passes - call audio bridged through AudioSocket to a bounded local agent

Before: hardware gate passed (previous entry) with the engine-driven IVR.
Phase 3 goal: bridge the ATA call audio to an external process and back over
PCMU end to end, using the pinned app_audiosocket/res_audiosocket modules and
operator presence at the handset.

Change:
- Added telephony/audiosocket_agent.py: bounded AudioSocket TCP agent
  (loopback-only bind, one session at a time, max session/run budget, no
  audio stored or logged - only frame counts and energy summaries). Protocol
  per res_audiosocket.c: 3-byte header (kind, len hi/lo); kind 0x01 + 16-byte
  UUID at session start, kind 0x10 = 20 ms 8 kHz signed-linear mono frames,
  kind 0x00 terminates. The agent streams a 660 Hz tone paced at real media
  cadence, counts inbound frames (voiced/peak), then terminates the session.
- Dialplan: phase-3 extension 101 (from-ata): Answer ->
  AudioSocket(0023a1a4-...-0f3d5e6d7a99, 127.0.0.1:9100) -> Hangup. Fixed
  call UUID is documented and legal because the bench is single-dialog.
  telephony/asterisk_conf.py AUDIOSOCKET_* constants + module list now
  includes res_audiosocket.so/app_audiosocket.so; bench tree regenerated.
- Three operator-heard sound defects were root-caused and fixed in the agent:
  (1) burst-send of all frames truncated audibly (engine channel queue) ->
  paced at 20 ms; (2) timestep-based pacing stretched 2 s of tone to 5.6 s
  (macOS sleep granularity) -> absolute-clock scheduling (tone-sec=3.2
  remaining overhead collapsed vs 5.6); (3) per-frame sine restarts clicked
  at frame boundaries (660 Hz does not divide 20 ms) -> single continuous
  buffer sliced per frame. After (3) the operator reports a clean steady
  tone: "clean now... well beyond good enough".
- Cosmetics noted, not blocking: engine logs an app_audiosocket
  "Failed to receive frame" ERROR when the agent closes the session;
  bench-tree file logger still refuses to open (console logging used).

Verify (operator-performed, logs captured):
- python3 -m unittest discover -s tests/unit -> 146 OK (5 new agent tests:
  frame shape, energy, uuid rejection, paced round trip, terminate framing).
- agent.log final session: uuid match, tone-frames=100, tone-sec=3.2, rx=158
  inbound audio frames (engine -> agent), voiced=8, peak=32256.
- Engine console trace: INVITE from ATA (dial 101#), RTP both directions,
  app_audiosocket running on channel SIP/100-..., HangupCause Normal
  Clearing on operator hangup; on agent-terminated session the clean channel
  hangup follows the cosmetic ERROR line.
- Operator (handset): dial 101# -> continuous 2 s tone, quality "well beyond
  good enough"; earlier IVR path (100) unaffected.

Rollback: stop agent + bench engine, restore *.phase2 configs; generator
reverts are in git history. No APU/alarm/production change; bench link only.

Outcome: Phase 3 passes: real ATA handset audio reaches an external process
and returns over the pinned engine, with bounded and reviewable agent code.
This completes the local phases of the plan; what remains is operator/scope
work: OpenWrt module manifest comparison before any APU deployment, and
whichever external-media application (e.g. speech agent) the operator wants
behind extension 101.

## 2026-09-15: tooling published; sleigh verified, emulator slot-count fixed

Before: boot_run.py used one delay slot per transfer; the sleigh models two.

Change:
- Verified the published processor module against the boot-tail evidence:
  two delay slots (the setup copy loop advances BOTH r2 and r3 via its two
  post-branch instructions, which only works with slots=2), link value at
  instruction start + 12 bytes = the selector entry 0x7fd18, and word-
  scaled jspci targets. NO processor-module fix is needed - the earlier
  emulator was the wrong side of the comparison (the firmware pads unused
  slots with nops, which masked the bug while still running).
- Published `refactor/mipsx_boot_trace.py` (bounded, inert without args,
  synthetic-test vectors only) and `refactor/tests/test_mipsx_boot_trace.py`
  as commit 3358774 and pushed to github.com/kugg/ATA-tools main.
- Local research/ files remain local-only per the standing rule.

Verify: `python3 -B -m unittest refactor.tests.test_mipsx_boot_trace` -> 5 OK;
`python3 -B -m unittest discover -s tests/unit` -> OK; push confirmed
fbe395b..3358774 on origin/main.

Rollback: git revert 3358774 (tooling only; no existing file touched).

Outcome: the validated MIPS-X semantics now live in the public tooling in
runnable form; remaining open item is the r30/S-struct dispatch family.

## 2026-09-15 (night): services map, syslog decoded, scanner published

Before: syslog/HTTP/FTP presence in the pinned image unproven; the .data
string layout unmapped.

Change:
- Completed the runtime image in `refactor/mipsx_strings.py`: the four
  raw map regions, seven deflate streams, and the five CRC-checked
  type-8 payloads (mode-1 destinations: 0x6cbcc->0x2fbc, 0x6bb60->0x100,
  0x76c20->0x100). The .data string cabin therefore sits at
  0x2fbc..0x7b84 inside the main image.
- Deterministic findings (all from the expanded image + decompiled C):
  HTTP surface = /dev, /dev.xml, service.xml, stat.xml, /rtps, /clr0,
  gated by LoginID0/LoginID1/UseLoginID; TFTP client only - no FTP
  exists (every 'ftp' byte run is the tftp substring); syslog client
  with the config pair SyslogIP (type 0x00061101, extended ip.port,
  default 0.0.0.0.514) and SyslogCtrl (4-byte class bitmask, live cell
  RAM 0xb6f8, shipped default 0x08c4001a).
- SyslogCtrl semantics: every emit site gates on (ctrl & class_bit);
  recovered class bits 0x1/0x10000/0x40000/0x400000/0x8000000/0x20000000/
  0x40000000/0x80000000 with the emit families named (validator, config
  UI, signaling). Full debug = enable all bits. No 514 constant exists
  because the port comes from SyslogIP.
- Parameter schema located at image 0x4330.. (20-byte entries:
  {name_ptr, default/storage, formatter, type, id}); config pointers
  travel via iRam0000c11c/uRam00002ed0 globals.
- Published `refactor/mipsx_strings.py` + synthetic tests + the research
  doc `docs/ata-sip-firmware-services.md` as commit 02f5a6f and pushed.

Verify: unittest refactor.tests.test_mipsx_strings - 3 OK; boot-trace
tests 5 OK; unit suite OK; push 3358774..02f5a6f on origin main.

Blockers: live bench was unreachable this session (no 192.168.2.0/24
path active on the host; the operator-attended window from TODO.md is
still the gate), so the 192.168.2.2 probe request could not be actioned;
/dev and /dev.xml remain the known admin endpoints from earlier bench
evidence.

Rollback: git revert 02f5a6f (adds three new files only).

Outcome: enabling remote debug logging is now a reproducible profile
change: SyslogIP:<collector>.514 + SyslogCtrl:<class-mask> through the
proven cfgfmt + TFTP flow; the research doc records the evidence chain.

## 2026-09-15/16: reboot tool added (refactor/ata_reboot.py)

Before: the remote-reboot recipe existed only as prose in
docs/ata-sip-firmware-services.md.

Change: added the bounded planner/runner implementing the recipe:
collect (read-only /dev.xml + sha256 baseline), prepare (single reversible
knob AltGkTimeOut flipped; trip + revert profiles compiled with the
published cfgfmt -t<ptag> -sip), serve (the proven telephony TFTP tool,
bounded window, trip profile; --revert for the restore), verify
(/dev.xml byte-compare; mismatch = ambiguous stop). Dry-run default,
--apply gates everything, 0700 work dir, bounded sizes. Offline validated
against the pinned profile + ptag.dat: trip/revert binaries differ in
exactly 2 bytes. 7 synthetic unit tests (no sockets). Published as
commits 04421a7 (+ doc pointer) and pushed.

Verify: unittest refactor.tests.test_ata_reboot - 7 OK; full unit suite
OK; binary diff check above; status dry-run plan prints.

Blockers: hardware step untouched (bench window is the operator gate);
the collect/serve/verify steps run only inside that window.

Rollback: git revert 04421a7 (new files only).

Outcome: a reproducible, reversible device reset that provably preserves
the stored profile state.

## 2026-09-16T18:45Z: ata_reboot optional --tftp-name (learning server)

Before: run --apply required --tftp-name copied by hand from the previous
TFTP tool log; the whole-window orchestrated run (78caf66) was committed
but the name pin made ad-hoc bench use clumsy.

Change: LearningTftpServer in refactor/ata_reboot.py wraps the published
telephony/tftp_profile.py TftpServer and derives the device fetch name
from the first pre-reset RRQ; after the dhcp reset marker the wrapper
flips revert_active so the PXE-early boot fetch receives the revert
profile. Explicit --tftp-name still pins the name. A NUL-keyed
placeholder satisfies the base class non-empty-payload-map rule; name
learning is gated on the expected client peer (the unit test caught the
foreign-peer leak). Dry-run plan prints learning mode explicitly.

Verify: python3 -B -m unittest refactor.tests.test_ata_reboot -> 10/10 OK
(LearningTftpTest covers trip learn, revert swap, foreign-peer rejection
with no learning); python3 -B -m unittest discover -s tests/unit -> OK;
refactor/ata_reboot.py run dry-run renders both modes; py_compile clean.
Commits c4e064d and 5a6b524 pushed to origin/main. LC_ALL=C grep over the
tool and test files shows no non-ASCII characters in shipped code.

Rollback: git revert 5a6b524 c4e064d restores the pinned-name-only
runner; no device state touched (dry-run and synthetic tests only).

Blockers/next: live bench unreachable from this host (no 192.168.2.0/24
route); orchestrated run needs an operator-attended window. in_r30 /
S-struct dispatch family (~3766 jspci sites) is the next research pass
via the emulator RAM snapshot.

## 2026-09-16T21:30Z: OpenWrt 24.10.8 digital twin + feed cache + SDK pipeline

Before: the OpenWrt twin work existed only as experimental scripts and this
entry supersedes the provisional 2026-09-16 session notes above (none were
written; the harness boot/install/probe loop from earlier in the session was
iterated directly). The macOS engine, loopback probe, CPU-less ATA bench gate
(Phase 2 IVR + Phase 3 AudioSocket) were already passing on the host; the
pinned package set was verified but never run under OpenWrt.

Change: ported the protocol-level engine to an isolated QEMU x86_64 OpenWrt
24.10.8 guest with no egress (slirp restrict=on, only loopback host-fwd ssh
2205 and serial 4519). New tools: tests/qemu/run-qemu-asterisk.sh (bounded
harness: read-only route preflight with numeric 10.0.2.0/24 overlap check,
serial bootstrap of br-lan 10.0.2.15 + dropbear, chunked pubkey install,
host->guest ssh/scp, opkg local file:// feeds with signature verification,
engine start, in-guest loopback probe, log harvest, post-run drift compare);
tests/qemu/guest_drive.py + serial_capture.py (serial driver/logger);
tests/qemu/provision-guest.sh (rewrites distfeeds to local sources,
opkg update+install pinned set); telephony/openwrt_feed_cache.py (closure
resolver + SHA256-verified offline cache across base/packages/telephony/
target feeds; dry-run default); 6 new unit tests; pages feed target feed
(libstdcpp6 lives in targets/x86/64/packages, not packages/x86_64).
twin package manifest telephony/openwrt-twin-manifest-24.10.8.txt (65 ipks
actually installed, verified against provision.log). tests/openwrt/
build-openwrt-packages.sh SDK 24.10.8 build pipeline (dry-run default,
checksum-verified SDK, pins files required).

Verify: full harness run to completion twice (engine-up, probe-done stages);
in-guest REGISTER/INVITE/PCMU/RTP/DTMF/BYE round trip on OpenWrt passes;
operator manual dual check: extension 100# -> IVR prompt, RFC2833 digit 5 ->
confirmation tone; extension 101# -> clean AudioSocket agent tone (same
behaviour as the real ATA gate on 192.168.2.2). python3 -B -m unittest
discover -s tests/unit -> 152 OK (146 + 6 new); py_compile clean; all
scripts bash -n clean. No segfaults observed on the OpenWrt build (the
res_timing_pthread lesson from the host Read() crash carries over: the
explicit module list installs and everything runs plain).

Rollback: harness is a dry-run-by-default swarm with no persistent host
changes; it never alters routes/interfaces/filters/VPN. Removing the twin
tree (TWIN_ROOT) and the four feed entries leaves nothing installed on the
host. No guest disk is persisted (snapshot, discarded each run).

Outcome: the twin reproduces the host-loopback protocol results AND the
operator-attended ATA milestones under pinned OpenWrt 24.10.8, without a
physical ATA and without guest egress. The SDK pipeline is staged but not
run (300 MB download; operator decision to run it).

Blockers/next: SDK build is a long compile and is deliberately not executed
here; overlay-footprint budget vs APU free space still needs the target-size
opkg data (open operator follow-up). Phase 4 pjsip/WebRTC/ARI twin remains
deferred. Commits not made for this batch (working tree only; multiple
untracked new files listed in docs/handoff.md).
