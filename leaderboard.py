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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

CFG = load_config()
GUILD_ID = CFG["guild_id"]
CHANNEL_NAMES = {k: None for k in CFG["channels"]}  # resolved at runtime

IST = timezone(timedelta(hours=5, minutes=30))
LC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DISCORD_UA = CFG["bot"]["ua"]
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

LC_RECENT_SUBS_QUERY = """query recentAcSubmissions($username: String!, $limit: Int!) {
    recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
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
    """Fetch full stats (totals + contest + recent subs) for a user."""
    profile = lc_request(LC_PROFILE_QUERY, {"username": username})
    time.sleep(LC_DELAY)
    contest = lc_request(LC_CONTEST_QUERY, {"username": username})
    time.sleep(LC_DELAY)
    subs_data = lc_request(LC_RECENT_SUBS_QUERY, {"username": username, "limit": 50})
    time.sleep(LC_DELAY)

    result = {
        "username": username,
        "totals": {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0},
        "avatar": "",
        "contest": None,
        "recent_subs": [],
    }

    if profile:
        user = (profile.get("data") or {}).get("matchedUser")
        if user:
            result["avatar"] = user.get("profile", {}).get("userAvatar", "")
            for row in user.get("submitStats", {}).get("acSubmissionNum", []):
                result["totals"][row["difficulty"]] = row["count"]
    else:
        print(f"  WARNING: profile fetch failed for {username}")

    if contest:
        ranking = (contest.get("data") or {}).get("userContestRanking")
        if ranking:
            result["contest"] = {
                "attended": ranking.get("attendedContestsCount", 0),
                "rating": round(ranking.get("rating", 0)),
                "global_rank": ranking.get("globalRanking", 0),
                "top_pct": round(ranking.get("topPercentage", 0), 1),
            }
    else:
        print(f"  WARNING: contest fetch failed for {username}")

    if subs_data:
        raw_subs = (subs_data.get("data") or {}).get("recentAcSubmissionList") or []
        result["recent_subs"] = [
            {
                "id": s["id"],
                "title": s["title"],
                "titleSlug": s["titleSlug"],
                "timestamp": int(s["timestamp"]),
            }
            for s in raw_subs
        ]

    return result


def filter_subs_by_date(recent_subs, start_dt, end_dt):
    """Filter recent submissions to those between start_dt and end_dt (datetime, naive IST)."""
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    return [s for s in recent_subs if start_ts <= s["timestamp"] <= end_ts]


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


def post_register_message(token, channel_id, members):
    """Post the current members list + instructions."""
    embeds = []

    # Members list
    if members:
        lines = []
        for i, (did, m) in enumerate(members.items(), 1):
            lines.append(f"**{i}.** {m.get('display_name', m['lc_username'])} — `{m['lc_username']}`")
        desc = "\n".join(lines)
        if len(desc) > 4000:
            desc = desc[:3997] + "..."
        embeds.append({
            "title": f"Registered Members ({len(members)})",
            "description": desc,
            "color": 0x2ECC71,
        })
    else:
        embeds.append({
            "title": "Registered Members",
            "description": "*No one registered yet. Be the first!*",
            "color": 0x95A5A6,
        })

    # Instructions
    embeds.append({
        "title": "How to Register",
        "description": (
            "Type **only your LeetCode username** (e.g. `aryanbatra`) in this channel.\n"
            "The bot validates it daily and adds you to the board.\n\n"
            "**Rules:**\n"
            "• One message = one username\n"
            "• Just the username, no extra text\n"
            "• Alphanumeric, hyphens, underscores only\n"
            "• 2-40 characters"
        ),
        "color": 0x5865F2,
        "footer": {"text": "Auto-updated daily · leaderboard in #leaderboard"},
    })

    body = {
        "username": "Register Bot",
        "embeds": embeds,
        "allowed_mentions": {"parse": []},
    }
    dapi(f"https://discord.com/api/v10/channels/{channel_id}/messages",
         method="POST", token=token, body=body)


def cmd_poll():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN required")
    resolve_channels(token)
    reg_id = CHANNEL_NAMES.get("register")
    if not reg_id:
        sys.exit("#register channel not found")

    members = load("members.json", {})
    messages = fetch_messages(token, reg_id)

    # Skip if no messages at all
    if not messages:
        print("No messages in #register — skipping")
        return

    # Parse usernames from messages (skip bots, skip already registered)
    existing_lc = {m["lc_username"].lower() for m in members.values()}
    new_registrations = []

    for m in messages:
        if m.get("author", {}).get("bot"):
            continue
        content = (m.get("content") or "").strip()
        match = USERNAME_RE.match(content)
        if not match:
            continue

        lc_username = match.group(1)
        if lc_username.lower() in existing_lc:
            continue

        # Validate against LeetCode
        print(f"Validating: {lc_username}")
        profile = lc_validate(lc_username)
        if not profile:
            print(f"  Rejected: {lc_username} (not found on LeetCode)")
            continue

        # Store member
        discord_id = m["author"]["id"]
        discord_name = m["author"].get("global_name") or m["author"]["username"]
        members[discord_id] = {
            "lc_username": profile["username"],
            "display_name": discord_name,
            "avatar": profile["avatar"],
            "totals": profile["totals"],
            "registered": datetime.now(IST).strftime("%Y-%m-%d"),
        }
        existing_lc.add(lc_username.lower())
        new_registrations.append(discord_name)
        print(f"  Registered: {discord_name} -> {profile['username']}")

    # Save members
    save("members.json", members)

    if not new_registrations:
        print("No new valid usernames found — skipping channel refresh")
        return

    # Clear channel and post fresh list
    clear_channel(token, reg_id)
    post_register_message(token, reg_id, members)
    print(f"Refreshed #register: {len(new_registrations)} new, {len(members)} total")


# ── Post leaderboard ────────────────────────────────────────────────────────

def clear_leaderboard(token, channel_id):
    """Delete all messages in the leaderboard channel."""
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


def today_ist():
    return datetime.now(IST).strftime("%Y-%m-%d")


def week_start_ist(today=None):
    now = datetime.now(IST) if today is None else datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=IST)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%Y-%m-%d")


def post_webhook_embeds(webhook, embeds):
    """Post multiple embeds via webhook, splitting if needed."""
    for i in range(0, len(embeds), 5):
        chunk = embeds[i:i+5]
        body = {
            "username": "Leaderboard",
            "embeds": chunk,
            "allowed_mentions": {"parse": []},
        }
        dapi(webhook, method="POST", body=body)
        time.sleep(0.5)


def cmd_board():
    token = os.environ.get("DISCORD_TOKEN")
    webhook = os.environ.get("LEADERBOARD_WEBHOOK_URL", "https://discord.com/api/webhooks/1541814326556491778/_Sa-daohbVwSV6wMbT0xowNWe_NrBjy90hpre7HPR7XPG2nJmkOJGrRthfksz3xZSZDx")
    if not token:
        sys.exit("DISCORD_TOKEN required")
    resolve_channels(token)
    lb_id = CHANNEL_NAMES.get("leaderboard")
    if not lb_id:
        sys.exit("#leaderboard channel not found")

    members = load("members.json", {})
    snapshots = load("snapshots.json", {})
    now = datetime.now(IST)
    today = today_ist()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_start = week_start_ist(today)

    # Date boundaries (naive IST)
    yesterday_start = datetime.strptime(yesterday, "%Y-%m-%d").replace(tzinfo=IST)
    yesterday_end = yesterday_start + timedelta(days=1)
    week_start_dt = datetime.strptime(week_start, "%Y-%m-%d").replace(tzinfo=IST)
    today_end = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=IST) + timedelta(days=1)

    # ── Clear channel ──
    clear_leaderboard(token, lb_id)
    print("Cleared #leaderboard")

    if not members:
        body = {
            "username": "Leaderboard",
            "embeds": [{
                "title": "LeetCode Leaderboard",
                "description": "No one registered yet.\nType your LeetCode username in **#register** to join.",
                "color": 0x95A5A6,
            }],
            "allowed_mentions": {"parse": []},
        }
        dapi(webhook, method="POST", body=body)
        print("No members — posted empty board")
        return

    # ── Fetch stats for all members ──
    rows = []
    for i, (did, member) in enumerate(members.items()):
        lc_user = member["lc_username"]
        print(f"[{i+1}/{len(members)}] Fetching {lc_user}...")
        stats = lc_stats(lc_user)

        member["totals"] = stats["totals"]
        member["avatar"] = stats["avatar"]

        # Store daily snapshot for weekly tracking
        store = snapshots.setdefault(did, {})
        if today not in store:
            store[today] = dict(stats["totals"])

        # Get Monday baseline for weekly delta
        prior_days = sorted(d for d in store if week_start <= d <= today)
        if prior_days:
            baseline = store[prior_days[0]]
        else:
            baseline = store.get(today, stats["totals"])

        weekly_delta = stats["totals"]["All"] - baseline.get("All", 0)
        weekly_easy = stats["totals"]["Easy"] - baseline.get("Easy", 0)
        weekly_medium = stats["totals"]["Medium"] - baseline.get("Medium", 0)
        weekly_hard = stats["totals"]["Hard"] - baseline.get("Hard", 0)

        # Filter recent submissions by date
        daily_subs = filter_subs_by_date(stats["recent_subs"], yesterday_start, yesterday_end)
        weekly_subs = filter_subs_by_date(stats["recent_subs"], week_start_dt, today_end)

        rows.append({
            "name": member.get("display_name", lc_user),
            "lc_username": lc_user,
            "avatar": stats["avatar"],
            "total": stats["totals"]["All"],
            "easy": stats["totals"]["Easy"],
            "medium": stats["totals"]["Medium"],
            "hard": stats["totals"]["Hard"],
            "contest": stats["contest"],
            "weekly_delta": weekly_delta,
            "weekly_easy": weekly_easy,
            "weekly_medium": weekly_medium,
            "weekly_hard": weekly_hard,
            "daily_subs": daily_subs,
            "weekly_subs": weekly_subs,
        })

    # Save snapshots
    save("snapshots.json", snapshots)
    save("members.json", members)

    # ── Build embeds ──
    embeds = []
    medals = ["\U0001F947", "\U0001F948", "\U0001F949"]

    # --- Header ---
    embeds.append({
        "author": {"name": "LeetCode Leaderboard"},
        "title": f"\U0001F4CA {now.strftime('%B %d, %Y')}",
        "description": f"**{len(rows)}** registered members · Updated at **{now.strftime('%I:%M %p IST')}**",
        "color": 0x5865F2,
    })

    # --- All-Time Rankings (sorted by total) ---
    by_total = sorted(rows, key=lambda r: (-r["total"], -r["hard"], -r["medium"], -r["easy"]))
    lines = []
    for i, r in enumerate(by_total):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        contest = f" · {r['contest']['rating']} rating" if r["contest"] else ""
        lines.append(
            f"{medal} **{r['name']}** (`{r['lc_username']}`)\n"
            f"    **{r['total']}** solved — {r['easy']}E / {r['medium']}M / {r['hard']}H{contest}"
        )
    embeds.append({
        "title": "\U0001F3C6 All-Time Rankings",
        "description": "\n".join(lines)[:4000],
        "color": 0xF1C40F,
    })

    # --- Daily Grind (yesterday's solved problems) ---
    by_daily = sorted(rows, key=lambda x: -len(x["daily_subs"]))
    daily_lines = []
    for i, r in enumerate(by_daily):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        count = len(r["daily_subs"])
        if count > 0:
            problems = "\n".join(
                f"    \u2022 [{s['title']}](https://leetcode.com/problems/{s['titleSlug']}/)"
                for s in r["daily_subs"][:10]
            )
            extra = f"\n    ...and {count-10} more" if count > 10 else ""
            daily_lines.append(
                f"{medal} **{r['name']}** (`{r['lc_username']}`)\n"
                f"    **{count}** solved\n{problems}{extra}"
            )
        else:
            daily_lines.append(
                f"{medal} **{r['name']}** (`{r['lc_username']}`)\n"
                f"    No problems solved"
            )
    embeds.append({
        "title": f"\U0001F525 Daily Grind — {yesterday}",
        "description": "\n\n".join(daily_lines)[:4000] if daily_lines else "*No data*",
        "color": 0xE67E22,
    })

    # --- Weekly Grind (this week's solved + delta) ---
    by_weekly = sorted(rows, key=lambda r: (-len(r["weekly_subs"]), -r["weekly_delta"]))
    weekly_lines = []
    for i, r in enumerate(by_weekly):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        delta = r["weekly_delta"]
        delta_str = f"**+{delta}**" if delta > 0 else (f"**{delta}**" if delta < 0 else "0")
        sub_count = len(r["weekly_subs"])
        if sub_count > 0:
            problems = "\n".join(
                f"    \u2022 [{s['title']}](https://leetcode.com/problems/{s['titleSlug']}/)"
                for s in r["weekly_subs"][:5]
            )
            extra = f"\n    ...and {sub_count-5} more" if sub_count > 5 else ""
            weekly_lines.append(
                f"{medal} **{r['name']}** (`{r['lc_username']}`)\n"
                f"    {delta_str} this week ({sub_count} solved)\n{problems}{extra}"
            )
        else:
            weekly_lines.append(
                f"{medal} **{r['name']}** (`{r['lc_username']}`)\n"
                f"    {delta_str} this week"
            )
    embeds.append({
        "title": f"\U0001F4C8 Weekly Grind (since {week_start})",
        "description": "\n\n".join(weekly_lines)[:4000] if weekly_lines else "*No progress yet this week*",
        "color": 0x2ECC71,
    })

    # --- Contest Rankings (just rating) ---
    contest_rows = [r for r in rows if r["contest"]]
    if contest_rows:
        by_rating = sorted(contest_rows, key=lambda r: -r["contest"]["rating"])
        c_lines = []
        for i, r in enumerate(by_rating):
            medal = medals[i] if i < 3 else f"**{i+1}.**"
            c = r["contest"]
            c_lines.append(
                f"{medal} **{r['name']}** (`{r['lc_username']}`)\n"
                f"    **{c['rating']}** rating"
            )
        embeds.append({
            "title": "\U0001F3AE Contest Rankings",
            "description": "\n".join(c_lines),
            "color": 0x9B59B6,
        })

    # --- Footer ---
    embeds.append({
        "title": "\U00002753 How to Join",
        "description": "Type your LeetCode username in **#register** to get on the board.",
        "color": 0x95A5A6,
        "footer": {"text": "Resets weekly (Monday) · register in #register"},
    })

    post_webhook_embeds(webhook, embeds)
    print(f"Board posted: {len(rows)} members, {len(embeds)} embeds")


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("poll", "board"):
        print("usage: leaderboard.py [poll|board]")
        sys.exit(2)
    {"poll": cmd_poll, "board": cmd_board}[sys.argv[1]]()
