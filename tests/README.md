# Test boundaries

Unit tests: no sockets, privileges, models, service mutation or network commands.

Host tests in `tests/host/` are separate and explicit. They may open only bounded,
ephemeral `127.0.0.1` sockets with one-second timeouts. They use deterministic
synthetic PCMU samples, never microphones, saved audio, user reference voices,
devices, QEMU, WireGuard or external peers.

Run host checks only when intentionally qualifying the local host:

```sh
python3 -B -m unittest discover -s tests/host -v
python3 -B -m telephony.host_qualification --run
```

QEMU tests: see tests/qemu/README.md before launch.

Each task records test purpose, prerequisites, results and limitations. Failed
checks stay visible. Mark completed only after the specified environment passes.
