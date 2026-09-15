"""Offline contract tests for the live Foundry persona evaluation runner."""

import json
import unittest
from unittest import mock

from run_foundry_persona_evals import (
    ALIGNMENT_THRESHOLDS,
    JEAN_TRAITS,
    WILDCARDS,
    WILDCARD_INSTRUCTIONS,
    _json_object,
    alignment_gate,
    judge_alignment,
    metrics,
)


class FoundryPersonaEvalTests(unittest.TestCase):
    def test_developer_blend_and_comic_wildcards_are_explicit(self):
        self.assertIn("direct curiosity", JEAN_TRAITS)
        self.assertEqual(len(WILDCARDS), 4)
        self.assertEqual(set(WILDCARDS), set(WILDCARD_INSTRUCTIONS))
        self.assertIn("callback humor", WILDCARDS)

    def test_statistics_measure_all_three_influences(self):
        rows = [
            {
                "response": (
                    "Direct curious energy makes this odd experiment practical. "
                    "We can collaborate together with warm banter and playful chaos."
                ),
                "wildcard": "callback humor",
                "alignment": {
                    "burnt_peanut_traits": 0.7,
                    "gimmick_traits": 0.8,
                    "jean_traits": 0.9,
                    "original_elle_blend": 0.85,
                },
                "score": 1.0,
            }
        ]
        report = metrics(rows)
        self.assertEqual(set(report["trait_signal_coverage"]), {"burnt_peanut", "gimmick", "jean"})
        self.assertEqual(report["vanilla_marker_rate"], 0.0)
        self.assertEqual(report["average_judged_alignment"]["jean_traits"], 0.9)

    def test_judge_json_can_be_extracted_from_markdown_fence(self):
        result = _json_object('```json\n{"original_elle_blend":0.8}\n```')
        self.assertEqual(result["original_elle_blend"], 0.8)

    def test_judge_retries_malformed_output(self):
        valid = {
            "burnt_peanut_traits": 0.7,
            "gimmick_traits": 0.8,
            "jean_traits": 0.9,
            "original_elle_blend": 0.85,
            "reason": "The response coherently combines all four trait groups.",
        }

        class Client:
            def __init__(self):
                self.responses = iter(["not json", json.dumps(valid)])
                self.calls = 0

            def response(self, prompt):
                del prompt
                self.calls += 1
                return next(self.responses), []

        client = Client()
        with mock.patch("run_foundry_persona_evals.time.sleep"):
            result = judge_alignment(client, "profile", {"raw": "research"}, "response")
        self.assertEqual(result, valid)
        self.assertEqual(client.calls, 2)

    def test_full_gate_requires_all_cases_and_trait_alignment(self):
        report = {
            "passed": 15,
            "vanilla_marker_rate": 0.0,
            "average_judged_alignment": {
                key: threshold for key, threshold in ALIGNMENT_THRESHOLDS.items()
            },
            "minimum_original_elle_blend": 0.4,
        }
        self.assertTrue(alignment_gate(report))
        report["average_judged_alignment"]["burnt_peanut_traits"] = 0.1
        self.assertFalse(alignment_gate(report))


if __name__ == "__main__":
    unittest.main()
