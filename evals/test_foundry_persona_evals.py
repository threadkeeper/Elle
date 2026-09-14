"""Offline contract tests for the live Foundry persona evaluation runner."""

import unittest

from run_foundry_persona_evals import JEAN_TRAITS, WILDCARDS, metrics


class FoundryPersonaEvalTests(unittest.TestCase):
    def test_developer_blend_and_comic_wildcards_are_explicit(self):
        self.assertIn("direct curiosity", JEAN_TRAITS)
        self.assertEqual(len(WILDCARDS), 4)
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


if __name__ == "__main__":
    unittest.main()
