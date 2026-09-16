"""Adversarial controls for the independent oracle; no A1 implementation used."""
from copy import deepcopy
import unittest

from tools.a2_e1 import digest, event, event_metrics, verdict


class OracleCounterexamples(unittest.TestCase):
    def setUp(self):
        self.events = [event("first", 1, session="one"), event("second", 2, session="one")]

    def test_loss_cannot_pass(self):
        self.assertEqual(event_metrics(self.events, self.events[:1])["event_loss"], 1)

    def test_order_and_duplicate_cannot_pass(self):
        self.assertEqual(event_metrics(self.events, self.events[::-1])["sequence_disorder"], 1)
        self.assertEqual(event_metrics(self.events, self.events + self.events[:1])["duplicate_amplification"], 1)

    def test_fabricated_event_cannot_pass(self):
        self.assertEqual(event_metrics(self.events, self.events + [event("phantom")])["duplicate_amplification"], 1)

    def test_status_and_structured_value_mutations_cannot_pass(self):
        for key, value in (("status", "failed"), ("content_payload", {"text": False}),
                           ("persona_id", "model-derived-persona"), ("attachment_ref", [{"source_ref": "changed"}])):
            altered = deepcopy(self.events)
            altered[0][key] = value
            self.assertEqual(event_metrics(self.events, altered)["payload_status_drift"], 1)
        self.assertNotEqual(digest({"value": False}), digest({"value": 0}))
        self.assertNotEqual(digest({"value": None}), digest({"value": False}))

    def test_unknown_collapse_cannot_pass(self):
        altered = deepcopy(self.events)
        altered[0]["metadata"]["knowledge"]["observability"]["state"] = "UNKNOWN"
        self.assertEqual(event_metrics(self.events, altered)["semantic_collapse"], 1)

    def test_destructive_correction_cannot_pass(self):
        correction = event("correction", 3, session="one")
        correction["correction_of"] = self.events[0]["event_id"]
        expected = self.events + [correction]
        observed = deepcopy(expected)
        observed[0]["content_payload"] = {"text": "overwritten"}
        self.assertEqual(event_metrics(expected, observed)["destructive_correction"], 1)
        self.assertEqual(event_metrics(expected, expected[1:])["destructive_correction"], 1)

    def test_missing_or_failed_evidence_cannot_pass(self):
        self.assertEqual(verdict([], []), "BLOCKED")
        self.assertEqual(verdict([{"passed": True}], ["missing F8"]), "NOT_EVALUABLE")
        self.assertEqual(verdict([{"passed": False}], ["missing F8"]), "FAIL")
        self.assertEqual(verdict([{"passed": True}], []), "PASS")


if __name__ == "__main__":
    unittest.main()
