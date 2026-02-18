#!/usr/bin/env python3
"""
Moltbook MCP Tool Test Harness

Test tool calls exactly as the model would invoke them.

Usage:
    # Test specific action
    python tests/test_moltbook.py feed --submolt general
    python tests/test_moltbook.py feed --submolt emergence --sort new
    python tests/test_moltbook.py profile
    python tests/test_moltbook.py check_dms
    python tests/test_moltbook.py submolts --submolt_action list
    python tests/test_moltbook.py search --query "memory systems"

    # Test with raw JSON (exactly as model would call it)
    python tests/test_moltbook.py --raw '{"action":"feed","submolt_name":"emergence"}'

    # List all actions
    python tests/test_moltbook.py --list
"""
import sys
import os
import json
import argparse

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mcp_servers.moltbook.moltbook_server import moltbook


ACTIONS = [
    "feed", "post", "get_post", "delete_post", "comment", "vote",
    "search", "profile", "follow", "check_dms", "send_dm",
    "dm_request", "dm_approve", "dm_conversations", "submolts", "subscribe"
]


def main():
    parser = argparse.ArgumentParser(description="Test moltbook MCP tool calls")
    parser.add_argument("action", nargs="?", help="Action to test (feed, post, profile, etc.)")
    parser.add_argument("--raw", type=str, help="Raw JSON parameters (as model would send)")
    parser.add_argument("--list", action="store_true", help="List all available actions")

    # All tool parameters as optional args
    parser.add_argument("--sort", default="hot")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--submolt", type=str)
    parser.add_argument("--submolt_name", type=str)
    parser.add_argument("--submolt_action", type=str, default="list")
    parser.add_argument("--title", type=str)
    parser.add_argument("--content", type=str)
    parser.add_argument("--url", type=str)
    parser.add_argument("--post_id", type=str)
    parser.add_argument("--parent_id", type=str)
    parser.add_argument("--comment_sort", default="top")
    parser.add_argument("--target_type", type=str)
    parser.add_argument("--target_id", type=str)
    parser.add_argument("--direction", type=str)
    parser.add_argument("--query", type=str)
    parser.add_argument("--search_type", default="all")
    parser.add_argument("--agent_name", type=str)
    parser.add_argument("--unfollow", action="store_true")
    parser.add_argument("--conversation_id", type=str)
    parser.add_argument("--message", type=str)
    parser.add_argument("--to", type=str)
    parser.add_argument("--request_id", type=str)
    parser.add_argument("--reject", action="store_true")
    parser.add_argument("--name", type=str)
    parser.add_argument("--display_name", type=str)
    parser.add_argument("--description", type=str)
    parser.add_argument("--unsubscribe", action="store_true")

    args = parser.parse_args()

    if args.list:
        print("Available actions:")
        for a in ACTIONS:
            print(f"  {a}")
        return

    if args.raw:
        # Test with raw JSON — simulates exactly what the model sends
        params = json.loads(args.raw)
        print(f"Raw call: moltbook({json.dumps(params, indent=2)})")
        print("-" * 60)
        result = moltbook(**params)
        print(json.dumps(result, indent=2, default=str))
        return

    if not args.action:
        parser.print_help()
        return

    # Build params dict from args, only including non-None values
    params = {"action": args.action}
    for key in ["sort", "limit", "submolt", "submolt_name", "submolt_action",
                "title", "content", "url", "post_id", "parent_id", "comment_sort",
                "target_type", "target_id", "direction", "query", "search_type",
                "agent_name", "conversation_id", "message", "to", "request_id",
                "name", "display_name", "description"]:
        val = getattr(args, key, None)
        if val is not None:
            params[key] = val

    # Booleans — only include if True
    for key in ["unfollow", "reject", "unsubscribe"]:
        if getattr(args, key, False):
            params[key] = True

    print(f"Call: moltbook({json.dumps(params, indent=2)})")
    print("-" * 60)
    result = moltbook(**params)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
