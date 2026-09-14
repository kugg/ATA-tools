"""Explicit host-loopback integration tests; never include these in unit discovery."""

from pathlib import Path
import subprocess
import sys
import unittest

from telephony.host_qualification import QualificationResult, _require_loopback, run_host_qualification


ROOT = Path(__file__).resolve().parents[2]


class HostQualificationTests(unittest.TestCase):
    def test_default_command_prints_plan_without_opening_sockets(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "telephony.host_qualification"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN:", result.stdout)
        self.assertIn("No sockets are opened", result.stdout)

    def test_explicit_qualification_uses_loopback_only(self):
        self.assertEqual(
            run_host_qualification(),
            QualificationResult(sccp=True, iax2_mini=True, rtp_pcmu=True),
        )

    def test_non_loopback_peers_are_rejected_before_protocol_processing(self):
        _require_loopback(("127.0.0.1", 2000))
        with self.assertRaisesRegex(RuntimeError, "non-loopback"):
            _require_loopback(("192.0.2.1", 2000))


if __name__ == "__main__":
    unittest.main()
