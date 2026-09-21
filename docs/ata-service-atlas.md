# ATA web and TFTP service atlas

This atlas maps the pinned SIP 3.1.0 firmware's embedded web server and TFTP
provisioning client to exact runtime data, instructions, and handlers. It uses
the same launch-derived five-block runtime image as the syslog atlas.

```sh
python3 firmware/service_lookup.py web /stats
python3 firmware/service_lookup.py web --list
python3 firmware/service_lookup.py tftp "receive success"
python3 firmware/service_lookup.py tftp --list
```

Optional package verification checks all runtime strings, route-table slots,
configuration descriptors, and direct materialization instructions:

```sh
python3 firmware/service_lookup.py web --verify-package \
  ata_03_01_00_sip_040211_1/ATA030100SIP040211A.zup
```

## Web server

The completeness boundary is every path token accepted by
`maybe_http_route_parse@0x34238`, plus both method tokens recognized by
`maybe_http_request_parse@0x34584`. The router accepts one empty/default route,
nine directly materialized strings, and four entries in fixed table `0x4a88`.
Its final path returns `-1` for unknown routes.

| Route | Evidence | Result/handler | Operation | Confidence |
| --- | --- | --- | --- | --- |
| `/` | empty token | `-3` or `-9` -> `maybe_http_response_dispatch@0x33940` | default landing behavior | Inferred operation |
| `/resetcfwd` | table `0x4a88`, mask `0x1000` | table index 0 -> inline config dispatch | reset call-forwarding state | Inferred operation |
| `/dev.xml` | table `0x4a90`, mask `0x1001` | table index 1 -> inline config dispatch | render `ATADev` configuration XML | Exact |
| `/adv40c9` | table `0x4a98`, mask `0x1` | table index 2 -> inline config dispatch | alternate advanced configuration page | Inferred operation |
| `/dev` | table `0x4aa0`, mask `0x10` | table index 3 -> response dispatcher | configuration HTML GET/form POST | Exact |
| `/refresh` | `0x343a8 -> 0x4acc` | `-3` allowed, `-9` blocked | configuration refresh/resync, gated by `OpFlags & 0x100` | Exact |
| `/reset` | `0x343dc -> 0x4ad4` | `-3` allowed, `-9` blocked | write restart class 1 when `OpFlags & 0x200` is clear | Exact |
| `/stats` | `0x34410 -> 0x5556` | `-5` -> `sub_00032c7c` | device/network statistics HTML | Exact |
| `/rtps` | `0x34434 -> 0x555c` | `-7` -> `sub_000337b0` | per-line RTP statistics HTML | Exact |
| `/clr0` | `0x34458 -> 0x5561` | clear line 0 -> RTP handler | clear line-0 RTP counters | Exact |
| `/clr1` | `0x3447c -> 0x5566` | clear line 1 -> RTP handler | clear line-1 RTP counters | Exact |
| `/service` | `0x344ac -> 0x556b` | `-8` -> `sub_00032e70` | line-service state HTML | Exact |
| `/service.xml` | `0x344d0 -> 0x5573` | `-10` -> `sub_000335e4` | `ATAService` state XML | Exact |
| `/stat.xml` | `0x344f4 -> 0x557f` | `-11` -> `sub_00033314` | `ATAStats` device/network XML | Exact |

Only method tokens `get ` (`0x558c`, referenced at `0x34620`) and `post `
(`0x5591`, referenced at `0x34720`) are accepted. No `HEAD`, `PUT`, `DELETE`, or
`OPTIONS` route token is present. `/dev` is the proven POST path; static evidence
does not establish that every route accepts both methods.

The only status line in the complete loaded-runtime string inventory is
`HTTP/1.1 200 OK` at `0x515c`. Its response block also emits `Connection: close`,
`Cache-Control: no-store`, `Content-Length`, and `Content-Type: text/%s`.
Application/access errors are rendered under status 200; no 401/403/404/500
status-line string is present. XML and HTML subtype arguments are established at
`0x33a00 -> 0x51c7` and `0x339fc -> 0x51cb` respectively.

### Web control state

The live `OpFlags` word is `g_op_flags@0xa32c`. Initialization binds configuration
key `0x143` to this word. Both method paths test bit 7 (`0x80`) at `0x346b4` and
`0x34748`, selecting restricted handling; the GET branch rejects ordinary route
results while handling the special `-3` action path separately. The router tests
bit 8 (`0x100`) for `/refresh` at `0x343b0..0x343bc` and bit 9 (`0x200`) for
`/reset` at `0x343e4..0x343f0`. A set bit changes the route result from action
`-3` to blocked action `-9`.

`g_cfg_restart_requirement@0xaa58` is shared configuration state rather than a
web-only reset flag. `/reset` writes class 1 at `0x34400`. The parameter-update
path can write class 1 or class 2 according to descriptor flags, and profile
completion at `0x449a4` treats either nonzero class as restart-needed. The exact
difference between classes 1 and 2 remains unresolved.

## TFTP client

The ATA firmware is a **TFTP client, not a TFTP server**. It fetches profiles and
upgrade images. No WRQ, upload, listen, request-serving, or file-publication path
was found in the complete loaded-runtime literal/reference scan.

The TFTP completeness boundary includes every TFTP-specific initialized-data
literal, every direct materialization of those literals, the three parameter
descriptors, and the recovered transfer/timer/fallback handlers.

| Family | Entries | Exact anchors |
| --- | --- | --- |
| Configuration | `UseTftp`, `CfgInterval`, `TftpURL` | descriptors `0x4170`, `0x41c0`, `0x4350` |
| Status rendering | HTML and XML TFTP filename/address fields | `0x32d68 -> 0x4c91`, `0x33488 -> 0x4ec0` |
| Transfer result | upgrade failure, receive success, receive failure | `0x1e434`, `0x44b34`, `0x44bec` |
| Client progression | `applyProfile`, `nextTftp=`, restored-state trace, timer fallback | `0x44c90`, `0x44d18`, `0x44e90`, `0x44efc` |
| Profile validation | short, magic, header/length, overflow, checksum | `0x441f8`, `0x442f4`, `0x4438c`, `0x443fc`, `0x44484` |
| Apply consequences | modified, reboot-needed, waiting-to-reset, reset | `0x44828`, `0x4486c`, `0x44a60`, `0x44a98` |
| Main handlers | GET coordinator, scheduler, resume/rescheduler | `0x44ac4`, `0x44d7c`, `0x44e5c` |

The state trace changes the earlier interpretation of `0x44e5c`: it is not an
alternate-source selector. `g_use_tftp@0xbaf4` gates the function. During restored
startup, `g_restore_resume_pending@0xab70` causes one immediate GET and logs
`g_persisted_work_flags@0xb7b4` with `g_tftp_timer_remaining@0xa988`. Otherwise it
combines that saved remainder with `g_tftp_interval_ticks@0xb84c` and initialized
constant `0x57e40`, bounds the delay, logs `nextTftp %d`, and registers another
callback on `g_tftp_timer@0xb724`.

The timer remainder is explicitly persisted: save logic queries the timer,
subtracts a 200-unit margin, floors at zero, and writes it into retained runtime
state; restore logic loads it before TFTP resume. Scheduling sets bit 0 in the
shared persisted work flags, and profile parsing clears bit 0. Other bits in that
word have non-TFTP users, so the global is not labeled as TFTP-exclusive.

The apply-consequence rows are shared downstream profile-parser behavior: HTTP
configuration can reach related apply logic, so they are not labeled as
TFTP-exclusive. `AltTftpURL` exists in external parameter metadata but has no
corresponding literal in this loaded SIP runtime. No alternate-server selection
was found in the recovered TFTP handler; its exact representation and any
relationship to another component remain unresolved.

## Evidence boundary

Package verification proves bytes, table/descriptor words, and recorded direct
instructions. Handler purpose comes from bounded static control-flow and data
use. Inferred side-effect labels remain marked as such. This does not prove
runtime reachability, authentication behavior, delivery success, or hardware
effects. No device, network, VM, or modified firmware was used.
