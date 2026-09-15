"""Synthesize minimal PCM WAV prompts for the loopback IVR calibration.

Produces fixed-tone, machine-checkable prompts (440 Hz for the menu, 660 Hz
for the confirmation) at 8 kHz 16-bit mono so the local engine probe needs no
core sound package. Files are written one at a time into an existing
directory; existing files are never overwritten.

This is a local calibration aid only; a deployed engine would ship real
prompts from the asterisk-sounds package.
"""

import argparse
import math
import os
import struct
import sys
import wave

SAMPLE_RATE = 8000
TONE_AMPLITUDE = 0.35
DURATION_SECONDS = 1


def tone_pcm(frequency_hz, duration_seconds=DURATION_SECONDS):
    samples = []
    for index in range(int(SAMPLE_RATE * duration_seconds)):
        phase = 2.0 * math.pi * frequency_hz * index / SAMPLE_RATE
        samples.append(int(32767 * TONE_AMPLITUDE * math.sin(phase)))
    return struct.pack("<%dh" % len(samples), *samples)


def write_wav(path, frequency_hz):
    if os.path.exists(path):
        raise FileExistsError("refusing to overwrite %s" % path)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(tone_pcm(frequency_hz))
    os.chmod(path, 0o600)


PROMPTS = {
    "menu.wav": 440.0,
    "confirmed.wav": 660.0,
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sounds_dir",
                        help="destination directory (must already exist)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not os.path.isdir(args.sounds_dir):
        print("ERROR: %s is not a directory" % args.sounds_dir, file=sys.stderr)
        return 1
    written = []
    for name, frequency_hz in sorted(PROMPTS.items()):
        path = os.path.join(args.sounds_dir, name)
        write_wav(path, frequency_hz)
        written.append(name)
    print("WROTE %s into %s" % (", ".join(written), args.sounds_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
