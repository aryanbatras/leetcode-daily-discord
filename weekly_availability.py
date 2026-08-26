"""Weekly availability tracker for Mission Faang.

Reads messages from #weekly-availability, parses per-day time blocks,
clears channel, and posts fresh weekly schedule.

Format: Mon: 9am-12pm, 2pm-6pm | Wed: 10am-4pm

Usage:
    python3 weekly_availability.py scan    -> scan messages, parse schedules
    python3 weekly_availability.py chart   -> clear channel + post weekly chart
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

DAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

TIME_RE = re.compile(r"(\d{1,2})\s*(am|pm)", re.IGNORECASE)
BLOCK_RE = re.compile(
    r"(\d{1,2})\s*(am|pm)\s*[-–to]+\s*(\d{1,2})\s*(am|pm)",
    re.IGNORECASE,
)
DAY_RE = re.compile(
    r"(mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(\s*[-–to]+\s*(mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?",
    re.IGNORECASE,
)


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


def clear_channel(token, channel_id):
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


def parse_time(s):
    m = TIME_RE.match(s.strip())
    if not m:
        return None
    h = int(m.group(1))
    ampm = m.group(2).lower()
    if ampm == "pm" and h != 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    return h


def hour_to_str(h):
    if h == 0 or h == 24:
        return "12am"
    elif h == 12:
        return "12pm"
    elif h < 12:
        return f"{h}am"
    else:
        return f"{h-12}pm"


def expand_day_range(day_str):
    """Expand 'Mon-Fri' or 'Mon-Wed' to list of day indices."""
    day_str = day_str.strip().lower()
    parts = re.split(r"\s*[-–to]+\s*", day_str, maxsplit=1)
    if len(parts) == 2:
        start = DAY_MAP.get(parts[0][:3])
        end = DAY_MAP.get(parts[1][:3])
        if start is not None and end is not None:
            days = []
            d = start
            while True:
                days.append(d)
                if d == end:
                    break
                d = (d + 1) % 7
                if d == start:
                    break
            return days
    else:
        d = DAY_MAP.get(day_str[:3])
        if d is not None:
            return [d]
    return []


def parse_weekly_schedule(text):
    """Parse weekly availability text into {day_index: [(start, end), ...]}."""
    schedule = {}
    # Split by | or newlines
    parts = re.split(r"[|\n]+", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Find day(s)
        day_match = DAY_RE.search(part)
        if not day_match:
            continue

        day_str = day_match.group(0)
        days = expand_day_range(day_str)

        # Find time blocks after the day
        after_day = part[day_match.end():]
        blocks = re.findall(BLOCK_RE, after_day)
        parsed_blocks = []
        for b in blocks:
            start_h = int(b[0])
            start_ampm = b[1].lower()
            end_h = int(b[2])
            end_ampm = b[3].lower()

            if start_ampm == "pm" and start_h != 12:
                start_h += 12
            elif start_ampm == "am" and start_h == 12:
                start_h = 0
            if end_ampm == "pm" and end_h != 12:
                end_h += 12
            elif end_ampm == "am" and end_h == 12:
                end_h = 0

            if start_h < end_h:
                parsed_blocks.append((start_h, end_h))

        for d in days:
            schedule[d] = parsed_blocks

    return schedule


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


def cmd_scan():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("DISCORD_BOT_TOKEN required")

    ch_id = resolve_channel(token, "weekly-availability")
    if not ch_id:
        sys.exit("#weekly-availability channel not found")

    url = f"https://discord.com/api/v10/channels/{ch_id}/messages?limit=100"
    msgs = dapi(url, token=token) or []

    users = {}
    for m in msgs:
        if m.get("author", {}).get("bot"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue

        schedule = parse_weekly_schedule(content)
        if not schedule:
            continue

        discord_id = m["author"]["id"]
        username = m["author"].get("global_name") or m["author"]["username"]
        users[discord_id] = {
            "username": username,
            "schedule": {str(k): v for k, v in schedule.items()},
            "message_id": m["id"],
        }

    save("weekly_availability.json", {
        "users": users,
        "updated": datetime.now(IST).isoformat(),
    })

    print(f"Scanned {len(users)} users with weekly schedules")
    return users


def cmd_chart():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("DISCORD_BOT_TOKEN required")

    ch_id = resolve_channel(token, "weekly-availability")
    if not ch_id:
        sys.exit("#weekly-availability channel not found")

    data = load("weekly_availability.json", {"users": {}})
    users = data.get("users", {})

    # Clear channel
    clear_channel(token, ch_id)
    print("Cleared #weekly-availability")

    if not users:
        body = {
            "username": "Weekly Schedule Bot",
            "embeds": [{
                "title": "Weekly Availability",
                "description": (
                    "No schedules posted yet.\n\n"
                    "**Format:** `Mon: 9am-12pm, 2pm-6pm | Wed: 10am-4pm`\n"
                    "**Days:** Mon, Tue, Wed, Thu, Fri, Sat, Sun\n"
                    "**Ranges:** Mon-Fri, Mon-Wed, Sat-Sun\n\n"
                    "Edit your message daily — bot refreshes every morning."
                ),
                "color": 0x95A5A6,
            }],
            "allowed_mentions": {"parse": []},
        }
        dapi(f"https://discord.com/api/v10/channels/{ch_id}/messages",
             method="POST", token=token, body=body)
        print("Posted empty chart")
        return

    # Build weekly heatmap (7 days x 24 hours)
    weekly_count = [[0]*24 for _ in range(7)]
    weekly_users = [[[] for _ in range(24)] for _ in range(7)]

    for did, info in users.items():
        for day_str, blocks in info["schedule"].items():
            day = int(day_str)
            for start_h, end_h in blocks:
                for h in range(start_h, min(end_h, 24)):
                    weekly_count[day][h] += 1
                    weekly_users[day][h].append(info["username"])

    embeds = []

    # Header
    embeds.append({
        "title": "Weekly Availability",
        "description": f"**{len(users)}** members posted schedules",
        "color": 0x3498DB,
    })

    # Daily breakdown
    for day_idx in range(7):
        lines = []
        any_slot = False
        for h in range(24):
            count = weekly_count[day_idx][h]
            if count > 0:
                any_slot = True
                bar = "\u2588" * count + "\u2591" * (10 - count) if count <= 10 else "\u2588" * 10
                names = ", ".join(weekly_users[day_idx][h][:3])
                if len(weekly_users[day_idx][h]) > 3:
                    names += f" +{len(weekly_users[day_idx][h])-3}"
                lines.append(f"`{hour_to_str(h):>4}` {bar} **{count}** — {names}")

        if any_slot:
            embeds.append({
                "title": f"\U0001F4C5 {DAY_NAMES[day_idx]}",
                "description": "\n".join(lines),
                "color": 0x2ECC71,
            })

    # Best slots per day
    best_lines = []
    for day_idx in range(7):
        best_h = max(range(24), key=lambda h: weekly_count[day_idx][h])
        if weekly_count[day_idx][best_h] > 0:
            names = ", ".join(weekly_users[day_idx][best_h])
            best_lines.append(
                f"**{DAY_NAMES[day_idx]}** — {hour_to_str(best_h)} "
                f"({weekly_count[day_idx][best_h]} available): {names}"
            )
    if best_lines:
        embeds.append({
            "title": "\U0001F3AF Best Slots Per Day",
            "description": "\n".join(best_lines),
            "color": 0xF1C40F,
        })

    # Individual schedules
    ind_lines = []
    for did, info in sorted(users.items(), key=lambda x: x[1]["username"]):
        parts = []
        for day_idx in range(7):
            blocks = info["schedule"].get(str(day_idx), [])
            if blocks:
                blocks_str = ", ".join(f"{hour_to_str(s)}-{hour_to_str(e)}" for s, e in blocks)
                parts.append(f"{DAY_NAMES[day_idx]}: {blocks_str}")
        if parts:
            ind_lines.append(f"**{info['username']}** — {' | '.join(parts)}")
    if ind_lines:
        embeds.append({
            "title": "\U0001F4C5 Individual Schedules",
            "description": "\n".join(ind_lines),
            "color": 0x9B59B6,
        })

    # Footer
    embeds.append({
        "description": (
            "**Format:** `Mon: 9am-12pm, 2pm-6pm | Wed: 10am-4pm`\n"
            "Edit your message daily — bot refreshes every morning."
        ),
        "color": 0x95A5A6,
    })

    # Post embeds
    for i in range(0, len(embeds), 5):
        chunk = embeds[i:i+5]
        body = {
            "username": "Weekly Schedule Bot",
            "embeds": chunk,
            "allowed_mentions": {"parse": []},
        }
        dapi(f"https://discord.com/api/v10/channels/{ch_id}/messages",
             method="POST", token=token, body=body)
        time.sleep(0.5)

    print(f"Posted weekly chart: {len(users)} users, {len(embeds)} embeds")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("scan", "chart"):
        print("usage: weekly_availability.py [scan|chart]")
        sys.exit(2)
    {"scan": cmd_scan, "chart": cmd_chart}[sys.argv[1]]()
