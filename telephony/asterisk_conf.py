"""Generate a private, bounded Asterisk 20 config tree for the bench ATA path.

Produces chan_sip (sip.conf), extensions.conf, modules.conf and rtp.conf that
match the bench-proven SIP topology: ATA186 at 192.168.2.10 registers to
192.168.2.2 as user 100 over PCMU/PCMA with RFC2833 DTMF, and extension 100
answers with Playback. Dry run by default; --apply writes new files only into a
mode-0700 directory. No engine is run, no socket is bound, and no ATA is
contacted by this script.

The generated values contain no credentials or device identities beyond the
fixed, non-secret bench addresses documented in docs/asterisk-integration.md.
"""

import argparse
import ipaddress
import os
import re
import sys

DEFAULT_ADDRESS = "192.168.2.2"
DEFAULT_ATA = "192.168.2.10"
DEFAULT_EXTENSION = "100"
DEFAULT_RTP_START = 20000
DEFAULT_RTP_END = 20100

# Answer() is a core application (main/pbx_builtins.c), not a loadable
# module; the list below matches modules that actually ship in Asterisk 20.
MODULES = [
    "res_rtp_asterisk.so",
    "res_crypto.so",
    "res_http_websocket.so",
    "chan_sip.so",
    "pbx_config.so",
    "app_playback.so",
    "app_read.so",
    "res_audiosocket.so",
    "app_audiosocket.so",
    "codec_ulaw.so",
    "codec_alaw.so",
    "format_sln.so",
    "format_gsm.so",
    "format_wav.so",
    "res_timing_pthread.so",
]


class ConfigError(ValueError):
    """An input is outside the bounded bench profile."""


def _fmt_address(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        raise ConfigError("not an IP address: %r" % host)
    return host


def _fmt_extension(number):
    if not re.fullmatch(r"[0-9]{1,4}", number):
        raise ConfigError("extension must be 1-4 digits: %r" % number)
    return number


def _fmt_port_range(start, end):
    for port in (start, end):
        if not 1024 <= port <= 65535:
            raise ConfigError("RTP port out of range: %s" % port)
    if start > end:
        raise ConfigError("RTP start port above end port")
    return start, end


def sip_conf(address, ata, extension, dtmf="rfc2833"):
    return (
        "[general]\n"
        "context = from-ata\n"
        "allowguest = no\n"
        "bindaddr = %s\n"
        "bindport = 5060\n"
        "srvlookup = no\n"
        "nat = no\n"
        "canreinvite = no\n"
        "disallow = all\n"
        "allow = ulaw\n"
        "allow = alaw\n"
        "language = en\n"
        "\n"
        "[%s]\n"
        "type = friend\n"
        "host = dynamic\n"
        "permit = %s\n"
        "context = from-ata\n"
        "defaultuser = %s\n"
        "secret =\n"
        "disallow = all\n"
        "allow = ulaw\n"
        "allow = alaw\n"
        "dtmfmode = %s\n"
        "qualify = no\n"
        "nat = no\n"
        "canreinvite = no\n"
    ) % (_fmt_address(address), _fmt_extension(extension), _fmt_address(ata),
         _fmt_extension(extension), dtmf)


# Fixed call UUID for the single-dialog external-media bench extension.
# The bench profile is one call at a time, so a stable identifier is correct
# here; it is non-secret and documented alongside the agent.
AUDIOSOCKET_UUID = "0023a1a4-b10f-4a51-8d5f-0f3d5e6d7a99"
AUDIOSOCKET_SERVICE = "127.0.0.1:9100"
AUDIOSOCKET_EXTENSION = "101"


def extensions_conf(extension):
    return (
        "[from-ata]\n"
        "exten => %s,1,Answer()\n"
        "same => n,Playback(hello-world)\n"
        "same => n,Read(digits,menu,1)\n"
        "same => n,GotoIf($[\"${digits}\" = \"5\"]?ok)\n"
        "same => n,Hangup()\n"
        "same => n(ok),Playback(confirmed)\n"
        "same => n,Hangup()\n"
        "\n"
        "exten => %s,1,Answer()\n"
        "same => n,AudioSocket(%s,%s)\n"
        "same => n,Hangup()\n"
    ) % (_fmt_extension(extension), AUDIOSOCKET_EXTENSION,
         AUDIOSOCKET_UUID, AUDIOSOCKET_SERVICE)


def modules_conf():  # noqa
    head = "[modules]\nautoload = no\n"
    return head + "".join("load => %s\n" % name for name in MODULES)


def rtp_conf(start, end):
    start, end = _fmt_port_range(start, end)
    return (
        "[general]\n"
        "rtpstart = %d\n"
        "rtpend = %d\n"
        "symmetric_rtp = yes\n"
    ) % (start, end)


def notes(address, ata, extension):
    return (
        "Asterisk 20 bench config generated for the ATA integration plan\n"
        "(docs/asterisk-integration.md). Non-secret, fixed bench topology.\n"
        "\n"
        "service address : %s\n"
        "ATA peer        : %s\n"
        "extension       : %s\n"
        "engine          : chan_sip (removed in Asterisk 21; pinned 20.8.1-r1)\n"
        "dialplan        : %s Answer, Playback(hello-world), Read(one digit,\n"
        "                  bounded IVR), Playback(confirmed), Hangup\n"
        "                  %s Answer, AudioSocket(bounded local agent)\n"
        "\n"
        "Validation: run an Asterisk 20 host probe against this tree on the\n"
        "isolated bench/loopback only. Credentials are intentionally empty to\n"
        "match the bench profile; this tree must never face an untrusted or\n"
        "public network.\n"
    ) % (address, ata, extension, extension, extension)


def render(address=DEFAULT_ADDRESS, ata=DEFAULT_ATA, extension=DEFAULT_EXTENSION,
           rtp_start=DEFAULT_RTP_START, rtp_end=DEFAULT_RTP_END):
    address = _fmt_address(address)
    ata = _fmt_address(ata)
    extension = _fmt_extension(extension)
    rtp_start, rtp_end = _fmt_port_range(rtp_start, rtp_end)
    return {
        "sip.conf": sip_conf(address, ata, extension),
        "extensions.conf": extensions_conf(extension),
        "modules.conf": modules_conf(),
        "rtp.conf": rtp_conf(rtp_start, rtp_end),
        "ASTERISK.md": notes(address, ata, extension),
    }


def _ensure_outdir(path):
    if os.path.exists(path) and not os.path.isdir(path):
        raise ConfigError("not a directory: %s" % path)
    os.makedirs(path, mode=0o700, exist_ok=True)


def write_tree(outdir, files):
    _ensure_outdir(outdir)
    existing = [name for name in files if os.path.exists(os.path.join(outdir, name))]
    if existing:
        raise ConfigError("refusing to overwrite existing files: %s"
                          % ", ".join(sorted(existing)))
    for name, content in files.items():
        full = os.path.join(outdir, name)
        with open(full, "w") as handle:
            handle.write(content)
        os.chmod(full, 0o600)
    return list(files)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", metavar="DIR",
                        help="write the config tree into DIR (mode 0700); "
                             "default is a dry run")
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--ata", dest="ata", default=DEFAULT_ATA)
    parser.add_argument("--extension", default=DEFAULT_EXTENSION)
    parser.add_argument("--rtp-start", type=int, default=DEFAULT_RTP_START)
    parser.add_argument("--rtp-end", type=int, default=DEFAULT_RTP_END)
    return parser.parse_args(argv)


def main(argv=None):
    os.umask(0o077)
    args = parse_args(argv)
    files = render(args.address, args.ata, args.extension,
                   args.rtp_start, args.rtp_end)
    if not args.apply:
        print("DRY RUN: would write %s under mode-0700 directory"
              % ", ".join(sorted(files)))
        print("DRY RUN: start with --apply DIR to write the config tree")
        return 0
    written = write_tree(args.apply, files)
    print("WROTE %s to %s" % (", ".join(written), args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())