"""Shared helpers for MF Grind Discord automation."""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date
from html import unescape

LC_GRAPHQL = "https://leetcode.com/graphql"

MOZILLA_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BOT_UA = "MFGrindBot/1.0 (+https://github.com/aryanbatras/leetcode-daily-discord)"

DIFFICULTY_COLORS = {
    "Easy": 0x2ECC71,
    "Medium": 0xFFA116,
    "Hard": 0xE74C3C,
}

DESCRIPTION_LIMIT = 4000
FIELD_VALUE_LIMIT = 1024


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def http_json(url, payload=None, headers=None, timeout=30):
    hdrs = {"User-Agent": MOZILLA_UA}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=hdrs
        )
    else:
        req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_text(url, headers=None, timeout=30):
    hdrs = {"User-Agent": BOT_UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def lc_graphql(query, variables=None):
    return http_json(
        LC_GRAPHQL,
        {"query": query, "variables": variables or {}},
        headers={"Referer": "https://leetcode.com"},
    )


def post_webhook(url, payload, retries=4):
    """Post a webhook payload. Discord answers 204 No Content on success.
    Sleeps after every send so we never trip Discord's rate limits."""
    data = json.dumps(payload).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": BOT_UA},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 204):
                    time.sleep(2.5)
                    return True
                raise RuntimeError(f"status {resp.status}")
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code == 429:
                time.sleep(2 ** attempt)
                continue
            if exc.code >= 500:
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as exc:
            last_err = exc
            time.sleep(2 ** attempt)
    print(f"webhook failed after {retries} attempts: {last_err}")
    return False


def send_embed(webhook_url, embed, username, content=None, ping_everyone=False):
    payload = {
        "username": username,
        "embeds": [embed],
        "allowed_mentions": {"parse": ["everyone"] if ping_everyone else []},
    }
    if content:
        payload["content"] = content
    return post_webhook(webhook_url, payload)


def days_since(year, month, day):
    return (date.today() - date(year, month, day)).days


def utc_day_number():
    return int(time.time() // 86400)


def seeded_index(key, modulus, extra_offset=0):
    """Stable pseudo-random index per key that advances once per UTC day."""
    digest = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    return (utc_day_number() * 2654435761 + digest + extra_offset) % max(modulus, 1)


def truncate(text, limit, suffix):
    if len(text) <= limit:
        return text
    cut = text[: limit - len(suffix)]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip() + suffix


def html_to_discord(html):
    """Convert LeetCode's HTML statement into Discord-flavoured markdown."""
    text = html

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
    text = re.sub(r"(?m)^[\s\xa0]+$", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def norm_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())
