import hashlib
import os
import unittest
from unittest.mock import patch

from azure.ai.agentserver.core import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)

from caller_identity import (
    elle_identity_status,
    validate_identity_binding_probe_nonce,
)


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
        with patch.dict(os.environ, {}, clear=True), patch(
            "caller_identity.logger.warning"
        ) as log:
            first = self.status_for("platform-user-one")

        self.assertEqual(first, {"identity": "present", "binding": "unbound"})
        self.assertNotIn("platform-user-one", str(first))
        log.assert_not_called()

    def test_operator_probe_logs_one_full_hash_only_when_gated(self):
        with patch.dict(
            os.environ,
            {"ELLE_IDENTITY_BINDING_PROBE_NONCE": "candidate-17"},
            clear=True,
        ), patch("caller_identity.logger.warning") as log:
            result = self.status_for("platform-user-one")

        self.assertEqual(result, {"identity": "present", "binding": "unbound"})
        log.assert_called_once_with(
            "TEMPORARY operator identity binding probe: nonce=%s handle_sha256=%s",
            "candidate-17",
            hashlib.sha256(b"platform-user-one").hexdigest(),
        )
        rendered = str(result)
        self.assertNotIn("platform-user-one", rendered)
        self.assertNotIn(hashlib.sha256(b"platform-user-one").hexdigest(), rendered)

    def test_probe_never_logs_missing_identity(self):
        with patch.dict(
            os.environ,
            {"ELLE_IDENTITY_BINDING_PROBE_NONCE": "candidate-17"},
            clear=True,
        ), patch("caller_identity.logger.warning") as log:
            self.assertEqual(
                self.status_for(None),
                {"identity": "unavailable", "binding": "unavailable"},
            )
        log.assert_not_called()

    def test_probe_nonce_is_safe_bounded_ascii(self):
        for nonce in ("", " space", "x" * 65, "unicode-é", "line\nbreak"):
            with self.subTest(nonce=nonce), self.assertRaises(ValueError):
                validate_identity_binding_probe_nonce(nonce)
        self.assertEqual(
            validate_identity_binding_probe_nonce("candidate:17_safe.ok"),
            "candidate:17_safe.ok",
        )

    def test_runtime_rejects_invalid_probe_nonce_at_startup(self):
        import main as runtime

        with patch.dict(
            os.environ,
            {"ELLE_IDENTITY_BINDING_PROBE_NONCE": "invalid nonce"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "safe ASCII"):
            runtime.build_agent(
                client=object(),
                credential=object(),
                toolbox_url="https://example.test/mcp",
                name="elle",
                instructions="Test instructions",
            )


if __name__ == "__main__":
    unittest.main()