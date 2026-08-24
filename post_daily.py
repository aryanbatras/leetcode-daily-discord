import json
import os
import re
import sys
import urllib.request
from html import unescape

GRAPHQL_ENDPOINT = "https://leetcode.com/graphql"
ZEROTRAC_ENDPOINT = "https://zerotrac.github.io/leetcode_problem_rating/data.json"

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

DIFFICULTY_COLORS = {
    "Easy": 0x2ECC71,
    "Medium": 0xFFA116,
    "Hard": 0xE74C3C,
}

DESCRIPTION_LIMIT = 4000
FIELD_VALUE_LIMIT = 1024


def http_json(url, payload=None):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Referer"] = "https://leetcode.com"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers
        )
    else:
        req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def html_to_discord(html):
    """Convert LeetCode's HTML statement into Discord-flavoured markdown."""
    text = html

    # <pre><strong>Example N:</strong> ... </pre> -> fenced code block
    def pre_repl(m):
        inner = m.group(1)
        inner = re.sub(r"<[^>]+>", "", inner)
        return "```\n" + unescape(inner.strip()) + "\n```"

    text = re.sub(r"<pre>(.*?)</pre>", pre_repl, text, flags=re.S)

    text = re.sub(r"<(?:strong|b)(?:\s[^>]*)?>", "**", text)
    text = re.sub(r"</(?:strong|b)>", "**", text)
    text = re.sub(r"<(?:em|i)(?:\s[^>]*)?>", "*", text)
    text = re.sub(r"</(?:em|i)>", "*", text)
    text = re.sub(r"<li>", "\n- ", text)
    text = re.sub(r"</?(ul|ol)(?:\s[^>]*)?>", "\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<p(?:\s[^>]*)?>", "", text)
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<sup>", "^", text)
    text = re.sub(r"<sub>", "_", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)

    # drop whitespace-only lines (incl. &nbsp; residue), collapse excess newlines
    text = re.sub(r"(?m)^[\s\xa0]+$", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate(text, limit, suffix):
    if len(text) <= limit:
        return text
    cut = text[: limit - len(suffix)]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip() + suffix


def fetch_zerotrac_rating(title_slug):
    try:
        rows = http_json(ZEROTRAC_ENDPOINT)
        for row in rows:
            if row.get("TitleSlug") == title_slug:
                return row.get("Rating")
    except Exception as exc:
        print(f"Zerotrac lookup failed ({exc}); continuing without rating")
    return None


def build_embed(daily, rating):
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
        "color": DIFFICULTY_COLORS.get(difficulty, 0x95A5A6),
    }

    if question.get("content"):
        body = html_to_discord(question["content"])
        embed["description"] = truncate(
            body, DESCRIPTION_LIMIT, "\n\n*Full statement at the link above.*"
        )

    topics = ", ".join(t["name"] for t in question.get("topicTags", []))
    fields = [
        {"name": "Difficulty", "value": difficulty, "inline": True},
        {"name": "Acceptance", "value": f"{question['acRate']:.1f}%", "inline": True},
        {"name": "Rating", "value": str(round(rating)) if rating else "unrated", "inline": True},
    ]
    if topics:
        fields.append({"name": "Topics", "value": topics[:FIELD_VALUE_LIMIT]})
    embed["fields"] = fields

    embed["footer"] = {
        "text": "Progress counts automatically once you've run /add in #leaderboard",
    }
    return embed


def post_to_discord(webhook_url, embed):
    payload = json.dumps({"username": "Daily Problem", "embeds": [embed]}).encode("utf-8")
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set")
        sys.exit(1)

    data = http_json(GRAPHQL_ENDPOINT, {"query": QUERY})
    daily = data.get("data", {}).get("activeDailyCodingChallengeQuestion")
    if not daily:
        print("Unexpected LeetCode response:", json.dumps(data)[:500])
        sys.exit(1)

    question = daily["question"]
    rating = fetch_zerotrac_rating(question["titleSlug"])
    embed = build_embed(daily, rating)

    status = post_to_discord(webhook_url, embed)
    if status not in (200, 204):
        print(f"Discord webhook returned {status}")
        sys.exit(1)
    print(
        f"Posted daily problem: {question['questionFrontendId']}. {question['title']} "
        f"({question['difficulty']}, rating={rating})"
    )


if __name__ == "__main__":
    main()
