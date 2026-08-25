"""LeetCode leaderboard for Mission Faang.

Modes:
    python3 leaderboard.py poll    -> scan #register for new usernames, validate, store
    python3 leaderboard.py board   -> fetch stats for all members, post to #leaderboard

State lives in data/members.json — committed back by GitHub Actions.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# ── Config ──────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GUILD_ID = 1541028379598397452
CHANNEL_NAMES = {"register": None, "leaderboard": None}  # resolved at runtime

IST = timezone(timedelta(hours=5, minutes=30))
LC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DISCORD_UA = "MFGrindBot/1.0 (github.com/aryanbatras/leetcode-daily-discord)"
LC_DELAY = 1.0  # seconds between LeetCode API calls

# ── LeetCode ────────────────────────────────────────────────────────────────

LC_GRAPHQL = "https://leetcode.com/graphql"

LC_PROFILE_QUERY = """query userData($username: String!) {
    matchedUser(username: $username) {
        username
        profile { userAvatar }
        submitStats: submitStatsGlobal {
            acSubmissionNum { difficulty count }
        }
    }
}"""

LC_CONTEST_QUERY = """query userContestRankingInfo($username: String!) {
    userContestRanking(username: $username) {
        attendedContestsCount
        rating
        globalRanking
        topPercentage
    }
}"""


def lc_request(query, variables):
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        LC_GRAPHQL, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": LC_UA,
                 "Referer": "https://leetcode.com"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def lc_validate(username):
    """Check if a LeetCode username exists. Returns profile dict or None."""
    data = lc_request(LC_PROFILE_QUERY, {"username": username})
    if not data:
        return None
    user = (data.get("data") or {}).get("matchedUser")
    if not user:
        return None
    counts = {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0}
    for row in user.get("submitStats", {}).get("acSubmissionNum", []):
        counts[row["difficulty"]] = row["count"]
    return {
        "username": user["username"],
        "avatar": user.get("profile", {}).get("userAvatar", ""),
        "totals": counts,
    }


def lc_stats(username):
    """Fetch full stats (totals + contest info) for a user."""
    profile = lc_request(LC_PROFILE_QUERY, {"username": username})
    time.sleep(LC_DELAY)
    contest = lc_request(LC_CONTEST_QUERY, {"username": username})
    time.sleep(LC_DELAY)

    result = {"username": username, "totals": {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0}, "avatar": "", "contest": None}

    if profile:
        user = (profile.get("data") or {}).get("matchedUser")
        if user:
            result["avatar"] = user.get("profile", {}).get("userAvatar", "")
            for row in user.get("submitStats", {}).get("acSubmissionNum", []):
                result["totals"][row["difficulty"]] = row["count"]

    if contest:
        ranking = (contest.get("data") or {}).get("userContestRanking")
        if ranking:
            result["contest"] = {
                "attended": ranking.get("attendedContestsCount", 0),
                "rating": round(ranking.get("rating", 0)),
                "global_rank": ranking.get("globalRanking", 0),
                "top_pct": round(ranking.get("topPercentage", 0), 1),
            }

    return result


# ── Discord ─────────────────────────────────────────────────────────────────

def dapi(url, method="GET", token=None, body=None):
    headers = {"User-Agent": DISCORD_UA}
    if token:
        headers["Authorization"] = f"Bot {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as e:
        return None


def resolve_channels(token):
    chans = dapi(f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels", token=token)
    for c in chans:
        if c["type"] == 0 and c["name"] in CHANNEL_NAMES:
            CHANNEL_NAMES[c["name"]] = c["id"]


def react(token, channel_id, message_id, emoji):
    import urllib.parse
    encoded = urllib.parse.quote(emoji)
    dapi(f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
         method="PUT", token=token)


def fetch_messages(token, channel_id, after="0"):
    msgs = []
    while True:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=100&after={after}"
        batch = dapi(url, token=token)
        if not batch:
            break
        msgs.extend(batch)
        after = batch[0]["id"]
        if len(batch) < 100:
            break
        time.sleep(0.3)
    return msgs


# ── State ───────────────────────────────────────────────────────────────────

def load(name, default=None):
    try:
        with open(os.path.join(DATA_DIR, name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}


def save(name, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    p = os.path.join(DATA_DIR, name) + ".tmp"
    with open(p, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(p, os.path.join(DATA_DIR, name))


# ── Poll registrations ──────────────────────────────────────────────────────

USERNAME_RE = re.compile(r"^\s*([A-Za-z0-9_\-]{2,40})\s*$")


def cmd_poll():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("DISCORD_BOT_TOKEN required")
    resolve_channels(token)
    reg_id = CHANNEL_NAMES.get("register")
    if not reg_id:
        sys.exit("#register channel not found")

    members = load("members.json", {})
    processed = load("processed_ids.json", [])
    seen = set(processed)

    msgs = fetch_messages(token, reg_id)
    new_count = 0

    for m in msgs:
        mid = m["id"]
        if mid in seen:
            continue
        seen.add(mid)
        processed.append(mid)

        # Skip bot messages
        if m.get("author", {}).get("bot"):
            continue

        content = (m.get("content") or "").strip()
        match = USERNAME_RE.match(content)
        if not match:
            continue

        lc_username = match.group(1)
        discord_id = m["author"]["id"]
        discord_name = m["author"].get("global_name") or m["author"]["username"]

        # Check if already registered
        already = False
        for existing in members.values():
            if existing.get("lc_username", "").lower() == lc_username.lower():
                already = True
                break

        if already:
            react(token, reg_id, mid, "\u274C")  # ❌
            continue

        # Validate against LeetCode
        profile = lc_validate(lc_username)
        if not profile:
            react(token, reg_id, mid, "\u274C")  # ❌
            continue

        # Store member
        members[discord_id] = {
            "lc_username": profile["username"],
            "display_name": discord_name,
            "avatar": profile["avatar"],
            "totals": profile["totals"],
            "registered": datetime.now(IST).strftime("%Y-%m-%d"),
        }
        react(token, reg_id, mid, "\u2705")  # ✅
        new_count += 1
        print(f"Registered: {discord_name} -> {profile['username']}")

    # Trim processed_ids to last 2000
    if len(processed) > 2000:
        processed = processed[-2000:]

    save("members.json", members)
    save("processed_ids.json", processed)
    print(f"Poll done: {new_count} new registrations, {len(members)} total members")


# ── Post leaderboard ────────────────────────────────────────────────────────

def cmd_board():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    webhook = os.environ.get("LEADERBOARD_WEBHOOK_URL")
    if not token:
        sys.exit("DISCORD_BOT_TOKEN required")
    if not webhook:
        sys.exit("LEADERBOARD_WEBHOOK_URL required")
    resolve_channels(token)

    members = load("members.json", {})
    if not members:
        body = {
            "username": "Leaderboard",
            "embeds": [{
                "title": "LeetCode Leaderboard",
                "description": "No one registered yet.\nType your LeetCode username in #register to join.",
                "color": 0x95A5A6,
            }],
            "allowed_mentions": {"parse": []},
        }
        dapi(webhook, method="POST", body=body)
        print("No members — posted empty board")
        return

    # Fetch stats for all members (with rate limiting)
    rows = []
    for i, (did, member) in enumerate(members.items()):
        lc_user = member["lc_username"]
        print(f"[{i+1}/{len(members)}] Fetching {lc_user}...")
        stats = lc_stats(lc_user)

        # Update stored totals
        member["totals"] = stats["totals"]
        member["avatar"] = stats["avatar"]

        total = stats["totals"]["All"]
        easy = stats["totals"]["Easy"]
        medium = stats["totals"]["Medium"]
        hard = stats["totals"]["Hard"]

        contest_line = ""
        if stats["contest"]:
            c = stats["contest"]
            contest_line = f" · {c['rating']} rating"

        rows.append({
            "name": member.get("display_name", lc_user),
            "lc_username": lc_user,
            "avatar": stats["avatar"],
            "total": total,
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "contest": contest_line,
        })

    # Sort by total solved descending, then easy/medium/hard
    rows.sort(key=lambda r: (-r["total"], -r["hard"], -r["medium"], -r["easy"]))

    # Build embed
    now = datetime.now(IST)
    lines = []
    medals = ["\U0001F947", "\U0001F948", "\U0001F949"]  # 🥇🥈🥉
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        lines.append(
            f"{medal} **{r['name']}** — **{r['total']}** solved "
            f"({r['easy']}E / {r['medium']}M / {r['hard']}H){r['contest']}"
        )

    # Split if too long for one embed
    description = "\n".join(lines)
    if len(description) > 4000:
        description = description[:3997] + "..."

    embed = {
        "author": {"name": "LeetCode Leaderboard"},
        "title": now.strftime("%B %d, %Y"),
        "description": description,
        "color": 0x5865F2,
        "footer": {"text": f"{len(rows)} members · updates daily at 06:00 IST · register in #register"},
    }

    if rows and rows[0]["avatar"]:
        embed["thumbnail"] = {"url": rows[0]["avatar"]}

    body = {
        "username": "Leaderboard",
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }
    dapi(webhook, method="POST", body=body)

    # Save updated totals
    save("members.json", members)
    print(f"Board posted: {len(rows)} members")


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("poll", "board"):
        print("usage: leaderboard.py [poll|board]")
        sys.exit(2)
    {"poll": cmd_poll, "board": cmd_board}[sys.argv[1]]()
