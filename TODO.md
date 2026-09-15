# Durable task queue

Last updated: 2026-09-14. Local work only; no APU/alarm deployment authorized here.

## Public release curation (2026-09-12)

- [x] Replace `README.md`, `refactor/README.md`, `refactor/FLASHING.md`, and
  `docs/ata-firmware-maintenance.md` with generic public guides; generalize
  `docs/firmware-analysis.md` paths and fix archived Cisco links.
- [x] Add BSD-3-Clause `LICENSE` per owner selection; clarify
  `THIRD_PARTY_NOTICES.md` and add trademark/non-affiliation boundary.
- [x] Define the exact 27-file public allowlist (18 Python) and scan it for bench
  addresses, device MACs, interfaces, credentials, private paths, and unsafe
  index content.
- [x] Verify the previously failing artifact-backed include-depth vector; run
  focused, full, artifact-backed, compile, manifest, loopback, inert-default,
  and `git diff --check` gates with passing results recorded in `WORKLOG.md`.
- [x] Clear the unsafe unborn-branch index without touching the worktree, stage
  only the explicit allowlist, review the actual staged diff, commit `032deb7`,
  add the remote, push `main`, and inspect `https://github.com/kugg/ATA-tools`.
  Remote tree holds exactly the 27 intended paths.
- [x] Publish decompilation tooling per owner selection (commit `7b27318`):
  `MIPSX_Ghidra_ATA186/`, Ghidra Java/Python decompile drivers, `analyze_*`/
  `build_name_map`/`decompile_ghidra`/`ghidra_decompile` scripts, `zup_extract`
  + tests, and `.gitignore` (now ignores all of `research/`). Rewrote the three
  analyze scripts' `/Users/user/devel/ata/research/...` defaults to
  repo-relative `ROOT`; no absolute paths, `.c`, results, TODO/WORKLOG/AGENTS,
  handoff, prserv/QEMU, or launch-trace content published.
- [ ] Decide the launch-trace work as a separate scope:
  `refactor/zup_launch_trace.c`, `refactor/tests/test_zup_launch_trace.py`, and
  their uncommitted edits in `docs/firmware-analysis.md` and
  `refactor/README.md` remain local-only by owner choice. If later published,
  the `test_source_exists`/`setUpClass` compile dependency on the `.c` must be
  resolved first so the public suite stays green.
- [ ] Keep physical ATA flash, reboot, SIP registration, ringing, and audio as
  unperformed hardware gates; keep modern Asterisk integration as future work.

## Current batch

- [x] Reverse-engineer the vintage support-tool formats with Ghidra/Docker-i386
  reference runs. The current `refactor/` utilities deliberately replace unsafe
  operational compatibility with bounded offline and policy-gated behavior; the
  vintage directory remains unmodified.
- [x] Harden `cfgfmt.py`, `prserv.py`, and `sata186us.py` with bounded input,
  private outputs/logs, dry-run defaults, and loopback/direct-bench restrictions.
- [x] Regenerate Oplane model `7bba4246-cd75-436d-a39f-580d7ab6b4db` for the final
  direct Python service plus retained relay/QEMU paths, obtain advice, and grade all
  70 cases against exact final source. The sanitized PASS/FAIL/N/A evidence and
  seven assessed states are in
  `reports/security-2026-09-12-direct-python-ata.md`.
- [x] At the operator's request, remove Oplane as a mandatory agent gate. The prior
  remote state updates remain unpersisted historical evidence; do not retry or use
  Oplane unless a future user explicitly requests it.
- [ ] Review the documented port limitations (obsolete `*Freq` float
  +-1 LSB, `kbox` bytes [8:12], structural-only `.sbin` RSA) before
  relying on those corners for any device workflow.

## ATA SIP maintenance

- [x] Select the preferred architecture: source-readable Python serves only the
  exact pinned image on fixed direct-bench addresses in one bounded foreground
  window. Retain dedicated Realtek USB passthrough, no management NIC, i386 QEMU,
  and the vintage server as an equivalence reference/live alternative. Do not retry
  the failed `vmnet-bridged` probe.
- [x] Qualify the software chain without hardware: the host simulator moved all 312
  target blocks through two Python loopback relays and actual i386
  `sata186us.linux` in QEMU. Every returned byte matched; no USB, ATA, DTMF, or
  flash was involved.
- [x] Inspect the local SIP and transition images offline; record hashes, headers,
  envelope validation, and the v1.34-only transition rule.
- [x] Keep the operator-requested optimized path separate in
  `optimized/ata-update.sh`: one readable, complete host launcher.
  Its QEMU executable/data, kernel, initrd, vintage server, and firmware are local
  under `optimized/` and verified together once with `SHA256SUMS`; large/vendor
  artifacts remain ignored by Git. Bare execution is inert; `--apply` validates the
  bundle and routes, builds a private disposable initramfs, and binds only host
  `192.168.2.2:8000/8500` through QEMU user networking to guest `10.0.2.15`. An
  instrumented loopback copy served all 312 blocks and 319,135 bytes from the local
  bundle; its directly tracked watchdog was killed and reaped explicitly, leaving no
  timer or QEMU process. No ATA was contacted.
- [ ] Reverse-engineer the pinned SIP `.zup` image offline and reproducibly: extract
  its complete component/file layout, identify original component versions and any
  available source provenance, document how the container is assembled, and determine
  whether integrity uses hashes, checksums, signatures, or a vendor signing chain.
  The bounded reconstructor, reversible rebuilder, and MIPS-X scanner reproduce both
  pinned banks, resident text, and three checked type-8 mode-0 programs. Resident SIP
  and
  transition `r24` anchors remain `0x00040a00` and `0x00040020`; a cross-image
  comparison gives relative candidate `transition_r23 - sip_r23 = -0x14c`, but
  no absolute outer `r23`. Type-8 is bounded raw-DEFLATE plus CRC-32. Mode 1 writes
  initialized data at its header field; mode 0 starts code at the type-9 data
  terminal. The resident dispatcher proves types 1/2 are word copy/zero-fill, type 4
  is a linked call, types 5/6/7/8/9/`0xa`/`0xb`/`0xc` load their established
  registers, and terminal type 3 jumps to its field unchanged. Type 7 encodes each
  program's `code_start + 0x40000` word-addressed `r23`; only the CPU meaning of type
  3's `0x40000000` PC tag and type `0xd`'s four-range reads remain unknown. A shared
  6504-byte MIPS-X helper plus 448-byte table/context block is byte-identical across
  packages and structurally identifies the standalone Mark Adler/gzip inflate-core
  lineage. Helper behavior independently identifies type-6 `r25` as its context,
  type-`0xc` `r19` as its Huffman-table arena cursor, and type-`0xb=0x7f800` `r29`
  as its initial stack. Final type-5 values are consumed directly by packed programs: all 97
  SIP-main and all 129 transition `r24` calls land in resident text, while SIP
  auxiliary has neither a final type 5 nor an `r24` call. Loaded programs initialize
  `r29=0x7ffe0`, not `0x70000`, and clear `r25`. Outer `r23`/`r25`, the type-3 tag,
  bytes following each type-8 CRC, exact inflate source
  release/compiler, physical chip evidence, and whether any nested payload is
  executable or ZSP400-owned remain open; see `docs/firmware-analysis.md`. Unchanged
  SIP and transition banks now rebuild to their exact original package hashes. A mapped
  raw or compressed component can be replaced offline; all unrelated encoded streams
  stay byte-identical, the inner map/checksum and compressed trailer are regenerated,
  and reconstruction must equal the requested bank. This is structural feasibility
  only: local zlib 1.2.12 does not reproduce most historical streams,
  cross-version/vintage compatibility and device authenticity are unproved, and
   modified packages remain prohibited on hardware. The current concurrent checkout
   passes 229 refactor tests, 67 unit tests, 3 host tests, and 83 focused firmware tests.
   Complete linear-disassembly coverage and private-output commands for all confirmed
   resident and packed MIPS-X programs are recorded in `docs/firmware-analysis.md`;
   generated proprietary instruction dumps remain outside Git. A bounded C11
   validator/dispatcher trace model (`refactor/zup_launch_trace.c`, local-only
   pending separate publication/license review) reproduces SIP main/auxiliary and
   transition tables with synthetic and pinned tests; outer `r23`/`r25`, the type-3
   tag, and type-`0xd` purpose remain open. The SIP web UI is now located as
   `printf`-style HTML templates in mode-1 data (bank `0x6cbcc` → span
   `0x2fbc..0x7b84`), shared with transition (`0x73ce2`/`0x73e42`); the bank has
   ~90 KiB of never-mapped `0xff` fill, a NUL-terminated filename slot at
   `0x2ea0c`, and dial-plan-like tail text, but still no archive or filesystem
   container. A local-only take-apart/put-back pipeline (`refactor/zup_extract.py`
   + `zup_rebuild.py`, pending separate publication/license review) decomposes a
   package into an editable directory (bank, manifest, expanded payloads),
   recomposes edited records/payloads in place with fail-closed fit checks, and
   verifies by re-expansion; an edited SIP image rebuilds and reconstructs its
   edited bank exactly.
  Continue exact component/source mapping, then
  map realistic extension points for additional diagnostics, authenticated remote
  management, and modern native protocols. Keep modified images off devices until a
  separate threat model, recovery design, hardware gate, and explicit maintenance
  approval cover authenticity, secure update, resource, and rollback consequences.
- [x] Assess Cisco bug `CSCsd44357`: it affects ATA186 CUCM/TFTP XML configuration
  delivery above 4 KiB on known-affected SCCP 3.2(3); Cisco evidence says the
  observed SCCP 3.2(4) source is fixed. It does not characterize the SIP target.
- [x] Record operator acceptance of the pinned local SIP 3.1.0 target without
  package-level provenance, a local SCCP rollback image, or vendor transition proof.
  These are historical uncertainties, not live execution gates.
- [x] Supersede the historical removal of the Python firmware server with a bounded
  direct implementation in `refactor/sata186us.py`. It validates the exact target
  before binding, serves immutable in-memory bytes, restricts the fixed peer and
  per-channel tuples, and enforces independent accepted/rejected request ceilings.
  It is not a general firmware policy engine or authenticated network service.
- [x] Correct the Oplane-follow-up qualification regression: one no-hardware run
  failed closed because buffered `read(4096)` waited past the ready marker. Replace
  it with fixed-size `os.read`, verify post-run network state on failures, and rerun
  the complete 312-block chain successfully.
- [x] Apply the same bounded process-group and 2 MiB output discipline to QMP USB
  discovery, require the exact `usbhost` response ID, and fail on QMP errors rather
  than reporting an error as an empty device list.
- [x] Run the direct-service checkpoint gates: 186 refactor tests, 45 existing unit tests, 3 host
  tests, `py_compile`, direct exact-stream qualification, inert defaults, prior
  read-only QMP USB discovery, repeated actual-QEMU qualification, and residual
  process/listener checks all passed.
- [x] Replace opaque `socat` forwarding with a source-readable Python relay while
  retaining exactly two user-facing loopback UDP ports (`8000/8500`). The repeated
  actual-i386 run completed command 1/1 and data 313/313 request/response exchanges;
  exact byte totals and all 312 firmware blocks matched in three consecutive runs.
  Private payload-free stats and synthetic serial evidence are available to an agent.
- [x] Reject empty/oversized requests and responses, make diagnostic output private,
  exclusive, and no-follow, persist only static events in the untested live path,
  and remove owned generated qualification initrds after both success and failure.
- [x] Fix the first relay test's post-close diagnostics failure by caching the bound
  port before closing its socket; the corrected focused suite passed.
- [ ] Build the later SIP configuration-debug workflow around pinned Cisco tools in
  an isolated QEMU guest and equivalent Python `cfgfmt`/`prserv`/inspection tools.
  Keep offline analysis easy for a user and agent before any separately approved
  live configuration write.
- [x] Retain the earlier read-only request-capture evidence as diagnostics only.
  The latest capture received three exact-peer datagrams that failed the strict
  capture parser. Serving uses bounded legacy framing instead; the complete direct
  and vintage-server reference streams both pass without captured metadata.
- [ ] When the ATA is available, recheck read-only routes/NWI and the isolated
  adapter. For the preferred path, confirm the host already owns `192.168.2.2`, the
  ATA owns `192.168.2.10`, and both UDP ports are free, then launch one bounded
  `sata186us.py --apply` window. If the retained QEMU/USB alternative is selected,
  first use `--list-usb` to identify the unique current `0bda:8153` bus/address.
- [ ] Wait for the selected service's ready message, manually enter
  `100#192*168*2*2*8000#` once, observe server-side transfer status, and separately
  verify the ATA's reported firmware with `123#`. Do not automatically redial or
  replay after an ambiguous delivery.
- [ ] If a selected path uses CUCM/TFTP configuration delivery, retain version-specific
  evidence and statically limit the initial XML configuration to 4096 bytes before
  a separately approved transfer test; do not inherit the SCCP 3.2(4) fix to SIP.

## Current batch

- [x] Inspect ATA, alarm API and APU read-only; distinguish observations from plans.
- [x] Create repository operating rules, architecture, assumptions and task records.
- [x] Redact printer worklog credential; record recovery of accidental history edit.
- [x] Reconcile printer runbook with the live audit and ownership boundaries.
- [x] Implement opt-in DHCP-resilient printer lifecycle locally.
- [x] Independently ran 25 printer lifecycle/watchdog tests, 57 printer unit tests,
  and 6 ATA offline tests successfully after hardening.
- [x] Initialize this Git repository and verify ignored secret/runtime files.
- [x] Independently review and rerun printer and bench unit checks.
- [x] Threat-model actual local security-relevant diffs; assess all 40 cases.
- [x] Finalize sanitized results and handoff; no commit without request.
- [x] Add fail-closed local recovery for one verified interrupted printer snapshot
  temporary, plus static QEMU route/egress safety hardening; no QEMU launch.
- [x] Build and test the bounded no-WireGuard local ATA186 SCCP fixture.
- [x] Threat-model the fixture as model `0067aeb3-5c6e-4ea8-b348-1a49f821a617`;
  `OPLANE_REQ-00003471`, `OPLANE_REQ-00003472`, and `OPLANE_REQ-00003473` are
  source-control IMPLEMENTED, not deployment proof.
- [x] Add explicit, bounded host-loopback SCCP TCP, IAX2 mini-frame UDP and RTP/PCMU
  UDP qualification with deterministic synthetic PCMU data. This is not an engine,
  QEMU, ATA, captured-audio, or FFmpeg-runtime result.
- [x] User reported a factory reset of the ATA on the isolated bench. No firmware
  flash, engine connection, configuration export, credential handling or agent
  device action occurred; post-reset state is not yet observed.

## Next gates, in order

- [ ] Validate bounded safe temporary recovery under event pressure and actual
  stop/start/resource/recovery semantics; current evidence is local implementation
  and mocks only.
- [ ] Review lifecycle implementation on pinned OpenWrt 24.10.8 procd, not mocks.
- [ ] Review the local QEMU route-snapshot/overlap/egress hardening on a pinned
  OpenWrt 24.10.8 guest before any launch; static tests are not a VM acceptance.
- [ ] Obtain approval for any multi-guest socket backend; current rules permit
  user-mode networking only. Do not silently substitute a bridge.
- [ ] Run isolated QEMU delayed-DHCP, unchanged-renew, readdress, loss/recovery,
  restart, event-storm and abrupt-power-loss tests. Do not bypass confinement gate.
- [ ] Gate Avahi readiness and dual-stack discovery/firewall parity separately.
- [x] Threat-model the host IAX2/RTP/G.711/socket qualification diff and record
  per-case source and host-test evidence in
  `reports/security-2026-09-08-host-fixture.md`; this is not production proof.
- [ ] Pin and host-test Asterisk 20 with built-in `chan_skinny` against the current
  SCCP profile, then establish exact OpenWrt 24.10.8 packaging/module compatibility.
  The driver is deprecated/removed in Asterisk 21; do not treat the host probe as a
  deployment choice. `chan-sccp` v4.3.5 is a legacy Asterisk 18/19 fallback only.
- [x] Build the offline SCCP framing/registration/ringer fixture; it opens no socket.
- [ ] Validate the bounded SCCP/IAX2/RTP profile against the selected host engine,
  then port that exact profile through one isolated loopback-forwarded QEMU guest.
  No WireGuard is part of this first phone gate.
- [x] Build bounded synthetic IAX2 mini-frame and RTP/PCMU peers; full IAX2 signaling,
  PCMA, jitter handling, credentials, and engine behavior remain out of scope.
- [ ] Pin Chatterbox Git/library/model dependencies and local Python environment.
- [ ] Reproduce HTTP TTS contract locally; no writes or inference on alarm.
- [ ] Verify aggregate confinement and actual NoNewPrivs before a second workload.
- [ ] Define convergent release manifest, storage budget and recovery kit.
- [ ] Request maintenance checkpoint before any APU deployment or configuration.

## Explicitly unresolved

- [ ] Actual ATA port-1 registration/ring/audio remains unverified. The SIP
  firmware flash and wired 312-block transfer are accepted, and `123#` reports
  SIP 3.1(0) on hardware; registration, ringing, and audio are the open gates
  and must be reported by the operator, never inferred from a served stream.
- [ ] Observe only the isolated post-reset ATA firmware banner and ATA-side DHCP/IP
  state. The user-operated responder emitted an OFFER/ACK on `en28`; do not infer
  lease installation, defaults, or reachability, configure it, flash it, or connect
  it to the APU/shared LAN.
- [ ] Host fixtures have not yet interoperated with an external SIP engine (e.g.
  Asterisk); iAX2 peers remain out of scope.
- [x] SIP firmware 3.1(0) is flashed on this ATA and device-confirmed (`123#` on
  the handset). The bench SIP registrar/UAS and TFTP profile service are built
  and unit-tested offline; profile application, registration, ringing, and
  audio on hardware remain the separately approved, operator-attended gate.
- [x] Document the isolated QEMU/USB procedure, fixed image hash, exact adapter/device
  identities, bounded stop behavior, and manual post-transfer verification.
- [ ] alarm wrapper checkout and chatterbox_tts version inaccessible to kugg.
- [ ] ASR/agent orchestrator and IAX2 peer are not yet selected.
- [ ] Determine whether exposed historical PSK is still active; any rotation is
  an administrator operation, not an automatic part of documentation redaction.
- [x] Define the explicitly requested initial-commit scope: exclude the user-supplied
  Cisco artifact directory in `.gitignore` and include only project source, tests,
  documentation, and sanitized reports. Historical model state is nonblocking and
  must not be retried automatically. Review the actual diff and sanitized local
  evidence before any explicitly requested commit.

## SIP verification gate (2026-09-14)

- [x] Live firmware flash accepted: wire dialogue served (312 blocks, 319,135
  bytes, exactly 1 hello, 0 invalid), pcap independently verified, and the ATA
  reports SIP 3.1(0) via `123#`. Root cause of the first failed attempt
  (`int(tok, 0)` on leading-zero KBOX tokens) fixed and regression-tested.
- [x] Confirm the ATA HTTP admin over `/dev.xml` (unauthenticated) and use it as
  a read-only config snapshot and profile-application proof.
- [x] Build the bounded bench TFTP profile server (`telephony/tftp_profile.py`,
  RFC1350, allow-list filenames, fixed client, dry-run default) and the bounded
  SIP registrar/UAS (`telephony/sip_bench_proxy.py`, REGISTER/INVITE/RTP tone,
  dry-run default) plus 32 offline tests; suites green (
  unit 105 OK, refactor OK 57 skipped, host 3 OK).
- [x] Generate `telephony/ATA00070E36E57B.cnf.xml` from the live `/dev.xml`
  with only GkOrProxy=192.168.2.2, SIPRegOn=1, SIPRegInterval=60 changed.
- [ ] Operator-attended hardware gate: run the TFTP server with `--apply`
  (sudo), run the SIP proxy with `--apply`, power-cycle the ATA so it fetches
  the profile, confirm REGISTER on 5060 and `/dev.xml` reflects the profile,
  then lift the handset, dial extension 100, and verify ringing plus the
  audible repeating tone; ambiguity is a stop condition, not permission to
  redial or rerun.

## Published telephony milestone (2026-09-14)

- [x] Hardware gate fully closed: DHCP OFFER/ACK (options 66/150) -> TFTP RRQ +
  profile applied -> REGISTER 200 OK -> INVITE 100/180/200 with PCMU -> two-way
  audible RTP (pulsed 440 Hz tone, deliberate). All `telephony/` bench tools now
  command-proven on the isolated bench.
- [x] Fix RTP receive deadlock in `telephony/sip_bench_proxy.py` (`setblocking(False)`
  after bind) and add `_DrainingSock` regression test; unit suite 119 OK.
- [x] Rewrite README.md with installation instructions, telephony bench workflow,
  and roadmap; roadside: "Modern Asterisk integration is the next project."
- [x] Publish decompilation tooling: `refactor/build_comprehensive_names.py` and
  `refactor/deep_got_analysis.py`, paths repo-relative, whitespace clean.
- [x] Do NOT publish: `research/decompiled/named/*` (AI-derived ASM-to-C of the
  loader, proprietary-feeling; unstaged + gitignored, local-only forever unless
  separately requested) and `telephony/ata00070e36e57b.txt` /
  `telephony/ATA00070E36E57B.cnf.xml` (device identity; local-only).
- [x] Dispatch table investigation (2026-09-14): identified `register0x00000074`
  as function pointer table base (561 refs), `sip_dispatch_table_init` as
  initializer, `sip_dispatch_entry`/`sip_dispatch_return` as dispatch control.
  All `sip_func_XXXXX` definitions are indirect call stubs
  `(*(code *)((in_r24 + offset) * 4))()`. `printf`/`socket`/`str_copy`/`close`/
  `listen`/`setsockopt` were all misidentified Ghidra GOT K-value overlaps.
  Rename maps and C file fully corrected and synchronized.
- [x] Function identification (2026-09-14): applied `got_mapping.json` classifications
   to rename 217 functions — 175 dispatcher_XXXXXX, 34 str_copy_XXXXXX,
   5 error_handler_XXXXXX, 4 packet_recv_XXXXXX, 3 msg_buffer_handler_XXXXXX,
   3 validator functions. Updated sip_rename_map.json (1847 entries),
   rename_map.json (1847 entries), sip_bank_named.c (452 occurrences).
   All misidentified names resolved; 0 printf/socket/str_copy/FUN_ remain.
- [x] Stack-based dispatch resolution (2026-09-15): identified TWO dispatch patterns:
    table-based `(in_r24 + offset) * 4` (0 remaining in current C format) and
    stack-based `*(int *)(reg + offset) << 2` (404 total: 230 via register0x00000074 +
    174 via in_r30). `register0x00000074` IS the struct base containing both
    dispatch indices (negative offsets like -0x18, -0x20) and dispatch table entries
    (positive offsets like +8, +0xc). `in_r30` is an alias for `register0x00000074`
    — both point to the same struct. The struct is initialized by copying from
    `in_r30 + field_offset` to `register0x00000074 + offset`. All 404 stack-based
    dispatch functions are already classified in got_mapping.json. The dispatch
    targets are the classified functions: dispatcher (172), str_copy (33),
    error_handler (5), packet_recv (4), msg_buffer_handler (3),
    sip_validator_entry/aux/loop (3), and func_0cf8XXXX functions.
    Resolution approach: trace struct initialization to map dispatch indices →
    dispatch table entries → classified function names.
- [x] Readability optimization complete (2026-09-15): all 1630 `sip_func_XXXXX`
    functions renamed to classified names in `sip_bank_named.c` and
    `transition_bank_named.c`. All 808 indirect calls annotated with dispatch
    table comments. `sip_bank_named_readable.c` generated. `readability_report.md`
    generated. 0 remaining `sip_func_` references. Original `sip_bank_named.c`
    backed up to `sip_bank_named.c.bak`.
- [ ] Commit + push the 29-file staged set, then plan Asterisk integration.

## Asterisk integration (2026-09-14)

Local plan and tooling only; no APU/alarm/hardware change in this batch. Feed
pins verified against the 24.10.8 x86_64 telephony feed (Asterisk 20.8.1-r1,
module list with exact sizes in `telephony/openwrt-asterisk-packages-24.10.8.txt`);
plan in `docs/asterisk-integration.md`; dry-run config generator
`telephony/asterisk_conf.py` (+ 12 unit tests). `chan_sip` removed in Asterisk
21 means 20.8.1 stays pinned.

- [x] Build pinned Asterisk 20.8.1 on the developer host (source tarball;
  `chan_sip`, `res_rtp_asterisk`, `app_read`, `app_audiosocket`,
  `app_externalivr`, AGI, ulaw/alaw) as the non-APU host probe. DONE 2026-09-15:
  arm64 build under /var/folders/.../T/opencode/asterisk-build, all 27 modules
  Running; key fixes recorded in WORKLOG (arm64 OpenSSL 3 linkage, Darwin
  patches, res_crypto/res_http_websocket deps, pjproject use-ref drop).
- [x] Loopback integration harness: existing `telephony` fixtures
  (REGISTER/INVITE/PCMU/RTP/DTMF/hangup) against the local engine, bounded,
  no ATA. DONE 2026-09-15: `telephony/sip_loopback_probe.py` (+8 unit tests,
  141 total) passes full round trip vs local engine: REGISTER 200 OK, INVITE
  100/200 OK, ACK, 49 RTP PCMU packets, RFC2833 DTMF, BYE 200 OK; engine
  executed Answer+Playback(hello-world)+Hangup (1 call processed). Required
  generator change: peer `host=dynamic` + `permit=<ata>` (chan_sip rejects
  REGISTER from static-host peers), `defaultuser` instead of deprecated
  `username`, and probe messages need a From tag (pedantic checking).
- [ ] Resolve opkg dependency set (`opkg depends`) on pinned 24.10.8 and
  record the installed-footprint budget vs overlay free space (APU cleaning is
  an open operator follow-up).
- [ ] Hardware gate at maintenance checkpoint: ATA REGISTER to the engine on
  the isolated bench, dial 100, hear prompt/tone, two-way RTP.
- [x] Phase 2 IVR: DONE 2026-09-15 — bounded one-digit Read() IVR
  passes end to end (probe sends RFC2833 '5' after the prompt; engine
  GotoIf-digits=5 and streams the confirmation prompt). Prompts are
  synthesized locally (telephony/gen_ivr_prompts.py), so asterisk-sounds
  is not needed for calibration. First DTMF END also exposed a crash:
  with autoload=no, res_timing_pthread.so must be in the explicit module
  list or Read() segfaults in ast_timer_set_rate (NULL channel timer).
- [ ] Phase 3
  audiosocket/externalivr to a local agent adapter, PCMU end-to-end.
- [ ] Phase 4 (deferred): separate pjsip/WebRTC/ARI engine twin for remote
  clients; allowlisted and isolated from the ATA SIP peer.
