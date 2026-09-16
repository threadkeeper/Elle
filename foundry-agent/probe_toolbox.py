import argparse
import json

import requests
from azure.identity import AzureCliCredential

from deploy import PROJECT_ENDPOINT, TOOLBOX_NAME


def read_reply(response: requests.Response, request_id: int) -> dict:
    response.raise_for_status()
    if "text/event-stream" not in response.headers.get("Content-Type", ""):
        reply = response.json()
        if reply.get("id") != request_id:
            raise RuntimeError("MCP response ID does not match the request")
        return reply
    data = []
    for line in response.iter_lines(decode_unicode=True):
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            reply = json.loads("\n".join(data))
            data = []
            if reply.get("id") == request_id:
                return reply
    raise RuntimeError("MCP stream ended without a matching response")


def probe(version: str) -> dict:
    credential = AzureCliCredential(process_timeout=120)
    token = credential.get_token("https://ai.azure.com/.default").token
    url = f"{PROJECT_ENDPOINT}/toolboxes/{TOOLBOX_NAME}/versions/{version}/mcp?api-version=v1"
    with requests.Session() as client:
        client.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        })
        with client.post(url, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "elle-diagnostic", "version": "1.0"},
            },
        }, stream=True, timeout=120) as response:
            initialized = read_reply(response, 1)
            session_id = response.headers.get("Mcp-Session-Id")
        if "error" in initialized:
            return initialized
        if session_id:
            client.headers["Mcp-Session-Id"] = session_id
        client.headers["MCP-Protocol-Version"] = initialized["result"]["protocolVersion"]
        with client.post(url, json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }, timeout=120) as response:
            response.raise_for_status()
        tools = []
        cursor = None
        request_id = 2
        seen_cursors = set()
        while True:
            with client.post(url, json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/list",
                "params": {"cursor": cursor} if cursor else {},
            }, stream=True, timeout=120) as response:
                reply = read_reply(response, request_id)
            if "error" in reply:
                return reply
            tools.extend(tool["name"] for tool in reply["result"]["tools"])
            cursor = reply["result"].get("nextCursor")
            if not cursor:
                return {"version": version, "toolCount": len(tools), "tools": tools}
            if cursor in seen_cursors:
                raise RuntimeError("MCP server repeated a tools/list cursor")
            seen_cursors.add(cursor)
            request_id += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only, current-user toolbox discovery")
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    result = probe(args.version)
    print(json.dumps(result, indent=2))
    if "error" in result:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
