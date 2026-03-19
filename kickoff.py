"""
kickoff.py — Run at 18:15 CET to scrape task docs and post to Discord.

Usage:
    python kickoff.py

Polls the docs page until the countdown disappears, then scrapes all 3 task specs
via the MCP server and prints them.
"""

import asyncio
import json
import os
import sys
import time
import urllib.request

MCP_URL = "https://mcp-docs.ainm.no/mcp"
DOCS_URL = "https://docs.ainm.no"
APP_URL = "https://app.ainm.no/challenge"


def fetch_mcp(tool_name, args=None):
    """Call an MCP tool via HTTP."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": args or {}
        }
    }
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def list_mcp_tools():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def scrape_all_tasks():
    """List MCP tools and fetch all task documentation."""
    print("Listing MCP tools...")
    try:
        tools_resp = list_mcp_tools()
        tools = tools_resp.get("result", {}).get("tools", [])
        print(f"Available tools: {[t['name'] for t in tools]}")
    except Exception as e:
        print(f"Error listing tools: {e}")
        tools = []

    # Try to fetch task docs via known tool names
    task_docs = {}
    for name in ["get_task1", "get_task2", "get_task3", "task1", "task2", "task3",
                 "get_challenge", "list_tasks", "get_tasks"]:
        try:
            result = fetch_mcp(name)
            if "result" in result and result["result"] is not None:
                task_docs[name] = result["result"]
                print(f"✓ {name}: {str(result['result'])[:100]}")
        except Exception:
            pass

    # Try all available tools
    for tool in tools:
        tname = tool["name"]
        if tname not in task_docs:
            try:
                result = fetch_mcp(tname)
                if "result" in result:
                    task_docs[tname] = result["result"]
                    print(f"✓ {tname}: {str(result['result'])[:100]}")
            except Exception:
                pass

    return task_docs


if __name__ == "__main__":
    print("=== NM i AI 2026 Kickoff Script ===")
    print(f"Time: {time.strftime('%H:%M:%S')}")
    print()

    print("Scraping task docs via MCP...")
    docs = scrape_all_tasks()

    print("\n=== TASK DOCS ===")
    for name, content in docs.items():
        print(f"\n--- {name} ---")
        if isinstance(content, dict):
            print(json.dumps(content, indent=2, ensure_ascii=False))
        else:
            print(str(content))

    if not docs:
        print("No docs found. Competition may not have started yet.")
        sys.exit(1)

    print("\n=== DONE ===")
    print("Post the above to Discord and start task implementations!")
