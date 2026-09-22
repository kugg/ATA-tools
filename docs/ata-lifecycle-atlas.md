# ATA SIP lifecycle atlas

This atlas maps a bounded, package-verifiable subset of the ATA 3.1.0 SIP
registration and call-control lifecycle. It is static reverse-engineering
evidence, not a claim that every branch has been exercised on hardware.

Use the offline lookup without firmware:

```sh
python3 -B firmware/lifecycle_lookup.py "registration success"
python3 -B firmware/lifecycle_lookup.py timeout --machine call-teardown
python3 -B firmware/lifecycle_lookup.py --list --machine registration
```

When the pinned package is available, independently verify every message,
materialization, and recorded state, context, or timer instruction:

```sh
python3 -B firmware/lifecycle_lookup.py --verify-package \
  ata_03_01_00_sip_040211_1/ATA030100SIP040211A.zup
```

## Context model

The firmware does not use one global SIP enum. The atlas keeps these layers
separate:

| Layer | Evidence-backed representation |
|---|---|
| Call leg | Resident pointer table at `0xbefc`, selected by line-derived base plus leg index; first context word is the call-leg state |
| Registration | Per-line context: `+0x10` expected CSeq, `+0x1c` interval pointer, `+0x20` state, `+0xc23c` retry timer, `+0xc318` outstanding-work marker |
| Registration timer | Records at `0x2bc0`, stride `0x10c`; `+0x104` accepted interval and `+0x108` scheduled-work state |
| Packed call channels | Separate packed-main table at `0xbe98`, with two `0x6c` records inside each channel context; this is not the registration state |

The resident dispatchers use event arguments as well as parsed-message fields.
Numeric event and response-class values remain unnamed unless adjacent messages
or protocol fields prove their meaning.

## Registration states

Three adjacent values have stronger evidence than the rest:

| Value | Meaning | Evidence |
|---|---|---|
| `0x14` | registration attempt | removal success writes `0x14`; successful registration accepts this state |
| `0x15` | removal/unregister attempt | successful response logs `Rm Reg OK` only after comparing state to `0x15` |
| `0x16` | registered | successful registration logs `Reg OK`, writes `0x16`, and schedules the next refresh |

The response class `0x1e` is the interval-too-brief path: it reads parsed
`Min-Expires` at response offset `+0xbe8`, requires `1..3600`, updates the line
interval and timer record, and retries. The response handler also rejects a CSeq
mismatch before reaching state updates.

## Call paths

Direct resident message references bound the initial call atlas:

| Path | Evidence anchors |
|---|---|
| Outgoing INVITE failure | timeout `0x18d9c`, busy `0x19df4` |
| Answer/ACK | ACK `0x1a350`, ACK timeout `0x1a7d4` |
| Incoming ringing | ACK `0x1ac90` |
| Remote teardown | BYE/CANCEL `0x1ae5c` |
| Local teardown | response `0x1afa0`, timeout `0x1b000` |

The labels describe directly logged events and adjacent control flow. Where a
numeric call-leg state has not been uniquely tied to a protocol phase, the atlas
uses a descriptive state and leaves the numeric enum unresolved.

## Session refresh, transfer, media, and FXS additions

The atlas now has 3 contexts and 28 transitions. Fourteen transitions were added
across three new machines (`session-refresh`, `transfer`, `media`), each
package-verified against the pinned SIP package:

| Transition | Machine | Event | From -> To | Exact anchors |
|---|---|---|---|---|
| `session-refresh.incoming-refresh` | session-refresh | re-INVITE asks for refresh | established -> `0x11` | mat `0x16ff0`; save `0x17000`; store `0x17008` |
| `session-refresh.timeout-disconnect` | session-refresh | refresh timer expires | `0xa` -> `0x5` | compare `0x16858`; mat `0x1688c`; disconnect `0x16894`; store `0x1689c` |
| `session-refresh.restart-timer` | session-refresh | refresh accepted | refresh negotiated -> timer armed | mat `0x170b4` |
| `transfer.far-end-refer` | transfer | far end REFER | active call -> `+0x2a58 = 2` | store `0x1b51c`; mat `0x1b53c` |
| `transfer.consultation` | transfer | consultation transfer | active call -> context recorded | store `0x2be4c`; call `0x2be7c`; mat `0x2be84` |
| `transfer.blind` | transfer | blind transfer | active call -> `+0x924 = 1` | mat `0x2bee0`; store `0x2beec` |
| `transfer.redirect-or-xfer` | transfer | redirect/xfer response | proceeding -> fields cleared | clears `0x15eb0`/`0x15eb4`; store `0x15ec8`; mat `0x15ef8` |
| `failure.invite-failed` | outgoing-call | INVITE failure | `0x4` -> `0x1` | compare `0x162c4`; mat `0x162d4`; store `0x162e0` |
| `failure.hold-failed` | outgoing-call | hold failure | `0x9` -> hold not established | compare `0x1630c`; mat `0x16314`; call `0x16324` |
| `failure.retr-failed` | outgoing-call | retrieve failure | retrieve pending -> `0x7` | mat `0x1634c`; store `0x16358` |
| `media.start-rx` | media | RTP receive starts | negotiated -> Rx active | byte store `0x2af68`; mat `0x2af70`; word store `0x2afcc` |
| `media.start-resume` | media | media resume | `0x12` -> resumed | compare `0x2b220`; mat `0x2b28c` |
| `media.codec-mismatch-bye` | media | no matching codec on ACK | `0x7` -> `0x7` | mat `0x1a56c`; store `0x1a57c`; compare `0x1a5a0` |
| `fxs.hook-event` | media | FXS hook change | hook changed -> recorded | OFF `0x65014`; ON `0x6501c`; store `0x65020`; class `0x65024`; call `0x6502c` |

The FXS hook transition is the first **packed** entry. It uses the packed
runtime layout (payload offset `0x479bc`, runtime base `0xc74c`), selects the
`"OFF"`/`"ON"` string (`0x79f0`/`0x79f4`) for the channel context at `+0x10`,
and emits `[%d]%sHOOK` through the class-6 syslog path. The verifier checks the
packed instruction text and the packed message bytes for entries with
`"scope": "packed"`; resident entries continue to verify against the bank
image.

Call-leg offsets touched by these transitions (`+0x924`, `+0x24a0`, `+0x2a58`,
`+0x2834`, byte `+0x2899`) are derived only from repeated offset/width evidence
in the listed instruction checks; no struct fields are inferred from a single
access.

## Boundaries

- The atlas contains 3 context records and 28 transitions, covering
  registration, INVITE, ACK, teardown, session-refresh, transfer, media/RTP,
  failure, and one packed FXS hook event. It remains a bounded high-confidence
  slice, not an exhaustive inventory of every SIP branch or FXS state.
- Timer constants are reported as firmware internal units unless a conversion is
  directly established. In particular, `0xbb8` is not relabeled as seconds.
- Bench evidence separately proves REGISTER, INVITE, ACK, RTP, DTMF, and BYE on
  one isolated ATA. Static-only entries here do not inherit that hardware proof.
- Generated decompilation under `research/` remains local and is not required by
  the lookup or package verifier.
