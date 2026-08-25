import json
import os
import re
import sys
import time
import urllib.request

from mfcommon import (
    DESCRIPTION_LIMIT,
    lc_graphql,
    load_json,
    send_embed,
    html_to_discord,
    truncate,
)

QUERY = """query questionOfToday {
    activeDailyCodingChallengeQuestion {
        date
        link
        question {
            questionFrontendId
            title
            titleSlug
            content
            difficulty
            acRate
            topicTags {
                name
            }
        }
    }
}"""


def learn_lines(slug, frontend_id):
    lines = []
    shot = load_json("data/screenshots.json").get(str(frontend_id))
    if shot:
        lines.append(f"[Editorial screenshot]({shot})")
    lines.append(f"[LeetCode editorials](https://leetcode.com/problems/{slug}/solutions/)")
    vid = load_json("data/neetcode_map.json").get(slug)
    if vid:
        lines.append(f"[NeetCode video]({vid['youtube']})")
    lines.append(
        "Reference code (spoilers): "
        f"[C++](https://raw.githubusercontent.com/kamyu104/LeetCode-Solutions/master/C++/{slug}.cpp)"
        " · "
        f"[Python](https://raw.githubusercontent.com/kamyu104/LeetCode-Solutions/master/Python/{slug}.py)"
    )
    return "\n".join(lines)


def build_embed(daily):
    question = daily["question"]
    difficulty = question["difficulty"]
    url = f"https://leetcode.com{daily['link']}"

    embed = {
        "author": {
            "name": f"LeetCode Daily Challenge — {daily['date']}",
            "url": url,
        },
        "title": f"{question['questionFrontendId']}. {question['title']}",
        "url": url,
        "color": {"Easy": 0x2ECC71, "Medium": 0xFFA116, "Hard": 0xE74C3C}.get(
            difficulty, 0x95A5A6
        ),
    }

    if question.get("content"):
        body = html_to_discord(question["content"])
        embed["description"] = truncate(
            body, DESCRIPTION_LIMIT, "\n\n*Full statement at the link above.*"
        )

    topics = ", ".join(t["name"] for t in question.get("topicTags", []))
    rating = load_json("data/ratings.json").get(question["titleSlug"])
    fields = [
        {"name": "Difficulty", "value": difficulty, "inline": True},
        {"name": "Acceptance", "value": f"{question['acRate']:.1f}%", "inline": True},
        {"name": "Rating", "value": str(rating) if rating else "unrated", "inline": True},
    ]
    if topics:
        fields.append({"name": "Topics", "value": topics[:1024]})
    fields.append(
        {"name": "Learn", "value": truncate(learn_lines(question["titleSlug"], question["questionFrontendId"]), 1024, "…")}
    )
    embed["fields"] = fields

    embed["footer"] = {
        "text": "Progress tracked automatically via CodeGrind — /add to join the leaderboard",
    }
    return embed


def clear_channel(token, channel_id):
    """Delete all messages in a channel."""
    base = "https://discord.com/api/v10"
    headers = {"Authorization": f"Bot {token}", "User-Agent": "MFGrindBot/1.0"}
    after = "0"
    ids = []
    while True:
        req = urllib.request.Request(
            f"{base}/channels/{channel_id}/messages?limit=100&after={after}",
            headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                batch = json.loads(r.read().decode())
        except Exception:
            break
        if not batch:
            break
        ids += [m["id"] for m in batch]
        after = max(ids)
        if len(batch) < 100:
            break
        time.sleep(0.4)
    while ids:
        chunk = ids[-100:]
        del ids[-100:]
        data = json.dumps({"messages": chunk}).encode()
        req = urllib.request.Request(
            f"{base}/channels/{channel_id}/messages/bulk-delete",
            data=data, headers={**headers, "Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=30)
        except Exception:
            pass
        time.sleep(0.5)


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set")
        sys.exit(1)

    # Clear channel before posting fresh content
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        m = re.search(r"/webhooks/(\d+)/", webhook_url)
        if m:
            wh_id = m.group(1)
            # Fetch webhook to get the actual channel_id
            try:
                req = urllib.request.Request(
                    f"https://discord.com/api/v10/webhooks/{wh_id}",
                    headers={"Authorization": f"Bot {token}", "User-Agent": "MFGrindBot/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    wh_data = json.loads(r.read().decode())
                channel_id = wh_data["channel_id"]
                clear_channel(token, channel_id)
                print(f"Cleared channel {channel_id}")
            except Exception as e:
                print(f"Warning: could not clear channel: {e}")

    data = lc_graphql(QUERY)
    daily = data.get("data", {}).get("activeDailyCodingChallengeQuestion")
    if not daily:
        print("Unexpected LeetCode response:", json.dumps(data)[:500])
        sys.exit(1)

    question = daily["question"]
    embed = build_embed(daily)

    ok = send_embed(
        webhook_url,
        embed,
        username="Daily Problem",
        content="Today's problem is up — first solve takes the crown.",
        ping_everyone=False,
    )
    if not ok:
        print("Discord webhook failed")
        sys.exit(1)
    print(
        f"Posted daily problem: {question['questionFrontendId']}. {question['title']}"
    )


if __name__ == "__main__":
    main()
