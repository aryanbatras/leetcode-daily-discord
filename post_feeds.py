"""Post every daily feed: topic dailies, codeforces, cp31, cses, tracks,
core subjects, contests. One run = one workflow invocation."""

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

TOPICS = [
    ("arrays", "array"),
    ("strings", "string"),
    ("binary-search", "binary-search"),
    ("linked-list", "linked-list"),
    ("stacks-and-queues", "stack"),
    ("trees", "tree"),
    ("graphs", "graph"),
    ("dynamic-programming", "dynamic-programming"),
]

CF_BANDS = [800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900]
CF_COLORS = [
    (999, 0x95A5A6),
    (1199, 0x2ECC71),
    (1399, 0x3498DB),
    (1599, 0x9B59B6),
    (1799, 0xE67E22),
    (99999, 0xE74C3C),
]


def cf_color(rating):
    for cap, color in CF_COLORS:
        if rating <= cap:
            return color
    return 0x95A5A6


def learn_lines(slug, frontend_id):
    """Editorial-first resource links. Code is clearly labeled spoilers."""
    lines = []
    shots = load_json(f"{DATA}/screenshots.json")
    shot = shots.get(str(frontend_id))
    if shot:
        lines.append(f"[Editorial screenshot]({shot})")
    lines.append(
        f"[LeetCode editorials](https://leetcode.com/problems/{slug}/solutions/)"
    )
    video_map = load_json(f"{DATA}/neetcode_map.json")
    vid = video_map.get(slug)
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
    return {
        "name": "Learn",
        "value": truncate(learn_lines(slug, frontend_id), FIELD_VALUE_LIMIT, "…"),
    }


def statement_embed(q, footer):
    """Rich card for a LeetCode question dict."""
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
        {"name": "Rating", "value": str(load_json(f'{DATA}/ratings.json').get(q["titleSlug"], "unrated")), "inline": True},
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
        totalNum
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


def state_path(name):
    return f"{DATA}/{name}"


def recent_list(state, key, limit):
    arr = state.setdefault(key, [])
    del arr[:-limit]
    return set(arr)


def post_topics(hooks):
    state_path_f = state_path("topic_state.json")
    state = load_json(state_path_f) if os.path.exists(state_path_f) else {}
    for key, tag_slug in TOPICS:
        hook = hooks.get(key)
        if not hook:
            continue
        try:
            variables = {"f": {"tags": [tag_slug]}}
            total = (
                lc_graphql(TOPIC_QUERY_TOTAL, variables)["data"]["problemsetQuestionList"][
                    "totalNum"
                ]
            )
            recent = recent_list(state, key, 40)
            chosen = None
            base = seeded_index(f"topic:{key}", total)
            for offset in range(6):
                idx = (base + offset * 7) % total
                picked = (
                    lc_graphql(TOPIC_QUERY_PICK, {"f": {"tags": [tag_slug]}, "skip": idx})[
                        "data"
                    ]["problemsetQuestionList"]["questions"]
                )
                if not picked:
                    continue
                candidate = picked[0]
                if candidate["isPaidOnly"] or candidate["titleSlug"] in recent:
                    continue
                chosen = candidate
                break
            if not chosen:
                print(f"{key}: no eligible problem found, skipping")
                continue
            detail = lc_graphql(QUESTION_QUERY, {"slug": chosen["titleSlug"]})["data"][
                "question"
            ]
            embed = statement_embed(detail, "random daily drill — solve before peeking")
            send_embed(hook, embed, username=f"{key.replace('-', ' ').title()} Daily")
            state[key].append(chosen["titleSlug"])
            print(f"{key}: posted {chosen['titleSlug']}")
        except Exception as exc:
            print(f"{key}: FAILED {exc}")
    save_json(state_path_f, state)


def post_codeforces(hooks):
    problems = load_json(f"{DATA}/cf_problems.json")
    band = CF_BANDS[datetime.now(IST).weekday()]
    candidates = [p for p in problems if p["rating"] == band]
    state_p = state_path("cf_state.json")
    state = load_json(state_p) if os.path.exists(state_p) else {}
    used = state.setdefault("used", [])
    fresh = [p for p in candidates if f"{p['contestId']}{p['index']}" not in set(used)]
    pool = fresh or candidates
    pick = seeded_index("cf", len(pool)) if fresh else random.randrange(len(pool))
    problem = pool[pick]
    tags = ", ".join(problem["tags"][:6])
    solved = problem.get("solvedCount", 0)
    embed = {
        "author": {"name": "Codeforces"},
        "title": f"{problem['name']} ({problem['contestId']}{problem['index']})",
        "url": f"https://codeforces.com/problemset/problem/{problem['contestId']}/{problem['index']}",
        "color": cf_color(band),
        "description": (
            f"Today's target band is **{band}**. Timebox yourself to "
            f"{max(20, (band - 700) // 10)} minutes, then read the editorial only after a real attempt."
        ),
        "fields": [
            {"name": "Rating", "value": str(band), "inline": True},
            {"name": "Solved by", "value": f"{solved:,}", "inline": True},
            {"name": "Tags", "value": truncate(tags or "hidden on purpose", FIELD_VALUE_LIMIT, "…")},
        ],
        "footer": {"text": "cp/codeforces · rotating band daily"},
    }
    hook = hooks.get("codeforces")
    if hook and send_embed(hook, embed, username="Codeforces Daily"):
        used.append(f"{problem['contestId']}{problem['index']}")
        del used[:-200]
        save_json(state_p, state)
        print(f"codeforces: posted {problem['name']} ({band})")


def post_cp31(hooks):
    rows = load_json(f"{DATA}/cp31.json")
    idx = days_since(*LAUNCH_DAY) % len(rows)
    entry = rows[idx]
    embed = {
        "author": {"name": "TLE Eliminators CP-31 Sheet"},
        "title": f"Slot {idx + 1}/372 — {entry['name']}",
        "url": entry["url"],
        "color": cf_color(entry["band"]),
        "description": (
            f"The sheet's steady curriculum: one handpicked problem per rating band, "
            f"every single day. You are on the **{entry['band']}** rated block."
        ),
        "fields": [
            {"name": "Band", "value": str(entry["band"]), "inline": True},
            {"name": "Slot", "value": f"{entry['slot']}/31", "inline": True},
            {"name": "Solved by", "value": f"{entry.get('solvedCount', 0):,}", "inline": True},
        ],
        "footer": {"text": "cp/cp31 · full sheet cycles every 372 days"},
    }
    hook = hooks.get("cp31")
    if hook and send_embed(hook, embed, username="CP-31 Daily"):
        print(f"cp31: posted slot {idx + 1}: {entry['name']}")


def post_cses(hooks):
    tasks = load_json(f"{DATA}/cses.json")
    idx = days_since(*LAUNCH_DAY) % len(tasks)
    task = tasks[idx]
    embed = {
        "author": {"name": "CSES Problem Set"},
        "title": f"Task {task['id']} — {task['name']}",
        "url": f"https://cses.fi/problemset/task/{task['id']}",
        "color": 0x3498DB,
        "description": (
            "The classic algorithmic gym: 400 problems that quietly teach you every core technique. "
            "No editorials until you have a verdict."
        ),
        "fields": [
            {"name": "Category", "value": task["category"], "inline": True},
            {"name": "Progress", "value": f"#{idx + 1} of {len(tasks)}", "inline": True},
        ],
        "footer": {"text": "cp/cses · full set cycles every year"},
    }
    hook = hooks.get("cses")
    if hook and send_embed(hook, embed, username="CSES Daily"):
        print(f"cses: posted {task['id']} {task['name']}")


TRACKS = [
    ("blind-75", "blind75.json", "Blind 75", "the interview canon — smallest list with maximum coverage"),
    ("neetcode-150", "neetcode150.json", "NeetCode 150", "pattern-first prep across all major topics"),
    ("striver-a2z", "a2z.json", "Striver A2Z", "zero-to-advanced DSA path, strictly in order"),
]


def post_tracks(hooks):
    for key, datafile, title, blurb in TRACKS:
        hook = hooks.get(key)
        if not hook:
            continue
        rows = load_json(f"{DATA}/{datafile}")
        idx = days_since(*LAUNCH_DAY) % len(rows)
        row = rows[idx]
        leetcode_url = row.get("leetcode") or ""
        if leetcode_url and leetcode_url.startswith("/"):
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
        if send_embed(hook, embed, username=f"{title} Track"):
            print(f"{key}: posted #{idx + 1} {row['name']}")


def post_core_subjects(hooks):
    subjects = load_json(f"{DATA}/core_subjects.json")
    names = list(subjects.keys())
    subject = names[days_since(*LAUNCH_DAY) % len(names)]
    qs = subjects[subject]
    qidx = (days_since(*LAUNCH_DAY) // len(names)) % len(qs)
    qa = qs[qidx]
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
            {"name": "Cycle", "value": f"Q{qidx + 1}/{len(qs)}", "inline": True},
        ],
        "footer": {"text": "tracks/core-subjects · OS, networks and DBMS rotate"},
    }
    hook = hooks.get("core-subjects")
    if hook and send_embed(hook, embed, username=f"{subject} Drill"):
        print(f"core-subjects: posted [{subject}] {qa['q'][:60]}")


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
    return (f"{h}h {m:02d}m" if h else f"{m}m")


def post_contests(hooks):
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
    except Exception as exc:
        print(f"lc contests failed: {exc}")
    try:
        contests = cf_contests()
        upcoming = sorted(
            (c for c in contests if c.get("phase") == "BEFORE"), key=lambda c: c["startTimeSeconds"]
        )[:4]
        for c in upcoming:
            lines.append(
                f"**Codeforces** — [Round #{c.get('id')}: {c['name']}](https://codeforces.com/contests/{c['id']})\n"
                f"{fmt_ist(c['startTimeSeconds'])} · {human_duration(c.get('durationSeconds', 7200))}"
            )
    except Exception as exc:
        print(f"cf contests failed: {exc}")
    if not lines:
        print("contests: nothing to post")
        return
    embed = {
        "author": {"name": "Upcoming Contests"},
        "title": "Put them on your calendar",
        "color": 0xF39C12,
        "description": "\n\n".join(lines)[: DESCRIPTION_LIMIT],
        "footer": {"text": "#contests · refreshed every morning"},
    }
    hook = hooks.get("contests")
    if hook and send_embed(hook, embed, username="Contest Radar"):
        print("contests: posted")


def cf_contests():
    return http_json("https://codeforces.com/api/contest.list")["result"]


def main():
    hooks_env = os.environ.get("FEED_WEBHOOKS")
    if not hooks_env:
        print("FEED_WEBHOOKS is not set")
        sys.exit(1)
    hooks = json.loads(hooks_env)

    post_topics(hooks)
    post_codeforces(hooks)
    post_cp31(hooks)
    post_cses(hooks)
    post_tracks(hooks)
    post_core_subjects(hooks)
    post_contests(hooks)
    print("all feeds done")


if __name__ == "__main__":
    main()
