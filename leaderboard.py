"""Local LeetCode leaderboard for Mission Faang.

Modes:
    python3 leaderboard.py poll   -> process new "!register"/"!remove" messages in #leaderboard
    python3 leaderboard.py board  -> snapshot totals and post the weekly board
    python3 leaderboard.py daily  -> seed morning baseline / post evening daily board

State lives in data/ and is committed back to the repo by GitHub Actions,
so there is no server and nothing to host.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://discord.com/api/v10"
LC_GRAPHQL = "https://leetcode.com/graphql"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

IST = timezone(timedelta(hours=5, minutes=30))
LC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DISCORD_UA = "MFGrindBot/1.0 (github.com/aryanbatras/leetcode-daily-discord)"

REGISTER_RE = re.compile(r"^\s*!register\s+([A-Za-z0-9_\-]{1,40})\s*$", re.I)
REMOVE_RE = re.compile(r"^\s*!remove\s*$", re.I)

LC_QUERY = """query userData($username: String!) {
    matchedUser(username: $username) {
        username
        profile {
            userAvatar
        }
        submitStats: submitStatsGlobal {
            acSubmissionNum {
                difficulty
                count
            }
        }
    }
}"""


def path(name):
    return os.path.join(DATA_DIR, name)


def load_json(name, default):
    try:
        with open(path(name), encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def save_json(name, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
    os.replace(tmp, path(name))


def request(url, method="GET", token=None, body=None):
    headers = {"User-Agent": DISCORD_UA}
    if token:
        headers["Authorization"] = f"Bot {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        print(f"{method} {url} -> {exc.code}: {detail}")
        return exc.code, None


def lc_profile(username):
    """Return matched-user dict or None if the LeetCode username does not exist."""
    payload = {"query": LC_QUERY, "variables": {"username": username}}
    req = urllib.request.Request(
        LC_GRAPHQL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Referer": "https://leetcode.com", "User-Agent": LC_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    return (data.get("data") or {}).get("matchedUser")


def lc_totals(matched):
    counts = {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0}
    for row in matched["submitStats"]["acSubmissionNum"]:
        counts[row["difficulty"]] = row["count"]
    return counts


def today_ist():
    return datetime.now(IST).strftime("%Y-%m-%d")


def week_start_ist(today=None):
    now = datetime.now(IST) if today is None else datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=IST)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%Y-%m-%d")


def take_snapshot(members, snapshots, overwrite=True, sleep_s=0.0):
    """Fetch current totals for every member and store them under today's date.

    overwrite=False keeps the earliest value already stored for today — used by
    the morning seed so the daily board measures the whole day's grind.
    sleep_s paces LeetCode calls (one member every ~2s) to stay under rate limits.
    """
    day = today_ist()
    stale_cutoff = (datetime.now(IST) - timedelta(days=21)).strftime("%Y-%m-%d")
    for key, member in members.items():
        matched = lc_profile(member["lc_username"])
        if not matched:
            continue
        if sleep_s:
            time.sleep(sleep_s)
        totals = lc_totals(matched)
        member["avatar"] = matched.get("profile", {}).get("userAvatar")
        store = snapshots.setdefault(member.get("discord_id", key), {})
        if overwrite or day not in store:
            store[day] = totals
    for uid in list(snapshots):
        snapshots[uid] = {
            d: t for d, t in snapshots[uid].items() if d >= stale_cutoff or d == day
        }
        if not snapshots[uid]:
            del snapshots[uid]


def baseline_for(snapshots, uid, week_start, day):
    days = sorted(snapshots.get(uid, {}))
    prior = [d for d in days if week_start <= d <= day]
    if prior:
        return snapshots[uid][prior[0]]
    if days:  # registered mid-week: their registration snapshot is the baseline
        return snapshots[uid][days[0]]
    return {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0}


def cmd_board():
    token_webhook = os.environ.get("LEADERBOARD_WEBHOOK_URL")
    if not token_webhook:
        print("LEADERBOARD_WEBHOOK_URL is not set")
        sys.exit(1)

    members = load_json("members.json", {})
    snapshots = load_json("snapshots.json", {})
    if not members:
        body = {
            "username": "Weekly Board",
            "embeds": [
                {
                    "title": "Weekly Board",
                    "description": (
                        "No one has registered yet.\n"
                        "Type `!register <your-leetcode-username>` in this channel "
                        "and you're in."
                    ),
                    "color": 0x95A5A6,
                }
            ],
        }
    else:
        take_snapshot(members, snapshots)
        day = today_ist()
        start = week_start_ist(day)
        rows = []
        for key, member in members.items():
            uid = member.get("discord_id", key)
            snaps = snapshots.get(uid, {})
            current = snaps.get(day)
            if not current:
                continue
            base = baseline_for(snapshots, uid, start, day)
            rows.append(
                {
                    "name": member["display_name"],
                    "delta": current["All"] - base["All"],
                    "easy": current["Easy"] - base["Easy"],
                    "medium": current["Medium"] - base["Medium"],
                    "hard": current["Hard"] - base["Hard"],
                    "total": current["All"],
                }
            )
        rows.sort(key=lambda r: (-r["delta"], -r["total"]))
        lines = []
        for i, r in enumerate(rows, 1):
            lines.append(
                f"**{i}.** {r['name']} — **+{r['delta']}** this week "
                f"({r['easy']}E / {r['medium']}M / {r['hard']}H) · {r['total']} total"
            )
        save_json("snapshots.json", snapshots)
        body = {
            "username": "Weekly Board",
            "allowed_mentions": {"parse": []},
            "embeds": [
                {
                    "author": {"name": "LeetCode Weekly Board"},
                    "title": f"Week of {start} → {day}",
                    "description": "\n".join(lines)[:4000],
                    "color": 0x5865F2,
                    "footer": {
                        "text": "Resets every Monday · join with !register <username>"
                    },
                }
            ],
        }

    status, _ = request(token_webhook, method="POST", body=body)
    if status not in (200, 204):
        print(f"Webhook returned {status}")
        sys.exit(1)
    print(f"Weekly board posted ({len(members)} members)")


def cmd_daily():
    """Morning: seed today's baseline (first write wins). Evening: post the daily board."""
    token_webhook = os.environ.get("LEADERBOARD_WEBHOOK_URL")
    if not token_webhook:
        print("LEADERBOARD_WEBHOOK_URL is not set")
        sys.exit(1)

    now = datetime.now(IST)
    mode = os.environ.get("MF_DAILY_MODE") or ("seed" if now.hour < 12 else "post")
    day = today_ist()
    members = load_json("members.json", {})
    snapshots = load_json("snapshots.json", {})

    zero = {
        "title": f"Daily Grind — {day}",
        "description": (
            "No one has registered yet.\n"
            "Type `!register <your-leetcode-username>` in this channel "
            "and show up on tomorrow's board."
        ),
        "color": 0x95A5A6,
    }

    rows = []
    if members:
        if mode == "seed":
            take_snapshot(members, snapshots, overwrite=False, sleep_s=2.0)
            print(f"seeded baseline for {len(members)} members (2s pacing)")
        else:
            baselines = {}
            for key, member in members.items():
                uid = member.get("discord_id", key)
                baselines[uid] = dict(snapshots.get(uid, {}).get(day) or {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0})
            take_snapshot(members, snapshots, overwrite=True, sleep_s=2.0)
            for key, member in members.items():
                uid = member.get("discord_id", key)
                current = snapshots.get(uid, {}).get(day)
                if not current:
                    continue
                base = baselines[uid]
                delta = current["All"] - base["All"]
                if delta < 0:
                    continue  # re-registered mid-day; don't punish
                rows.append({
                    "name": member["display_name"],
                    "delta": delta,
                    "easy": current["Easy"] - base["Easy"],
                    "medium": current["Medium"] - base["Medium"],
                    "hard": current["Hard"] - base["Hard"],
                    "total": current["All"],
                })
        save_json("snapshots.json", snapshots)
        save_json("members.json", members)

    if mode == "seed":
        return

    rows.sort(key=lambda r: (-r["delta"], -r["total"]))
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    crowned = []
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 and r["delta"] > 0 else ""
        if medal:
            crowned.append(r["name"])
        lines.append(
            f"{medal or '**' + str(i + 1) + '.**'} {r['name']} — **+{r['delta']}** today "
            f"({r['easy']}E / {r['medium']}M / {r['hard']}H) · {r['total']} total"
        )
    if not lines:
        lines.append("Quiet day. The board resets at midnight — tomorrow is unwritten.")
    elif crowned:
        lines.append(f"\n👑 respect to {' · '.join(crowned)} — see the rest of you here tomorrow.")
    body = {
        "username": "Daily Board",
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "author": {"name": "LeetCode Daily Grind"},
            "title": f"Solved today — {day}",
            "description": "\n".join(lines)[:4000],
            "color": 0xF1C40F,
            "footer": {"text": "measured midnight to midnight IST · join with !register <username>"},
        }],
    }
    status, _ = request(token_webhook, method="POST", body=body)
    if status not in (200, 204):
        print(f"Webhook returned {status}")
        sys.exit(1)
    print(f"Daily board posted ({len(rows)} rows, mode={mode})")


def cmd_poll():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN is not set — skipping poll (set the secret to activate)")
        return

    state = load_json("state.json", {})
    channel_id = state.get("channel_id")
    if not channel_id:
        print("state.json missing channel_id")
        sys.exit(1)

    after = state.get("last_message_id", "0")
    messages = None
    for attempt in range(3):
        url = f"{API}/channels/{channel_id}/messages?after={after}&limit=100"
        status, messages = request(url, token=token)
        if status == 200:
            break
        print(f"Read failed (attempt {attempt + 1}/3, status {status}); backing off")
        import time

        time.sleep(3 * (attempt + 1))
        messages = None
    if messages is None:
        print("Giving up this cycle; will retry next run")
        return

    messages.reverse()  # oldest first so last_message_id advances correctly
    members = load_json("members.json", {})
    snapshots = load_json("snapshots.json", {})
    changed = False

    for msg in messages:
        state["last_message_id"] = msg["id"]
        author = msg["author"]
        if author.get("bot"):
            continue
        content = msg.get("content", "")
        reg = REGISTER_RE.match(content)
        rem = REMOVE_RE.match(content)
        uid = str(author["id"])
        display = author.get("global_name") or author.get("username")

        if reg:
            username = reg.group(1)
            matched = lc_profile(username)
            if matched:
                existing = members.get(uid)
                members[uid] = {
                    "discord_id": uid,
                    "display_name": display,
                    "lc_username": matched["username"],
                    "avatar": matched.get("profile", {}).get("userAvatar"),
                    "registered_at": datetime.now(IST).isoformat(),
                }
                snapshots.setdefault(uid, {})[today_ist()] = lc_totals(matched)
                changed = True
                totals = lc_totals(matched)
                verb = (
                    f"Updated your registration to **{matched['username']}**"
                    if existing and existing["lc_username"] != matched["username"]
                    else f"You're on the board as **{matched['username']}**"
                )
                request(
                    f"{API}/channels/{channel_id}/messages",
                    method="POST",
                    token=token,
                    body={
                        "content": (
                            f"<@{uid}> {verb}.\n"
                            f"Lifetime: **{totals['All']} solved** "
                            f"({totals['Easy']}E / {totals['Medium']}M / {totals['Hard']}H).\n"
                            "This week starts today. See you on the board at 08:00."
                        ),
                        "message_reference": {"message_id": msg["id"]},
                        "allowed_mentions": {"users": [uid]},
                    },
                )
                request(
                    f"{API}/channels/{channel_id}/messages/{msg['id']}"
                    f"/reactions/%E2%9C%85/@me",
                    method="PUT",
                    token=token,
                )
                print(f"Registered {display} -> {matched['username']}")
            else:
                request(
                    f"{API}/channels/{channel_id}/messages",
                    method="POST",
                    token=token,
                    body={
                        "content": f"<@{uid}> No LeetCode user called `{username}` — check the spelling and try again.",
                        "message_reference": {"message_id": msg["id"]},
                        "allowed_mentions": {"users": [uid]},
                    },
                )
                print(f"Rejected bad username '{username}' for {display}")
        elif rem:
            if uid in members:
                del members[uid]
                snapshots.pop(uid, None)
                changed = True
                request(
                    f"{API}/channels/{channel_id}/messages/{msg['id']}"
                    f"/reactions/%F0%9F%91%8B/@me",
                    method="PUT",
                    token=token,
                )
                print(f"Removed {display}")

    save_json("state.json", state)
    if changed:
        save_json("members.json", members)
        save_json("snapshots.json", snapshots)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("poll", "board", "daily"):
        print("usage: leaderboard.py [poll|board|daily]")
        sys.exit(2)
    {"poll": cmd_poll, "board": cmd_board, "daily": cmd_daily}[sys.argv[1]]()
