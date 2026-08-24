import json
import os
import sys
import urllib.request

GRAPHQL_ENDPOINT = "https://leetcode.com/graphql"

QUERY = """query questionOfToday {
    activeDailyCodingChallengeQuestion {
        date
        link
        question {
            questionFrontendId
            title
            difficulty
        }
    }
}"""

DIFFICULTY_COLORS = {
    "Easy": 0x2ECC71,
    "Medium": 0xFFA116,
    "Hard": 0xE74C3C,
}


def graphql(url, query):
    payload = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_to_discord(webhook_url, embed):
    payload = json.dumps(
        {
            "username": "Daily Problem",
            "embeds": [embed],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set")
        sys.exit(1)

    data = graphql(GRAPHQL_ENDPOINT, QUERY)
    daily = data.get("data", {}).get("activeDailyCodingChallengeQuestion")
    if not daily:
        print("Unexpected LeetCode response:", json.dumps(data)[:500])
        sys.exit(1)

    question = daily["question"]
    difficulty = question["difficulty"]

    embed = {
        "title": f"{question['questionFrontendId']}. {question['title']}",
        "url": f"https://leetcode.com{daily['link']}",
        "description": (
            f"**Difficulty:** {difficulty}\n"
            f"**Date:** {daily['date']}\n\n"
            "Solve it today and your streak counts automatically (once you've run `/add` in #leaderboard)."
        ),
        "color": DIFFICULTY_COLORS.get(difficulty, 0x95A5A6),
        "footer": {"text": "LeetCode Daily Challenge"},
    }

    status = post_to_discord(webhook_url, embed)
    if status not in (200, 204):
        print(f"Discord webhook returned {status}")
        sys.exit(1)
    print(f"Posted daily problem: {question['questionFrontendId']}. {question['title']} ({difficulty})")


if __name__ == "__main__":
    main()
