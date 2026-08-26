"""Availability scheduler for Mission Faang.

Reads messages from #availability, parses time blocks per user,
finds intersections, and posts the best meeting times.

Usage:
    python3 availability.py scan     -> scan #availability, update data
    python3 availability.py chart    -> post availability chart to #availability
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

CFG = load_config()
GUILD_ID = CFG["guild_id"]
IST = timezone(timedelta(hours=5, minutes=30))
DISCORD_UA = CFG["bot"]["ua"]


def clear_channel(token, channel_id):
    """Delete all messages in a channel."""
    after = "0"
    ids = []
    while True:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=100&after={after}"
        batch = dapi(url, token=token)
        if not batch:
            break
        ids += [m["id"] for m in batch]
        after = max(ids)
        if len(batch) < 100:
            break
        time.sleep(0.3)
    while ids:
        chunk = ids[-100:]
        del ids[-100:]
        dapi(f"https://discord.com/api/v10/channels/{channel_id}/messages/bulk-delete",
             method="POST", token=token, body={"messages": chunk})
        time.sleep(0.5)


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


def resolve_channel(token, name):
    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels"
    channels = dapi(url, token=token)
    if channels:
        for ch in channels:
            if ch["name"] == name and ch["type"] == 0:
                return ch["id"]
    return None


def fetch_messages(token, channel_id, limit=100):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}"
    return dapi(url, token=token) or []


def save(name, obj):
    p = os.path.join(DATA_DIR, name)
    with open(p, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)


def load(name, default=None):
    p = os.path.join(DATA_DIR, name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return default if default is not None else {}


# ── Time parsing ────────────────────────────────────────────────────────────

TIME_RE = re.compile(
    r"(\d{1,2})\s*(am|pm)\s*[-–—to]+\s*(\d{1,2})\s*(am|pm)",
    re.IGNORECASE,
)


def parse_time_block(block_str):
    """Parse '4am-10am' or '2pm-6pm' or '9pm-1am' into (start_hour, end_hour)."""
    # Normalize: strip extra spaces, lowercase
    block_str = block_str.strip().lower()
    m = TIME_RE.search(block_str)
    if not m:
        return None
    start_h = int(m.group(1))
    start_ampm = m.group(2).lower()
    end_h = int(m.group(3))
    end_ampm = m.group(4).lower()

    if start_ampm == "pm" and start_h != 12:
        start_h += 12
    elif start_ampm == "am" and start_h == 12:
        start_h = 0
    if end_ampm == "pm" and end_h != 12:
        end_h += 12
    elif end_ampm == "am" and end_h == 12:
        end_h = 0

    if start_h == end_h:
        return None
    # Handle overnight (e.g., 9pm-1am: start=21, end=1)
    if start_h > end_h:
        return (start_h, 24 + end_h)
    return (start_h, end_h)


def parse_availability(text):
    """Parse availability text like '4am-10am, 2pm-6pm' into list of (start, end) tuples."""
    # Normalize: replace various separators with comma
    text = text.strip().lower()
    text = re.sub(r"[;|/]+", ",", text)
    blocks = re.split(r"[,]+", text)
    result = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        parsed = parse_time_block(block)
        if parsed:
            result.append(parsed)
    return result


def hour_to_str(h):
    # Handle overnight hours (e.g., 25 = 1am next day)
    if h >= 24:
        h -= 24
    if h == 0:
        return "12am"
    elif h == 12:
        return "12pm"
    elif h < 12:
        return f"{h}am"
    else:
        return f"{h-12}pm"


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_scan():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("DISCORD_BOT_TOKEN required")

    ch_id = resolve_channel(token, "availability")
    if not ch_id:
        sys.exit("#availability channel not found")

    msgs = fetch_messages(token, ch_id)
    today = datetime.now(IST).strftime("%Y-%m-%d")

    # Parse availability from each user's message
    availability = {}  # discord_id -> {username, blocks, message_id}
    for m in msgs:
        if m.get("author", {}).get("bot"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue

        blocks = parse_availability(content)
        if not blocks:
            continue

        discord_id = m["author"]["id"]
        username = m["author"].get("global_name") or m["author"]["username"]
        availability[discord_id] = {
            "username": username,
            "blocks": blocks,
            "message_id": m["id"],
        }

    save("availability.json", {
        "date": today,
        "users": availability,
    })

    print(f"Scanned {len(availability)} users with availability")
    return availability


def cmd_chart():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("DISCORD_BOT_TOKEN required")

    ch_id = resolve_channel(token, "availability")
    if not ch_id:
        sys.exit("#availability channel not found")

    # Clear old messages
    clear_channel(token, ch_id)
    print("Cleared #availability")

    data = load("availability.json", {"date": "", "users": {}})
    users = data.get("users", {})

    if not users:
        # Post empty chart
        body = {
            "username": "Availability Bot",
            "embeds": [{
                "title": "Daily Availability",
                "description": "No availability posted yet.\n\nPost your available time in #availability:\n`4am-10am, 2pm-6pm`",
                "color": 0x95A5A6,
            }],
            "allowed_mentions": {"parse": []},
        }
        dapi(f"https://discord.com/api/v10/channels/{ch_id}/messages",
             method="POST", token=token, body=body)
        print("No availability data — posted empty chart")
        return

    # Build hourly heatmap (0-23)
    hourly_count = [0] * 24
    hourly_users = [[] for _ in range(24)]
    for did, info in users.items():
        for start_h, end_h in info["blocks"]:
            if end_h <= 24:
                for h in range(start_h, min(end_h, 24)):
                    hourly_count[h] += 1
                    hourly_users[h].append(info["username"])
            else:
                # Overnight block: split into two parts
                # e.g., 21-25 -> hours 21-23 and hours 0-1
                for h in range(start_h, 24):
                    hourly_count[h] += 1
                    hourly_users[h].append(info["username"])
                for h in range(0, end_h - 24):
                    hourly_count[h] += 1
                    hourly_users[h].append(info["username"])

    # Find top 3 best hours
    ranked = sorted(range(24), key=lambda h: -hourly_count[h])
    best_hours = [h for h in ranked if hourly_count[h] > 0][:3]

    embeds = []

    # Header
    embeds.append({
        "title": f"Daily Availability — {data.get('date', 'unknown')}",
        "description": f"**{len(users)}** members posted availability",
        "color": 0x3498DB,
    })

    # Visual timeline
    lines = []
    for h in range(24):
        count = hourly_count[h]
        bar = "\u2588" * count + "\u2591" * (10 - count) if count <= 10 else "\u2588" * 10
        if count > 0:
            names = ", ".join(hourly_users[h][:3])
            if len(hourly_users[h]) > 3:
                names += f" +{len(hourly_users[h])-3} more"
            lines.append(f"`{hour_to_str(h):>4}` {bar} **{count}** — {names}")
        else:
            lines.append(f"`{hour_to_str(h):>4}` {bar}")

    embeds = []
    embeds.append({
        "title": "Timeline",
        "description": "\n".join(lines),
        "color": 0x2ECC71,
    })

    # Best times
    if best_hours:
        best_lines = []
        for i, h in enumerate(best_hours):
            medal = ["\U0001F947", "\U0001F948", "\U0001F949"][i]
            names = ", ".join(hourly_users[h])
            best_lines.append(
                f"{medal} **{hour_to_str(h)}** — **{hourly_count[h]}** members available\n"
                f"    {names}"
            )
        embeds.append({
            "title": "\U0001F3AF Best Times to Meet",
            "description": "\n\n".join(best_lines),
            "color": 0xF1C40F,
        })

    # Individual schedules
    ind_lines = []
    for did, info in sorted(users.items(), key=lambda x: x[1]["username"]):
        blocks_str = ", ".join(f"{hour_to_str(s)}-{hour_to_str(e)}" for s, e in info["blocks"])
        ind_lines.append(f"**{info['username']}** — `{blocks_str}`")
    embeds.append({
        "title": "\U0001F4C5 Individual Schedules",
        "description": "\n".join(ind_lines),
        "color": 0x9B59B6,
    })

    # Post all embeds (Discord limit: 10 per message)
    for i in range(0, len(embeds), 5):
        chunk = embeds[i:i+5]
        body = {
            "username": "Availability Bot",
            "embeds": chunk,
            "allowed_mentions": {"parse": []},
        }
        dapi(f"https://discord.com/api/v10/channels/{ch_id}/messages",
             method="POST", token=token, body=body)
        time.sleep(0.5)

    print(f"Posted chart: {len(users)} users, {len(embeds)} embeds")


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("scan", "chart"):
        print("usage: availability.py [scan|chart]")
        sys.exit(2)
    {"scan": cmd_scan, "chart": cmd_chart}[sys.argv[1]]()
