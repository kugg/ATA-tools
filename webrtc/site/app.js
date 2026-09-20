(() => {
  const cfg = window.WEBRTC_CONFIG || {};
  const $ = (id) => document.getElementById(id);
  const statusEl = $("status");
  const callBtn = $("call");
  const echoBtn = $("echo");
  const acceptBtn = $("accept");
  const rejectBtn = $("reject");
  const muteBtn = $("mute");
  const hangupBtn = $("hangup");
  const audioEl = $("remoteAudio");
  const hintEl = $("hint");

  let ua = null;
  let registerer = null;
  let session = null;
  let incoming = null;
  let muted = false;
  let audioCtx = null;
  let ringTimer = null;

  const setStatus = (text, kind) => {
    statusEl.textContent = text;
    statusEl.className = "status " + (kind || "idle");
  };

  if (!window.isSecureContext) {
    hintEl.textContent = "Microphone access needs HTTPS. Open this page over https://.";
  } else {
    hintEl.textContent = "This page is extension 180. The office dials 180# to ring it.";
  }

  function startRingback() {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") audioCtx.resume();
      const burst = () => {
        const t = audioCtx.currentTime;
        [440, 480].forEach((freq) => {
          const osc = audioCtx.createOscillator();
          const gain = audioCtx.createGain();
          osc.frequency.value = freq;
          gain.gain.setValueAtTime(0.0001, t);
          gain.gain.exponentialRampToValueAtTime(0.06, t + 0.03);
          gain.gain.setValueAtTime(0.06, t + 1.7);
          gain.gain.exponentialRampToValueAtTime(0.0001, t + 2.0);
          osc.connect(gain);
          gain.connect(audioCtx.destination);
          osc.start(t);
          osc.stop(t + 2.05);
        });
      };
      burst();
      ringTimer = setInterval(burst, 6000);
    } catch (e) { /* ringback is best-effort */ }
  }

  function stopRingback() {
    if (ringTimer) {
      clearInterval(ringTimer);
      ringTimer = null;
    }
  }

  function attachRemote(s) {
    const sdh = s.sessionDescriptionHandler;
    if (!sdh || !sdh.peerConnection) return;
    const stream = new MediaStream();
    sdh.peerConnection.getReceivers().forEach((r) => {
      if (r.track) stream.addTrack(r.track);
    });
    audioEl.srcObject = stream;
    audioEl.play().catch(() => {});
  }

  function toggleMute() {
    const sdh = session && session.sessionDescriptionHandler;
    if (!sdh || !sdh.peerConnection) return;
    const sender = sdh.peerConnection
      .getSenders()
      .find((s) => s.track && s.track.kind === "audio");
    if (!sender || !sender.track) return;
    muted = !muted;
    sender.track.enabled = !muted;
    muteBtn.textContent = muted ? "Unmute" : "Mute";
  }

  function resetButtons() {
    callBtn.disabled = false;
    if (echoBtn) echoBtn.disabled = false;
    acceptBtn.hidden = true;
    rejectBtn.hidden = true;
    muteBtn.disabled = true;
    muteBtn.textContent = "Mute";
    hangupBtn.disabled = true;
    muted = false;
  }

  function watchSession(s) {
    s.stateChange.addListener((state) => {
      if (state === SIP.SessionState.Established) {
        stopRingback();
        session = s;
        setStatus("Connected", "ok");
        acceptBtn.hidden = true;
        rejectBtn.hidden = true;
        muteBtn.disabled = false;
        hangupBtn.disabled = false;
        attachRemote(s);
      } else if (state === SIP.SessionState.Terminated) {
        stopRingback();
        if (session === s) session = null;
        incoming = null;
        setStatus("Call ended", "idle");
        audioEl.srcObject = null;
        resetButtons();
      }
    });
  }

  function handleIncoming(invitation) {
    if (session || incoming) {
      invitation.reject().catch(() => {});
      return;
    }
    incoming = invitation;
    setStatus("Incoming call from the office", "busy");
    startRingback();
    callBtn.disabled = true;
    acceptBtn.hidden = false;
    rejectBtn.hidden = false;
    watchSession(invitation);
  }

  async function acceptIncoming() {
    if (!incoming) return;
    acceptBtn.disabled = true;
    try {
      await incoming.accept();
    } catch (e) {
      setStatus("Accept failed: " + e, "err");
      incoming = null;
      resetButtons();
    } finally {
      acceptBtn.disabled = false;
    }
  }

  async function rejectIncoming() {
    if (!incoming) return;
    stopRingback();
    try {
      await incoming.reject();
    } catch (e) { /* already gone */ }
    incoming = null;
    setStatus("Call rejected", "idle");
    resetButtons();
  }

  async function ensureUA() {
    if (ua) return ua;
    const uri = SIP.UserAgent.makeURI("sip:180@" + cfg.sipDomain);
    if (!uri) throw new Error("bad SIP URI");
    ua = new SIP.UserAgent({
      uri,
      displayName: cfg.displayName || "Web visitor",
      transportOptions: { server: cfg.wssUrl },
      sessionDescriptionHandlerFactoryOptions: { iceGatheringTimeout: 3000 }
    });
    ua.delegate = {
      onDisconnect: (error) => {
        setStatus("Disconnected" + (error ? ": " + error : ""), "err");
        session = null;
        incoming = null;
        stopRingback();
        resetButtons();
      },
      onInvite: (invitation) => handleIncoming(invitation)
    };
    await ua.start();
    registerer = new SIP.Registerer(ua, { expires: 300 });
    registerer.stateChange.addListener((state) => {
      if (state === SIP.RegistererState.Registered) {
        if (!session && !incoming) setStatus("Available - the office can dial 180#", "ok");
      } else if (state === SIP.RegistererState.Unregistered) {
        if (!session && !incoming) setStatus("Not registered - reload to retry", "err");
      }
    });
    try {
      await registerer.register();
    } catch (e) {
      setStatus("Registration failed: " + e, "err");
    }
    return ua;
  }

  async function hangup() {
    if (!session) return;
    try {
      if (session.state === SIP.SessionState.Establishing) {
        await session.cancel();
      } else if (session.state === SIP.SessionState.Established) {
        await session.bye();
      }
    } catch (e) {
      setStatus("Hangup error: " + e, "err");
    }
  }

  async function call(ext, what) {
    callBtn.disabled = true;
    if (echoBtn) echoBtn.disabled = true;
    setStatus("Calling...", "busy");
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") audioCtx.resume();
    } catch (e) { /* ringback is best-effort */ }
    try {
      const agent = await ensureUA();
      const target = SIP.UserAgent.makeURI(
        "sip:" + ext + "@" + cfg.sipDomain
      );
      if (!target) throw new Error("bad target URI");
      const inviter = new SIP.Inviter(agent, target);
      session = inviter;
      inviter.delegate = {
        onProgress: () => {
          if (session === inviter) {
            setStatus("Ringing " + what + "...", "busy");
            startRingback();
          }
        }
      };
      inviter.stateChange.addListener((state) => {
        if (state === SIP.SessionState.Establishing) {
          setStatus("Calling " + ext + "...", "busy");
        } else if (state === SIP.SessionState.Established) {
          stopRingback();
          setStatus("Connected - " + what + " answered", "ok");
          muteBtn.disabled = false;
          hangupBtn.disabled = false;
          attachRemote(inviter);
        } else if (state === SIP.SessionState.Terminated) {
          stopRingback();
          setStatus("Call ended", "idle");
          audioEl.srcObject = null;
          session = null;
          resetButtons();
        }
      });
      await inviter.invite();
      hangupBtn.disabled = false;
    } catch (e) {
      stopRingback();
      setStatus("Call failed: " + e, "err");
      session = null;
      resetButtons();
    }
  }

  callBtn.addEventListener("click", () => call(cfg.targetExtension, "the office"));
  if (echoBtn) {
    echoBtn.addEventListener("click", () => call(cfg.echoExtension || "999", "echo test"));
  }
  acceptBtn.addEventListener("click", acceptIncoming);
  rejectBtn.addEventListener("click", rejectIncoming);
  muteBtn.addEventListener("click", toggleMute);
  hangupBtn.addEventListener("click", hangup);
  window.addEventListener("beforeunload", () => {
    if (session) hangup();
  });

  ensureUA().catch((e) => setStatus("Startup failed: " + e, "err"));
})();
