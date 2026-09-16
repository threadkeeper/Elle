import argparse
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from azure.identity import AzureCliCredential


TENANT_ID = "8d0fb62d-a3b4-445b-bdd6-7954ef2cb817"
API_APP_ID = "0479a728-6b4d-4d96-8693-ef766bc8e1fe"
API_SCOPE_ID = "2cc9bf23-2b96-4998-9bcc-ca6fc735ca40"
PROJECT_RESOURCE_ID = (
    "/subscriptions/168b5d01-88b5-489c-8246-5f346c834ca5/resourceGroups/rg-ai"
    "/providers/Microsoft.CognitiveServices/accounts/foundry-jva-002"
    "/projects/proj-default-sweden"
)
CONNECTION_NAME = "elle-private-oauth"
CLIENT_NAME = "Elle Foundry Private OAuth"
TARGET = "https://elle-private-vnet.yellowsky-9d92d540.swedencentral.azurecontainerapps.io/mcp"


def application_body() -> dict:
    return {
        "displayName": CLIENT_NAME,
        "signInAudience": "AzureADMyOrg",
        "requiredResourceAccess": [
            {
                "resourceAppId": API_APP_ID,
                "resourceAccess": [{"id": API_SCOPE_ID, "type": "Scope"}],
            }
        ],
    }


def connection_body(client_id: str, client_secret: str, object_id: str) -> dict:
    authority = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0"
    return {
        "properties": {
            "authType": "OAuth2",
            "category": "RemoteTool",
            "target": TARGET,
            "authorizationUrl": f"{authority}/authorize",
            "tokenUrl": f"{authority}/token",
            "refreshUrl": f"{authority}/token",
            "scopes": [f"api://{API_APP_ID}/access_as_user", "offline_access"],
            "credentials": {"clientId": client_id, "clientSecret": client_secret},
            "metadata": {"oauthClientObjectId": object_id, "owner": "Elle"},
        }
    }


def callback_uri(connection: dict) -> str:
    uri = connection["properties"].get("redirectUrl")
    if not isinstance(uri, str):
        raise RuntimeError("Foundry has not returned the OAuth redirect URL")
    parsed = urlparse(uri)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "global.consent.azure-apim.net"
        or not parsed.path.startswith("/redirect/")
    ):
        raise RuntimeError("Foundry returned an unexpected OAuth redirect origin")
    return uri


class AzureApi:
    def __init__(self):
        self.credential = AzureCliCredential(tenant_id=TENANT_ID, process_timeout=120)

    def request(self, method: str, url: str, body: dict | None = None, *, missing_ok=False):
        host = urlparse(url).hostname
        scopes = {
            "graph.microsoft.com": "https://graph.microsoft.com/.default",
            "management.azure.com": "https://management.azure.com/.default",
        }
        if host not in scopes:
            raise ValueError("Only Microsoft Graph and ARM destinations are allowed")
        token = self.credential.get_token(scopes[host]).token
        response = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=90,
        )
        if missing_ok and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else None


def configure(api: AzureApi) -> dict:
    graph = "https://graph.microsoft.com/v1.0"
    arm = (
        f"https://management.azure.com{PROJECT_RESOURCE_ID}/connections/"
        f"{CONNECTION_NAME}?api-version=2025-04-01-preview"
    )
    connection = api.request("GET", arm, missing_ok=True)
    if connection is not None:
        props = connection["properties"]
        if props["authType"] != "OAuth2" or props["target"] != TARGET:
            raise RuntimeError("Existing connection does not match Private OAuth configuration")
        object_id = props.get("metadata", {}).get("oauthClientObjectId")
        if not object_id:
            raise RuntimeError("Existing connection does not identify its OAuth application")
        app = api.request("GET", f"{graph}/applications/{object_id}")
    else:
        apps = api.request(
            "GET", f"{graph}/applications?$filter=displayName eq '{CLIENT_NAME}'"
        )["value"]
        if apps:
            raise RuntimeError(
                "OAuth application already exists without its connection; inspect before retrying"
            )
        app = api.request("POST", f"{graph}/applications", application_body())
        expiry = datetime.now(timezone.utc) + timedelta(days=90)
        password = api.request(
            "POST",
            f"{graph}/applications/{app['id']}/addPassword",
            {"passwordCredential": {
                "displayName": CONNECTION_NAME,
                "endDateTime": expiry.isoformat(),
            }},
        )
        try:
            api.request(
                "PUT", arm,
                connection_body(app["appId"], password["secretText"], app["id"]),
            )
        except requests.HTTPError:
            api.request(
                "POST", f"{graph}/applications/{app['id']}/removePassword",
                {"keyId": password["keyId"]},
            )
            raise
        finally:
            password.clear()
        connection = api.request("GET", arm)
    redirect = callback_uri(connection)
    redirects = app.get("web", {}).get("redirectUris", [])
    if redirect not in redirects:
        api.request(
            "PATCH", f"{graph}/applications/{app['id']}",
            {"web": {"redirectUris": [*redirects, redirect]}},
        )
    verified = api.request("GET", f"{graph}/applications/{app['id']}")
    if redirect not in verified["web"]["redirectUris"]:
        raise RuntimeError("OAuth callback registration was not retained")
    return {
        "connection": CONNECTION_NAME,
        "authType": "OAuth2",
        "clientId": app["appId"],
        "redirectUri": redirect,
        "perUserAuthorizationRequired": True,
        "liveAgentChanged": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure a separate per-user OAuth connection; never switches live traffic."
    )
    parser.add_argument("--apply", action="store_true", help="Create the app and connection")
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required")
    print(json.dumps(configure(AzureApi()), indent=2))


if __name__ == "__main__":
    main()
