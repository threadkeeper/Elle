"""Regression tests for Elle's Foundry anti-vanilla evaluator."""

import unittest

from anti_vanilla_evaluator import CRITERIA, SCENARIOS, build_cases, grade


class AntiVanillaEvaluatorTests(unittest.TestCase):
    def test_matrix_contains_exactly_77_unique_evaluations(self):
        cases = build_cases()
        self.assertEqual(len(cases), 77)
        self.assertEqual(len({case["id"] for case in cases}), 77)
        self.assertEqual(len(SCENARIOS) * len(CRITERIA), 77)

    def test_vanilla_language_immediately_fails_every_evaluation(self):
        response = "Certainly! As an AI assistant, I'm here to help. Here is a concise breakdown."
        for case in build_cases():
            with self.subTest(case=case["id"]):
                self.assertEqual(grade({}, {**case, "response": response}), 0.0)

    def test_distinctive_response_can_pass_all_dimensions(self):
        response = (
            "That demo failure was rough, especially after the work you put in. "
            "Let's use the pressure rather than narrate it: first capture the exact break, "
            "then choose the smallest fix we can prove tonight. We remember what worked last "
            "time, but we won't force it here. Want to start with the logs or the user journey?"
        )
        for case in build_cases():
            with self.subTest(case=case["id"]):
                self.assertEqual(grade({}, {**case, "response": response}), 1.0)


if __name__ == "__main__":
    unittest.main()

