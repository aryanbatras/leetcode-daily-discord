"""Post every daily feed across all MF Grind channels."""

import json
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta

from mfcommon import (
    DIFFICULTY_COLORS,
    DESCRIPTION_LIMIT,
    FIELD_VALUE_LIMIT,
    days_since,
    html_to_discord,
    http_json,
    lc_graphql,
    load_json,
    save_json,
    seeded_index,
    send_embed,
    truncate,
)

DATA = "data"
LAUNCH_DAY = (2026, 8, 24)
IST = timezone(timedelta(hours=5, minutes=30))
GENERAL_CHANNEL_ID = 1541028380655231118
FOCUS_ROOM_ID = 1541028380655231119

TOPICS = [
    "array", "string", "hash-table", "two-pointers", "sliding-window",
    "prefix-sum", "binary-search", "stack", "monotonic-stack", "queue",
    "heap-priority-queue", "linked-list", "tree", "trie", "graph",
    "union-find", "backtracking", "greedy", "dynamic-programming",
    "bit-manipulation", "math", "matrix", "sorting", "design",
]
BANDS = [800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900]
CSES_SECTIONS = [
    "Introductory Problems", "Sorting and Searching", "Dynamic Programming",
    "Graph Algorithms", "Range Queries", "Tree Algorithms", "Mathematics",
    "String Algorithms", "Geometry", "Advanced Techniques", "Additional Problems",
]
SUBJECTS = [
    ("operating-systems", "Operating Systems"),
    ("computer-networks", "Computer Networks"),
    ("dbms", "DBMS"),
]
CF_COLORS = [
    (999, 0x95A5A6),
    (1199, 0x2ECC71),
    (1399, 0x3498DB),
    (1599, 0x9B59B6),
    (1799, 0xE67E22),
    (99999, 0xE74C3C),
]

_RATINGS_CACHE = None


def ratings():
    global _RATINGS_CACHE
    if _RATINGS_CACHE is None:
        _RATINGS_CACHE = load_json(f"{DATA}/ratings.json")
    return _RATINGS_CACHE


def cf_color(rating):
    for cap, color in CF_COLORS:
        if rating <= cap:
            return color
    return 0x95A5A6


def learn_lines(slug, frontend_id):
    lines = []
    shot = load_json(f"{DATA}/screenshots.json").get(str(frontend_id))
    if shot:
        lines.append(f"[Editorial screenshot]({shot})")
    lines.append(f"[LeetCode editorials](https://leetcode.com/problems/{slug}/solutions/)")
    vid = load_json(f"{DATA}/neetcode_map.json").get(slug)
    if vid:
        lines.append(f"[NeetCode video]({vid['youtube']})")
    lines.append(
        "Reference code (spoilers): "
        f"[C++](https://raw.githubusercontent.com/kamyu104/LeetCode-Solutions/master/C++/{slug}.cpp)"
        " · "
        f"[Python](https://raw.githubusercontent.com/kamyu104/LeetCode-Solutions/master/Python/{slug}.py)"
    )
    return "\n".join(lines)


def learn_field(slug, frontend_id):
    return {"name": "Learn", "value": truncate(learn_lines(slug, frontend_id), FIELD_VALUE_LIMIT, "…")}


def statement_embed(q, footer):
    difficulty = q["difficulty"]
    url = f"https://leetcode.com/problems/{q['titleSlug']}/"
    embed = {
        "author": {"name": "LeetCode"},
        "title": f"{q['questionFrontendId']}. {q['title']}",
        "url": url,
        "color": DIFFICULTY_COLORS.get(difficulty, 0x95A5A6),
    }
    if q.get("content"):
        body = html_to_discord(q["content"])
        embed["description"] = truncate(
            body, DESCRIPTION_LIMIT, "\n\n*Full statement at the link above.*"
        )
    topics = ", ".join(t["name"] for t in q.get("topicTags", []))
    fields = [
        {"name": "Difficulty", "value": difficulty, "inline": True},
        {"name": "Acceptance", "value": f"{q.get('acRate', 0):.1f}%", "inline": True},
        {"name": "Rating", "value": str(ratings().get(q["titleSlug"], "unrated")), "inline": True},
    ]
    if topics:
        fields.append({"name": "Topics", "value": topics[:FIELD_VALUE_LIMIT]})
    fields.append(learn_field(q["titleSlug"], q["questionFrontendId"]))
    embed["fields"] = fields
    embed["footer"] = {"text": footer}
    return embed


TOPIC_QUERY_TOTAL = """
query total($f: QuestionListFilterInput!) {
    problemsetQuestionList: questionList(categorySlug: "", limit: 1, skip: 0, filters: $f) {
        totalNum
    }
}"""

TOPIC_QUERY_PICK = """
query pick($f: QuestionListFilterInput!, $skip: Int!) {
    problemsetQuestionList: questionList(categorySlug: "", limit: 1, skip: $skip, filters: $f) {
        questions: data { titleSlug difficulty isPaidOnly }
    }
}"""

QUESTION_QUERY = """
query detail($slug: String!) {
    question(titleSlug: $slug) {
        questionFrontendId
        title
        titleSlug
        content
        difficulty
        acRate
        topicTags { name }
    }
}"""


def recent_set(state, key, limit=40):
    arr = state.setdefault(key, [])
    del arr[:-limit]
    return set(arr)


def post_topics(hooks, digest):
    path = f"{DATA}/topic_state.json"
    state = load_json(path) if os.path.exists(path) else {}
    for slug in TOPICS:
        hook = hooks.get(slug)
        if not hook:
            continue
        time.sleep(0.6)
        try:
            variables = {"f": {"tags": [slug]}}
            total = lc_graphql(TOPIC_QUERY_TOTAL, variables)["data"]["problemsetQuestionList"]["totalNum"]
            recent = recent_set(state, slug)
            chosen = None
            base = seeded_index(f"lc-topic:{slug}", total)
            for offset in range(6):
                idx = (base + offset * 7) % total
                picked = lc_graphql(
                    TOPIC_QUERY_PICK, {"f": {"tags": [slug]}, "skip": idx}
                )["data"]["problemsetQuestionList"]["questions"]
                if not picked:
                    continue
                cand = picked[0]
                if cand["isPaidOnly"] or cand["titleSlug"] in recent:
                    continue
                chosen = cand
                break
            if not chosen:
                print(f"{slug}: no eligible problem, skipping")
                continue
            detail = lc_graphql(QUESTION_QUERY, {"slug": chosen["titleSlug"]})["data"]["question"]
            embed = statement_embed(detail, "random daily drill — solve before peeking")
            if send_embed(hook, embed, username=f"lc {slug.replace('-', ' ')}"):
                digest.append(("leetcode/" + slug, detail["title"], detail["difficulty"]))
                state[slug].append(chosen["titleSlug"])
                print(f"{slug}: posted {chosen['titleSlug']}")
        except Exception as exc:
            print(f"{slug}: FAILED {exc}")
    save_json(path, state)


def post_codeforces(hooks, digest):
    problems = load_json(f"{DATA}/cf_problems.json")
    by_band = {}
    for p in problems:
        by_band.setdefault(p["rating"], []).append(p)
    path = f"{DATA}/cf_state.json"
    state = load_json(path) if os.path.exists(path) else {}
    used = set(state.setdefault("used", []))
    for band in BANDS:
        hook = hooks.get(f"cf-{band}")
        if not hook:
            continue
        candidates = by_band.get(band, [])
        fresh = [p for p in candidates if f"{p['contestId']}{p['index']}" not in used]
        pool = fresh or candidates
        problem = pool[seeded_index(f"cf-{band}", len(pool))] if fresh else random.choice(pool)
        tags = ", ".join(problem["tags"][:6])
        embed = {
            "author": {"name": "Codeforces"},
            "title": f"{problem['name']} ({problem['contestId']}{problem['index']})",
            "url": f"https://codeforces.com/problemset/problem/{problem['contestId']}/{problem['index']}",
            "color": cf_color(band),
            "description": (
                f"A **{band}**-rated drill. Timebox: {max(20, (band - 700) // 10)} minutes, "
                "then editorial only after a serious attempt."
            ),
            "fields": [
                {"name": "Rating", "value": str(band), "inline": True},
                {"name": "Solved by", "value": f"{problem.get('solvedCount', 0):,}", "inline": True},
                {"name": "Tags", "value": truncate(tags or "hidden on purpose", FIELD_VALUE_LIMIT, "…")},
            ],
            "footer": {"text": "codeforces daily · stay in your growth band"},
        }
        if send_embed(hook, embed, username=f"codeforces {band}"):
            digest.append((f"codeforces/{band}", problem["name"], str(band)))
            used.add(f"{problem['contestId']}{problem['index']}")
            print(f"cf-{band}: posted {problem['name']}")
    state["used"] = list(used)[-500:]
    save_json(path, state)


def create_focus_event():
    """Keep exactly one upcoming 'night grind' event scheduled: tomorrow 21:00 IST."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        return
    import urllib.request
    import urllib.error

    tomorrow = datetime.now(IST) + timedelta(days=1)
    start = tomorrow.replace(hour=21, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    start_iso = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def call(method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"https://discord.com/api/v10{path}", method=method, data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {token}",
                "User-Agent": "MFGrindBot/1.0 (+https://github.com/aryanbatras/leetcode-daily-discord)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except Exception as exc:
            print("focus event api failed:", exc)
            return None

    existing = call("GET", f"/guilds/1541028379598397452/scheduled-events") or []
    if isinstance(existing, list) and any(
        e.get("scheduled_start_time", "").startswith(start_iso[:10]) for e in existing
    ):
        print("focus event: already covered for", start_iso[:10])
        return
    created = call("POST", "/guilds/1541028379598397452/scheduled-events", {
        "name": "night grind - silent focus",
        "description": (
            "one hour, cameras off, phones down. show up, pick your daily problem, "
            "disappear into it."
        ),
        "scheduled_start_time": start_iso,
        "scheduled_end_time": end_iso,
        "entity_type": 2,
        "channel_id": FOCUS_ROOM_ID,
        "privacy_level": 2,
    })
    if isinstance(created, dict) and created.get("id"):
        print("focus event created:", created["id"])


def post_cses(hooks, digest):
    tasks = load_json(f"{DATA}/cses.json")
    by_section = {}
    for t in tasks:
        by_section.setdefault(t["category"], []).append(t)
    day = days_since(*LAUNCH_DAY)
    for section in CSES_SECTIONS:
        hook = hooks.get(f"cses-{section.lower().replace(' ', '-')}")
        if not hook:
            continue
        items = by_section.get(section, [])
        if not items:
            continue
        task = items[day % len(items)]
        pos = items.index(task) + 1
        embed = {
            "author": {"name": f"CSES — {section}"},
            "title": f"Task {task['id']} — {task['name']}",
            "url": f"https://cses.fi/problemset/task/{task['id']}",
            "color": 0x3498DB,
            "description": "No editorials until you have a verdict. These build technique quietly.",
            "fields": [
                {"name": "Position", "value": f"{pos}/{len(items)}", "inline": True},
                {"name": "Section cycle", "value": f"day {day % len(items) + 1} of {len(items)}", "inline": True},
            ],
            "footer": {"text": "cses · classic algorithmic gym"},
        }
        if send_embed(hook, embed, username=f"cses {section.lower()}"):
            digest.append((f"cses/{section.lower().replace(' ', '-')}", task["name"], section))
            print(f"cses[{section}]: posted {task['id']} {task['name']}")


TRACKS = [
    ("blind-75", "blind75.json", "Blind 75", "the interview canon — smallest list with maximum coverage"),
    ("neetcode-150", "neetcode150.json", "NeetCode 150", "pattern-first prep across all major topics"),
    ("striver-a2z", "a2z.json", "Striver A2Z", "zero-to-advanced DSA path, strictly in order"),
]


def post_tracks(hooks, digest):
    for key, datafile, title, blurb in TRACKS:
        hook = hooks.get(key)
        if not hook:
            continue
        rows = load_json(f"{DATA}/{datafile}")
        idx = days_since(*LAUNCH_DAY) % len(rows)
        row = rows[idx]
        leetcode_url = row.get("leetcode") or ""
        if leetcode_url.startswith("/"):
            leetcode_url = "https://leetcode.com" + leetcode_url
        desc_lines = [blurb + "."]
        if row.get("article"):
            desc_lines.append(f"[Concept article]({row['article']})")
        if row.get("youtube"):
            desc_lines.append(f"[Video solution]({row['youtube']})")
        embed = {
            "author": {"name": f"{title} Track"},
            "title": row["name"],
            "url": leetcode_url or None,
            "color": DIFFICULTY_COLORS.get(row.get("difficulty"), 0x95A5A6),
            "description": truncate("\n".join(desc_lines), DESCRIPTION_LIMIT, ""),
            "fields": [
                {"name": "Difficulty", "value": row.get("difficulty") or "—", "inline": True},
                {"name": "Day", "value": f"{idx + 1}/{len(rows)}", "inline": True},
            ],
            "footer": {"text": f"tracks/{key} · solve today's, stay on pace"},
        }
        if send_embed(hook, embed, username=f"{title} track"):
            digest.append((key, row["name"], row.get("difficulty") or ""))
            print(f"{key}: posted #{idx + 1} {row['name']}")


def post_subjects(hooks, digest):
    subjects = load_json(f"{DATA}/core_subjects.json")
    day = days_since(*LAUNCH_DAY)
    for key, subject in SUBJECTS:
        hook = hooks.get(key)
        if not hook:
            continue
        qs = subjects.get(subject, [])
        if not qs:
            continue
        qa = qs[day % len(qs)]
        embed = {
            "author": {"name": f"{subject} — Interview Drill"},
            "title": truncate(qa["q"], 250, "…"),
            "color": 0x16A085,
            "description": (
                "Say your answer out loud first, structure it, then research the hint. "
                "Interviews reward organized thinking more than memorized answers."
            ),
            "fields": [
                {"name": "Hint (after you try)", "value": truncate(qa["hint"], FIELD_VALUE_LIMIT, "…")},
                {"name": "Cycle", "value": f"Q{day % len(qs) + 1}/{len(qs)}", "inline": True},
            ],
            "footer": {"text": f"tracks/{key} · full question bank cycles every {len(qs)} days"},
        }
        if send_embed(hook, embed, username=f"{subject} drill"):
            digest.append((key, qa["q"], subject))
            print(f"{key}: posted {qa['q'][:60]}")


def post_system_design(hooks, digest):
    doc = load_json(f"{DATA}/system_design.json")
    day = days_since(*LAUNCH_DAY)
    feeds = [("low-level-design", "low-level design", "LLD"), ("high-level-design", "high-level design", "HLD")]
    for key, name, label in feeds:
        hook = hooks.get(key)
        if not hook:
            continue
        qs = doc[name]
        qa = qs[day % len(qs)]
        embed = {
            "author": {"name": f"{label} — Design Interview"},
            "title": truncate(qa["q"], 250, "…"),
            "color": 0x8E44AD,
            "description": (
                "Sketch components and trade-offs on paper first: entities, APIs, storage, "
                "bottlenecks. The hint tells you where the conversation should land."
            ),
            "fields": [
                {"name": "Key concepts", "value": truncate(qa["hint"], FIELD_VALUE_LIMIT, "…")},
                {"name": "Cycle", "value": f"Q{day % len(qs) + 1}/{len(qs)}", "inline": True},
            ],
            "footer": {"text": f"system-design/{key} · popular asks rotating daily"},
        }
        if send_embed(hook, embed, username=f"{label} drill"):
            digest.append((key, qa["q"], label))
            print(f"{key}: posted {qa['q'][:60]}")


CONTEST_QUERY = """
query {
    topTwoContests {
        title
        titleSlug
        startTime
        duration
    }
}"""


def fmt_ist(ts):
    return datetime.fromtimestamp(int(ts), tz=IST).strftime("%a %d %b, %I:%M %p IST")


def human_duration(seconds):
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def post_contests(hooks, digest):
    lines = []
    try:
        data = lc_graphql(CONTEST_QUERY)["data"]["topTwoContests"]
        now = time.time()
        for c in data:
            start = int(c["startTime"])
            end = start + int(c["duration"])
            status = "live now" if start <= now < end else fmt_ist(start)
            lines.append(
                f"**LeetCode** — [{c['title']}](https://leetcode.com/contest/{c['titleSlug']}/)\n"
                f"{status} · {human_duration(c['duration'])}"
            )
            digest.append(("#contests", f"LC {c['title']}", fmt_ist(start)))
    except Exception as exc:
        print(f"lc contests failed: {exc}")
    try:
        contests = http_json("https://codeforces.com/api/contest.list")["result"]
        upcoming = sorted(
            (c for c in contests if c.get("phase") == "BEFORE"),
            key=lambda c: c["startTimeSeconds"],
        )[:4]
        for c in upcoming:
            lines.append(
                f"**Codeforces** — [{c['name']}](https://codeforces.com/contests/{c['id']})\n"
                f"{fmt_ist(c['startTimeSeconds'])} · {human_duration(c.get('durationSeconds', 7200))}"
            )
            digest.append(("#contests", f"CF {c['name']}", fmt_ist(c["startTimeSeconds"])))
    except Exception as exc:
        print(f"cf contests failed: {exc}")
    if not lines:
        print("contests: nothing to post")
        return
    embed = {
        "author": {"name": "Upcoming Contests"},
        "title": "Put them on your calendar",
        "color": 0xF39C12,
        "description": "\n\n".join(lines)[:DESCRIPTION_LIMIT],
        "footer": {"text": "#contests · refreshed every morning"},
    }
    hook = hooks.get("contests")
    if hook and send_embed(hook, embed, username="Contest Radar"):
        print("contests: posted")


def post_digest(digest):
    """Single morning overview in #general so nobody drowns in channels."""
    if not digest:
        return
    groups = {}
    for channel, title, extra in digest:
        group = channel.split("/")[0]
        label = channel.split("/", 1)[1] if "/" in channel else channel
        groups.setdefault(group, []).append((label, title, extra))
    lines = ["**Today's menu** — everything fresh, pick your battles:\n"]
    for group, items in groups.items():
        shown = [f"`#{ch}` {truncate(t, 42, '…')}" for ch, t, e in items[:6]]
        more = f"\n*+{len(items) - 6} more*" if len(items) > 6 else ""
        lines.append(f"**{group}**\n" + "\n".join(shown) + more)
    lines.append(
        "*Want to discuss a card? Open a thread right under it — top-level stays a clean archive.*"
    )
    body = "\n\n".join(lines)
    payload = json.dumps({
        "content": truncate(body, 1900, "\n*full menus live in their channels*"),
        "allowed_mentions": {"parse": []},
    }).encode()
    import urllib.request

    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{GENERAL_CHANNEL_ID}/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bot {os.environ.get('DISCORD_BOT_TOKEN', '')}",
            "User-Agent": "MFGrindBot/1.0 (+https://github.com/aryanbatras/leetcode-daily-discord)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("digest posted:", resp.status == 200 or resp.status == 204)
    except Exception as exc:
        print("digest failed:", exc)


def main():
    hooks_env = os.environ.get("FEED_WEBHOOKS")
    if not hooks_env:
        print("FEED_WEBHOOKS is not set")
        sys.exit(1)
    hooks = json.loads(hooks_env)
    digest = []
    post_topics(hooks, digest)
    post_codeforces(hooks, digest)
    post_cses(hooks, digest)
    post_tracks(hooks, digest)
    post_subjects(hooks, digest)
    post_system_design(hooks, digest)
    post_contests(hooks, digest)
    post_digest(digest)
    create_focus_event()
    print("all feeds done")


if __name__ == "__main__":
    main()
