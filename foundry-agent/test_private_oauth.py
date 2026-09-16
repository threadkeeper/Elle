import unittest

from configure_private_oauth import (
    API_APP_ID, API_SCOPE_ID, TENANT_ID, application_body, callback_uri, connection_body,
)


class PrivateOAuthTests(unittest.TestCase):
    def test_application_requests_only_private_delegated_scope(self):
        app = application_body()
        self.assertEqual(app["signInAudience"], "AzureADMyOrg")
        self.assertEqual(app["requiredResourceAccess"], [{
            "resourceAppId": API_APP_ID,
            "resourceAccess": [{"id": API_SCOPE_ID, "type": "Scope"}],
        }])

    def test_connection_uses_tenant_pinned_oauth(self):
        props = connection_body("client", "test-only-secret", "object")["properties"]
        self.assertEqual(props["authType"], "OAuth2")
        self.assertIn(TENANT_ID, props["authorizationUrl"])
        self.assertEqual(props["tokenUrl"], props["refreshUrl"])
        self.assertEqual(props["scopes"], [
            f"api://{API_APP_ID}/access_as_user", "offline_access",
        ])
        self.assertNotIn("audience", props)
        self.assertNotIn("Authorization", props)

    def test_callback_rejects_wrong_or_missing_origins(self):
        for uri in (
            None, "http://global.consent.azure-apim.net/redirect/id",
            "https://global.consent.azure-apim.net.evil.example/redirect/id",
            "https://global.consent.azure-apim.net/other/id",
        ):
            with self.subTest(uri=uri), self.assertRaises(RuntimeError):
                callback_uri({"properties": {"redirectUrl": uri}})

    def test_callback_uses_exact_foundry_value(self):
        uri = "https://global.consent.azure-apim.net/redirect/connection-id"
        self.assertEqual(callback_uri({"properties": {"redirectUrl": uri}}), uri)


if __name__ == "__main__":
    unittest.main()
