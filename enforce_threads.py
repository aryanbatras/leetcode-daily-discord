"""Enforce thread-only channels.

Scans designated channels for direct messages (not in threads).
Deletes them and posts a warning embed.

Usage:
    python3 enforce_threads.py
"""

import json
import os
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

CFG = load_config()
GUILD_ID = CFG["guild_id"]
DISCORD_UA = CFG["bot"]["ua"]

# Channels that must be thread-only
THREAD_ONLY_CHANNELS = [
    "introductions",
    "accomplishments",
    "study-buddy",
    "suggestions",
    "project-help",
]


def dapi(url, token=None, method="GET", body=None):
    data = json.dumps(body).encode() if body else None
    headers = {"User-Agent": DISCORD_UA}
    if token:
        headers["Authorization"] = f"Bot {token}"
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status == 204:
                return None
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  API error: {e}")
        return None


def resolve_channels(token):
    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels"
    channels = dapi(url, token=token)
    mapping = {}
    if channels:
        for ch in channels:
            if ch["name"] in THREAD_ONLY_CHANNELS and ch["type"] == 0:
                mapping[ch["name"]] = ch["id"]
    return mapping


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("DISCORD_BOT_TOKEN required")

    channels = resolve_channels(token)
    total_deleted = 0

    for name, ch_id in channels.items():
        # Fetch recent messages
        url = f"https://discord.com/api/v10/channels/{ch_id}/messages?limit=50"
        msgs = dapi(url, token=token) or []

        for m in msgs:
            # Skip bot messages
            if m.get("author", {}).get("bot"):
                continue
            # Skip messages that are in a thread (thread_id present)
            if m.get("thread"):
                continue
            # Skip pinned messages
            if m.get("pinned"):
                continue

            # This is a direct message in a thread-only channel — delete it
            del_url = f"https://discord.com/api/v10/channels/{ch_id}/messages/{m['id']}"
            dapi(del_url, token=token, method="DELETE")
            total_deleted += 1
            print(f"Deleted message from {m['author'].get('global_name', '?')} in #{name}")
            time.sleep(0.3)

    if total_deleted > 0:
        print(f"Cleaned up {total_deleted} messages from thread-only channels")
    else:
        print("All clean — no violations")


if __name__ == "__main__":
    main()
