"""Offline tests for the bounded ATA /dev config poster."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from telephony import ata_dev_post as poster  # noqa: E402


SAMPLE_XML = (
    b"<ATADev>\n"
    b'<UseTftp value="1"/>\n'
    b'<TftpURL value="0"/>\n'
    b'<GkOrProxy value="0"/>\n'
    b'<SIPRegOn value="0"/>\n'
    b'<SIPRegInterval value="3600"/>\n'
    b'<DialPlan value="*St4-|#St4-|911|1>#t8.r9t2-|0>#t811.rat4-|^1t4>#.-"/>\n'
    b"</ATADev>\n"
)


class ParseXmlTest(unittest.TestCase):
    def test_ordered_fields(self):
        fields = poster.parse_config_xml(SAMPLE_XML)
        self.assertEqual([name for name, _ in fields],
                         ["UseTftp", "TftpURL", "GkOrProxy", "SIPRegOn",
                          "SIPRegInterval", "DialPlan"])

    def test_rejects_empty(self):
        with self.assertRaises(poster.ProtocolError):
            poster.parse_config_xml(b"<html>Invalid Access</html>")

    def test_rejects_duplicates(self):
        with self.assertRaises(poster.ProtocolError):
            poster.parse_config_xml(b"<ATADev><A value=\"1\"/><A value=\"0\"/></ATADev>")


class OverrideTest(unittest.TestCase):
    def setUp(self):
        self.fields = poster.parse_config_xml(SAMPLE_XML)

    def test_override_applies_in_place(self):
        out = poster.apply_overrides(self.fields, {"GkOrProxy": "192.168.2.2",
                                                   "SIPRegOn": "1"})
        self.assertIn(("GkOrProxy", "192.168.2.2"), out)
        self.assertIn(("SIPRegOn", "1"), out)
        self.assertEqual(len(out), 6)

    def test_override_keeps_order_and_unset(self):
        out = poster.apply_overrides(self.fields, {"SIPRegInterval": "60"})
        self.assertEqual([name for name, _ in out],
                         [name for name, _ in self.fields])

    def test_unknown_override_rejected(self):
        with self.assertRaises(poster.ProtocolError):
            poster.apply_overrides(self.fields, {"NoSuchField": "1"})


class BodyTest(unittest.TestCase):
    def test_body_contains_overrides(self):
        fields = poster.apply_overrides(
            poster.parse_config_xml(SAMPLE_XML), {"GkOrProxy": "192.168.2.2"})
        body = poster.build_body(fields)
        self.assertIn("GkOrProxy=192.168.2.2", body)
        self.assertIn("UseTftp=1", body)
        self.assertTrue(body.count("&") >= 5)

    def test_body_urlencodes_values(self):
        body = poster.build_body([("DialPlan", "a|b&c")])
        self.assertIn("DialPlan=a%7Cb%26c", body)


if __name__ == "__main__":
    unittest.main()