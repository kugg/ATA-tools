# ATA 186 SIP 3.1.0 firmware — services map and syslog research

Status: decompilation-derived findings with execution-validated semantics.
Local evidence chain: `WORKLOG.md` (2026-09-15 entries), the emulator
`refactor/mipsx_boot_trace.py`, the scanner `refactor/mipsx_strings.py`.
Derived from the pinned image `ATA030100SIP040211A.zup` (bank sha256
`ee2247ad…`). No live-device probes were used for these conclusions; the
local bench was unreachable at research time (no route to 192.168.2.0/24;
the bench window is an operator-attended gate).

## Runtime image layout (validated)

| Region | Bank bytes | Content |
| --- | --- | --- |
| Main program text | `0x0a00..0x2ea0c` | stored-DEFLATE stream 2 output |
| Main program `.data` | `0x2fbc..0x7b84` | type-8 payload `0x6cbcc` (mode 1, dest field `0x2fbc`), CRC-checked |
| Network stack | RAM `0x100..0x26d0` | type-8 payload `0x6bb60` (mode 1, dest `0x100`); `udp.c`/`dhcp.c`/`tcp.c`/`xltcp` debug strings |
| Payload `0x76c20` | RAM `0x100..` | small mode-1 companion (0x590 bytes) |
| Boot tail | `0x7f400..0x80000` | reset stub, validator, record selector, handlers |

The 205 decompiled functions at `0x0cf87b84..0x0cf8c74c` are the secondary
(web/config) module; the parameter schema in its `.data` range is the
authoritative source for the config surface below.

## Services present in this image

Deterministic string inventory (`refactor/mipsx_strings.py`) over the two
string cabins:

1. **HTTP server** (device admin, plain text): responses
   `HTTP/1.1 200 OK` at image `0x515c`; pages/forms for `/dev`
   (configuration), `/dev` reload links, `/rtps` (RTP statistics),
   `/clr0` (reset line-0 counters); machine views `dev.xml`,
   `service.xml`, `stat.xml`. Web access control exists (`LoginID0`,
   `LoginID1`, `UseLoginID`) — the same knobs the live `/dev.xml`
   snapshot already shows on the bench device.
2. **TFTP client** (profile + firmware): `tftp(0x%08x,%s)`, `tftpGet`,
   `UseTftp`, `TftpURL`, `Rx TFTP file:%s ok/fail`, retry logic
   (`retryApplyProfile`, `nextTftp`). Confirmed: there is **no FTP
   server or client** — every `ftp` byte sequence in the image is the
   `tftp` substring. TFTP is UDP-only, direction = device fetches.
3. **Syslog client** (see below): remote UDP logging, config-gated.
4. **DHCP client, DNS SRV (`_sip._udp`), STUN strings, SIP, RTP** —
   transport-layer modules whose debug strings were cataloged but are out
   of scope here.

## Syslog: where it lives and how to enable it

Config surface (from the parameter table at image `0x4330..` as
20-byte entries: `{name_ptr, default/storage, formatter, type/flags, id}`):

| Parameter | Type descriptor | Meaning |
| --- | --- | --- |
| `SyslogIP` | `0x00061101` (6-byte extended IP) | `<collector_ip>.<udp_port>`; `0.0.0.0.514` = disabled |
| `SyslogCtrl` | `0x00041101` (4-byte mask) | per-subsystem debug bitmask; live value at RAM `0xb6f8`, default stored `0x08c4001a` |

The logging layer: every emit site evaluates
`(SyslogCtrl & class_bit) != 0` before formatting/sending; the class-bit
constants recovered so far (read from the `.data` image):

| Bit | Observed gating sites |
| --- | --- |
| `0x00000001` | DHCP/stack `i:`-family messages |
| `0x00010000` | validator-class sites (`0xcf9b6xx`) |
| `0x00040000` | a dispatcher family (`0xcf97fxx`) |
| `0x00400000` | validators (`0xcf94axx`) |
| `0x08000000` | call/signaling sites (`0xcfa71xx`, `0xcfac0xx`) |
| `0x20000000` | parse/route sites (`0xcfa1d88`, `0xcfa2168`) |
| `0x40000000` | config/UI module (`0xcfac06c`) |
| `0x80000000` | a further signaling class (`0xcfa71xx`) |

Formatting detail: messages render through the PRI-style format
`%s<%d>%s %s [%02d]:%s` (image `0x3a43` = payload offset `0xa87`).
The UDP port is taken from `SyslogIP`, which is why no `514` constant
exists in the code.

Cross-reference summary (deterministic, from the materialization scanner
plus the decompiled C): the parameter schema lives at image `0x4330..` as
20-byte entries keyed by name pointers (`SyslogIP` = `0x4882`,
`SyslogCtrl` = `0x4877`, `dev.xml` = `0x4ab4`); the live control value
`uRam0000b6f8` is consumed by the log-emit dispatchers
(`dispatcher_fa1d88` family, class masks `0x1888/0x1894/0x18d0`, ...) and
config-block handles travel through the `iRam0000c11c`/`uRam00002ed0`
pointer globals (2225 `uRam`/`iRam` references in the decompiled C).

### Enabling remote logging (bench procedure, no hardware writes here)

1. Edit the pinned text profile (`telephony/ata00070e36e57b.txt`):
   ```
   SyslogIP:<bench_collector_ip>.514
   SyslogCtrl:0xFFFFFFFF
   ```
   `0xFFFFFFFF` = every recovered class set; use the table above to
   narrow. Lower 16 bits control low-level/stack messages.
2. Compile with the existing tool: `cfgfmt.py profile.txt profile.bin`
   (output unencrypted unless `EncryptKeyEx` is set; the `-e`/`-X` keys
   are no-ops in this toolchain by design).
3. Serve it over the proven TFTP/pumpkin flow (`telephony/tftp_profile.py`
   with `--apply`) and let the device fetch on its config interval or a
   manual resync; the collector is any UDP/514 listener, e.g.
   `nc -ul 514 > syslog.txt`.
4. Verify on-device with `792#` (current config dump) and confirm the
   collector receives PRI lines. These are operator-attended hardware
   gates under the standing rules; nothing in this step writes to the
   device by itself.

### Debug-level access, decompilation-derived

`SyslogCtrl` gates exactly one class per bit (all gates are plain `AND`s —
no additional level threshold was found, so "debug level" == the set of
enabled classes, not a numeric verbosity). With every bit set, all
recovered emit sites — stack (`dhcp.c`, `udp.c`, `tcp.c` markers),
TFTP/profile, signaling/validator families — emit messages through the
single PRI-formatted path.

## Remote reboot paths (decompilation-derived)

The only device-triggered remote mechanism is the **profile-driven reset**:
the config pipeline strings sit in the main `.data`
(`cfgNeedReboot %d` @ image `0x609c`, `waiting to reset` @ `0x60b8`,
`reset` @ `0x60cd`, `applyProfile` @ `0x612a`), and the apply flow copies
the reboot flag through the dispatcher handle
(`iRam0000c11c + 8 := uRam0000b6f4`, `func_0cf81268`). Practical form:

0. **Keep the lease answer up for the whole window** (the blink
   constraint): after a profile-driven reset the ATA immediately
   re-DHCPs; without a live responder it drops off the bench.  Run
   `dhcp.py --apply --interface <if>` (options 66/150 point at the bench
   TFTP) FIRST, with a capture deadline spanning the reset; it offers one
   lease and exits after the device ACKs.  `refactor/ata_reboot.py dhcp`
   wraps it with the same dry-run/apply discipline.
1. Serve a modified profile via the proven TFTP flow; the device fetches
   it at `CfgInterval` (3600 s in the bench profile) or on the next resync,
   and resets itself when the applied profile reports `cfgNeedReboot`.
2. A firmware "upgrade" also ends in a reset, but its trigger (the
   `100#<ip>*...#<port>#` feature code) is keypad-driven, so it is not
   fully remote.
3. Non-reboot look-alikes, deliberately excluded: `/clr0` resets RTP
   counters only; the `/dev` page "[Click here to reload]" re-renders the
   page only; `>>> SIP Soft Reset >>>` resets the SIP stack state, not the
   device. No HTTP route or SIP message handler for a device reboot was
   found in the string inventory.

## Remote reboot without changing the effective profile

The device keeps its running configuration in flash; a fetched profile is
*applied into* it (merge/overwrite), it is not consumed once. Two copies
therefore always exist: the device's flash config (source of truth,
readable VERBATIM through the proven `/dev.xml` snapshot) and the bench
profile in this repo (`telephony/ata00070e36e57b.txt`), from which the
binary profile regenerates deterministically with `cfgfmt.py`. "Burning"
the profile is thus a recoverable, auditable operation, not data loss —
but the reboot trigger must still be an *effective* profile change
(`cfgNeedReboot` is computed by the apply flow; the flag write runs
through the dispatcher handle as shown above, so serving a byte-identical
profile is not expected to disturb anything — and is also not expected
to reboot).

Recommended remote-reboot recipe (operator-attended window):

1. Collect first: snapshot `/dev.xml` (proven read-only flow) and diff it
   against `telephony/ata00070e36e57b.txt` to confirm they agree.
2. Serve the profile with one deliberate, reversible no-op-for-service
   change (e.g. toggle `AltGkTimeOut` or re-emit `SyslogCtrl` with a then-
   revertable value) so `cfgNeedReboot` trips. Keep the collected copies
   as the rollback target.
3. After the reset (log line `reset` / device returns on the bench IP),
   serve the original profile again so the *next* `CfgInterval` fetch
   (3600 s) restores the exact stored state; alternatively re-serve
   immediately — the device applies on fetch, so the original is in place
   before the hour elapses.
4. The post-reset re-lease lands on the step-0 responder; the device then
   refetches its (restored) profile from options 66/150 at boot.
5. Verify by diffing the fresh `/dev.xml` snapshot against step 1.

The alternative is a power-cycle (no profile I/O at all); no HTTP route
or SIP handler for a bare reboot exists in the image.

The full sequence embodies one command: `refactor/ata_reboot.py run
--apply --interface <if> --tftp-name <fetch-name>` (published, dry-run
default, nine offline tests).  The device's boot-time profile fetch is
PXE-early, so the revert payload must already be served when the device
comes back — `run` starts ONE TFTP server for the whole window with the
trip payload, uses the lease answer (dhcp.py as a library) as the reset
marker, swaps the served payload to the revert profile at the ACK, and
then polls `/dev.xml` until it is byte-identical to the baseline
(collected in step 1 of the same command).  `<fetch-name>` is the
filename the device requests — copy it from the previous TFTP tool log.
The trip/revert binaries differ in exactly 2 bytes — the knob.

## Open items

- The `in_r30`-family indirect transfers (~3766 sites) still await
  context-struct resolution via the emulator snapshot.
- Return types for the 1630 decompiled functions are derivable from `r2`
  at call sites; not yet automated.
- Live confirmation of the syslog profile on the bench device is pending
  the operator-attended window (`TODO.md`, hardware gates).
