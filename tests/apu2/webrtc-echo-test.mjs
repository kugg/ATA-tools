// webrtc-echo-test.mjs -- automated end-to-end WebRTC echo test against the APU.
//
// Places ONE echo call (extension 999) from a headless Chromium using fake media
// devices and reports the WebRTC transport state:
//   DTLS connected + inbound audio bytes > 0  =>  media path OK (echo audible).
//
// Requires playwright + a cached chromium. Example:
//   npm install --prefix /tmp/pw-test playwright@1.63.0
//   NODE_PATH=/tmp/pw-test/node_modules node tests/apu2/webrtc-echo-test.mjs
//
// Optional URL override:  node ... [https://host/webrtc/]
import { chromium } from "playwright";

const url = process.argv[2] || process.env.WEBRTC_URL || "https://10.47.11.97/webrtc/";

const browser = await chromium.launch({
  headless: true,
  args: [
    "--ignore-certificate-errors",
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required"
  ]
});
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  permissions: ["microphone"]
});
await context.addInitScript(() => {
  window.__pcs = [];
  const Orig = window.RTCPeerConnection;
  window.RTCPeerConnection = function (...args) {
    const pc = new Orig(...args);
    window.__pcs.push(pc);
    return pc;
  };
  window.RTCPeerConnection.prototype = Orig.prototype;
});

const page = await context.newPage();
const notes = [];
page.on("console", (m) => {
  const t = m.text();
  if (/DTLS|ICE|fail/i.test(t)) notes.push(t.slice(0, 160));
});

try {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("Available"),
    null,
    { timeout: 30000 }
  );
  console.log("page: registered (available)");

  await page.click("#echo");
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("Connected"),
    null,
    { timeout: 30000 }
  );
  console.log("page: echo call connected");

  await page.waitForTimeout(4000);

  const stats = await page.evaluate(async () => {
    const pcs = window.__pcs || [];
    const pc = pcs.filter((p) => p.connectionState === "connected").pop() || pcs[pcs.length - 1];
    if (!pc) return { error: "no RTCPeerConnection captured" };
    const out = { pcState: pc.connectionState, iceState: pc.iceConnectionState };
    const tr = pc.getTransceivers()[0];
    const dtls = tr && (tr.receiver?.transport || tr.sender?.transport);
    out.dtlsState = dtls ? dtls.state : undefined;
    const report = await pc.getStats();
    report.forEach((s) => {
      if (s.type === "inbound-rtp" && s.kind === "audio") {
        out.bytesReceived = s.bytesReceived;
        out.audioLevel = s.audioLevel;
      }
      if (s.type === "outbound-rtp" && s.kind === "audio") {
        out.bytesSent = s.bytesSent;
      }
    });
    return out;
  });
  console.log("STATS", JSON.stringify(stats));
  if (notes.length) console.log("console:", notes.slice(0, 3).join(" | "));

  await page.evaluate(() => document.querySelector("#hangup")?.click());
  await page.waitForTimeout(1500);

  const ok = stats.dtlsState === "connected" && (stats.bytesReceived || 0) > 0;
  console.log(ok ? "ECHO-PATH: OK (DTLS connected, audio received)" : "ECHO-PATH: FAIL");
  await browser.close();
  process.exit(ok ? 0 : 1);
} catch (err) {
  console.log("TEST-ERROR:", String(err).slice(0, 200));
  if (notes.length) console.log("console:", notes.slice(0, 3).join(" | "));
  await browser.close();
  process.exit(2);
}
