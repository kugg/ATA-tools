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

## Boundaries

- The atlas contains 3 context records and 14 transitions. It is an initial
  high-confidence lifecycle slice, not an exhaustive inventory of every SIP
  response, transfer, session-refresh, FXS, or RTP branch.
- Timer constants are reported as firmware internal units unless a conversion is
  directly established. In particular, `0xbb8` is not relabeled as seconds.
- Bench evidence separately proves REGISTER, INVITE, ACK, RTP, DTMF, and BYE on
  one isolated ATA. Static-only entries here do not inherit that hardware proof.
- Generated decompilation under `research/` remains local and is not required by
  the lookup or package verifier.
