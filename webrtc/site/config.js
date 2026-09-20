(function () {
  var host = window.location.hostname || "192.168.2.1";
  window.WEBRTC_CONFIG = {
    wssUrl: "wss://" + host + ":8089/ws",
    sipDomain: host,
    targetExtension: "100",
    echoExtension: "999",
    displayName: "Office visitor",
    iceServers: []
  };
})();
