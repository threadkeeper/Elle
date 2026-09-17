import unittest
from unittest.mock import patch

from azure.ai.agentserver.core import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)

from caller_identity import elle_identity_status


class CallerIdentityTests(unittest.TestCase):
    def status_for(self, user_id: str | None) -> dict[str, str]:
        token = set_request_context(FoundryAgentRequestContext(user_id=user_id))
        try:
            return elle_identity_status()
        finally:
            reset_request_context(token)

    def test_missing_identity_fails_closed(self):
        self.assertEqual(
            self.status_for(None),
            {"identity": "unavailable", "binding": "unavailable"},
        )

    def test_identity_is_present_without_model_visible_identifier(self):
        with patch("caller_identity.logger.info") as log:
            first = self.status_for("platform-user-one")

        self.assertEqual(first, {"identity": "present", "binding": "unbound"})
        self.assertNotIn("platform-user-one", str(first))
        fingerprint = log.call_args.args[1]
        self.assertEqual(len(fingerprint), 16)
        self.assertNotEqual(fingerprint, "platform-user-one")

    def test_operator_fingerprint_is_stable_and_distinct(self):
        with patch("caller_identity.logger.info") as log:
            self.status_for("platform-user-one")
            first = log.call_args.args[1]
            self.status_for("platform-user-one")
            repeated = log.call_args.args[1]
            self.status_for("platform-user-two")
            second = log.call_args.args[1]

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()