# WebRTC site (Phase 4 "wbrt") — call the office phone from a browser

Status: **DEPLOYED 2026-09-18 on the office APU, LAN + WireGuard.**
Internet exposure is NOT authorized/implemented. No auth/PIN by operator
decision (initial); TURN not deployed (not needed on LAN/WG; required before
internet exposure). See WORKLOG 2026-09-18g and the exposure gates below.

Access: `https://10.47.11.97/webrtc/` (WG) or `https://192.168.2.1/webrtc/`
(office LAN). Accept the self-signed cert; microphone requires the HTTPS
origin. WSS signaling: `wss://<host>:8089/ws` (pjsip transport-wss).

## Goal

A small static page served by the APU's uhttpd. A visitor clicks **Call**; the
browser sends a SIP INVITE over WebSocket (WSS) to Asterisk's pjsip transport;
Asterisk dials the office SPA0300 (chan_sip peer `100`). Two-way audio with
PCMU/PCMA (ulaw/alaw), which every browser supports.

```
browser (SIP.js) --WSS--> asterisk pjsip transport  :8089/ws
    INVITE sip:100@<domain>  ->  [from-webrtc]  ->  Dial(SIP/100,30)  ->  SPA rings
```

## Why pjsip (and why chan_sip cannot do this)

WebRTC requires SIP over WebSocket plus DTLS-SRTP. `chan_sip` has neither.
The ATA path stays on `chan_sip` (already working); the WebRTC path uses
`pjsip` in a separate context, so one cannot break the other — matching
`docs/architecture.md` ("the ATA SIP path and the WebRTC twin stay distinct").

## Contents

| Path | What it is |
| --- | --- |
| `site/` | the page: `index.html`, `app.js`, `style.css`, `config.js` |
| `asterisk/pjsip.conf.draft` | pjsip WSS transport + guest endpoint (draft, gated) |
| `asterisk/http.conf.draft` | Asterisk HTTP/TLS listener (WSS) (draft, gated) |
| `asterisk/extensions.conf.draft` | `[from-webrtc]` context: call rings the phone |
| `vendor/fetch-sipjs.sh` | pinned SIP.js fetch (SHA required, dry-run default) |
| `../../tests/apu2/apu2-deploy-webrtc-site.sh` | bounded site deploy to the APU |

## Prerequisites (NOT met yet)

1. **Packages** (closure delta, staged from the pinned feed, never device egress):
   `asterisk-pjsip`, `asterisk-res-srtp`, `libsrtp`, `libpjproject`
   (`asterisk-res-http-websocket` is already installed).
2. **TLS cert + key** for the WSS listener (`/etc/asterisk/keys/webrtc.crt|key`).
   Self-signed is fine for the LAN draft; browsers will warn.
3. **Secure context**: browsers only expose the microphone over HTTPS (or
   localhost). The page must be served over HTTPS even on the LAN — uhttpd
   already listens on `192.168.2.1:443` (self-signed cert for now).
4. **Vendored SIP.js** (no CDN dependency at runtime; pinned + SHA-verified).
5. Reviewed Asterisk config application, attended, with rollback — the drafts
   are deliberately *not* applied by the site deploy script.

## Deploy (draft, LAN only)

```
# 1) vendor the browser library (review artifact first, then pass its SHA256)
webrtc/vendor/fetch-sipjs.sh --sha256 <sha256> --apply

# 2) stage the site onto the APU (dry-run first; --apply is operator-attended)
tests/apu2/apu2-deploy-webrtc-site.sh            # dry-run
tests/apu2/apu2-deploy-webrtc-site.sh --apply    # writes /www/webrtc/ only

# 3) engine configs (gated; requires packages + certs from Prerequisites)
#    apply asterisk/*.draft per the runbook, restart asterisk, verify /ws listens

# 4) open https://192.168.2.1/webrtc/ (accept self-signed), click Call
```

## Internet exposure gates (LATER, separate approval)

- **TLS / reverse proxy**: terminate real TLS for both the page and `/ws`
  (nginx/haproxy; uhttpd has no WebSocket proxy). Direct WSS exposure needs a
  real cert + firewall review.
- **Media NAT**: office is behind NAT; internet callers need TURN (e.g. coturn)
  and/or RTP port-forwards plus `external_media_address`; test ICE for
  symmetric-NAT clients.
- **Auth/abuse**: guest INVITE without auth is a LAN-draft convenience only.
  Internet needs a PIN/registration gate, call-duration and concurrency caps,
  rate limiting, and bounded logging. No anonymous firewall-rule appends.
- **Isolation**: the pjsip listener stays scoped away from the ATA/office LAN
  path; verify the ATA path after every engine change.
- **IPv4 + IPv6** policy both reviewed before exposure.

## Open questions (need operator decisions)

1. Should the web call ring the phone directly (draft default: `Dial(SIP/100)`)
   or enter the IVR first (`100`)?
2. Guest policy for exposure: PIN per call, per-day link, or accounts?
3. Public hostname + certificate plan (Let's Encrypt via the office WAN?).
4. TURN location (APU vs elsewhere) and bandwidth budget.
