"""Static catalog builder: dumps a complete ordered problem list into a channel.

Usage: python3 scripts/build_catalog.py <mode>
Modes:
    cses-intro   — all Introductory Problems tasks, full scraped statements

Webhooks come from $FEED_WEBHOOKS or the local map file. Channel ids resolve
via the bot token in $DISCORD_BOT_TOKEN.
"""

import html as htmllib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://discord.com/api/v10"
GUILD = 1541028379598397452
LOCAL_HOOKS = "/var/folders/y6/rr08l8t92zv7ztv48m74gjsr0000gn/T/opencode/feed_webhooks_v2.json"
UA_DISCORD = "MFGrindBot/1.0 (github.com/aryanbatras/leetcode-daily-discord)"
UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SEND_PACE = 2.5
FETCH_PACE = 1.5

MATH_REPL = [
    ("\\rightarrow", "→"), ("\\leftarrow", "←"), ("\\le", "≤"), ("\\leq", "≤"),
    ("\\ge", "≥"), ("\\geq", "≥"), ("\\times", "*"), ("\\cdot", "*"),
    ("\\ldots", "..."), ("\\dots", "..."), ("\\infty", "∞"), ("\\sum", "Σ"),
    ("\\bmod", "mod"), ("\\mod", "mod"), ("\\oplus", "^"), ("\\cup", "∪"),
    ("\\cap", "∩"), ("\\ne", "≠"), ("\\neq", "≠"), ("\\pm", "±"),
]


def call(url, method="GET", token=None, body=None, ua=UA_DISCORD):
    data = None
    headers = {"User-Agent": ua}
    if token:
        headers["Authorization"] = f"Bot {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    start = time.time()
    while time.time() - start < 60:
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    p = min(json.loads(e.read().decode()).get("retry_after", 5) + 0.5, 20)
                except Exception:
                    p = 6
                time.sleep(p)
            elif e.code == 404:
                return None
            else:
                return None
        except Exception:
            time.sleep(3)
    raise RuntimeError(f"exhausted: {url}")


def hooks_map():
    env = os.environ.get("FEED_WEBHOOKS")
    path = env if env else LOCAL_HOOKS
    src = open(path) if ":" not in path[:8] else None
    if src:
        return json.load(src)
    return json.loads(path)


def find_channel_id(token, name):
    chans = call(f"{BASE}/guilds/{GUILD}/channels", token=token)
    for c in chans:
        if c["type"] == 0 and c["name"] == name:
            return c["id"]
    raise RuntimeError(f"channel #{name} not found")


def clear_channel(token, channel_id):
    ids = []
    after = "0"
    while True:
        batch = call(f"{BASE}/channels/{channel_id}/messages?limit=100&after={after}", token=token)
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
        call(f"{BASE}/channels/{channel_id}/messages/bulk-delete",
             method="POST", token=token, body={"messages": chunk})
        print(f"cleared {len(chunk)} messages")
        time.sleep(0.8)


def send_text(hook, content):
    payload = {"content": content, "allowed_mentions": {"parse": []}}
    call(hook, method="POST", body=payload)
    time.sleep(SEND_PACE)


def send_embed(hook, embed):
    payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    call(hook, method="POST", body=payload)
    time.sleep(SEND_PACE)


def latest_message_id(token, channel_id):
    msgs = call(f"{BASE}/channels/{channel_id}/messages?limit=1", token=token)
    return msgs[0]["id"] if msgs else None


MATH_SPAN = re.compile(r'<span class="math math-(inline|display)">.*?</span>', re.S)


def math_text(fragment):
    txt = re.sub(r"<[^>]+>", "", fragment)
    txt = htmllib.unescape(txt)
    for a, b in MATH_REPL:
        txt = txt.replace(a, b)
    txt = txt.replace("\\", "")
    return txt.strip()


def cses_html_to_md(html_frag):
    s = html_frag
    s = MATH_SPAN.sub(lambda m: f"`{math_text(m.group(0))}`" if m.group(1) == "inline"
                      else f"\n```\n{math_text(m.group(0))}\n```\n", s)
    s = re.sub(r"<h1[^>]*>(.*?)</h1>", lambda m: f"\n**{m.group(1).strip()}**\n", s, flags=re.S)
    s = re.sub(r"<pre>(.*?)</pre>", lambda m: "\n```\n" + htmllib.unescape(m.group(1)).rstrip("\n") + "\n```\n", s, flags=re.S)
    s = re.sub(r"<li>(.*?)</li>", lambda m: "• " + m.group(1).strip(), s, flags=re.S)
    s = re.sub(r"</?(ul|ol)[^>]*>", "\n", s)
    s = re.sub(r"</p>", "\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<code>(.*?)</code>", lambda m: "`" + htmllib.unescape(m.group(1)) + "`", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def scrape_cses_task(task_id):
    url = f"https://cses.fi/problemset/task/{task_id}"
    req = urllib.request.Request(url, headers={"User-Agent": UA_BROWSER})
    with urllib.request.urlopen(req, timeout=30) as r:
        page = r.read().decode()
    cons = re.search(r'<ul class="task-constraints">(.*?)</ul>', page, re.S)
    tl = ml = ""
    if cons:
        vals = re.findall(r"<b>(.*?)</b>\s*([^<]+)", cons.group(1))
        for k, v in vals:
            if "Time" in k:
                tl = v.strip()
            if "Memory" in k:
                ml = v.strip()
    body = re.search(r'<div class="md">(.*?)</div>\s*</div>', page, re.S)
    statement = cses_html_to_md(body.group(1)) if body else "*(statement parse failed — solve at the link)*"
    return {"tl": tl, "ml": ml, "body": statement}


def fmt_task_embed(idx, total, task, detail):
    meta = []
    if detail["tl"]:
        meta.append(f"time {detail['tl']}")
    if detail["ml"]:
        meta.append(f"mem {detail['ml']}")
    body = detail["body"]
    if len(body) > 3900:
        cut = body[:3900]
        if "```" in cut and cut.count("```") % 2 == 1:
            cut += "\n```"
        body = cut.rstrip() + "\n\n*(full statement at the link)*"
    return {
        "author": {"name": "CSES — Introductory Problems"},
        "title": f"{idx}. {task['name']}",
        "url": f"https://cses.fi/problemset/task/{task['id']}",
        "color": 0x3498DB,
        "description": body or "*(statement at the link)*",
        "fields": [
            {"name": "Limits", "value": " · ".join(meta) or "—", "inline": True},
            {"name": "Position", "value": f"{idx}/{total}", "inline": True},
        ],
    }


def mode_cses_intro():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    hook = hooks.get("cses-introductory-problems")
    assert hook, "webhook key cses-introductory-problems missing"
    channel_id = find_channel_id(token, "introductory-problems")

    tasks = [t for t in json.load(open("data/cses.json"))
             if t["category"] == "Introductory Problems"]
    tasks.sort(key=lambda t: t["id"])
    print(f"{len(tasks)} introductory tasks")

    clear_channel(token, channel_id)

    send_embed(hook, {
        "author": {"name": "CSES Problem Set"},
        "title": "Introductory Problems",
        "url": "https://cses.fi/problemset/list/",
        "color": 0x2C3E50,
        "description": ("All tasks in order, full statement on each card. "
                        "Catalog at the end."),
        "footer": {"text": f"{len(tasks)} tasks"},
    })

    catalog = ["**Catalog — Introductory Problems**", ""]
    for i, task in enumerate(tasks, 1):
        try:
            detail = scrape_cses_task(task["id"])
        except Exception as exc:
            print(f"scrape failed {task['id']}: {exc}")
            detail = {"tl": "", "ml": "", "body": "*(scrape failed — solve at the link)*"}
        send_embed(hook, fmt_task_embed(i, len(tasks), task, detail))
        catalog.append(f"**{i}.** {task['name']}")
        print(f"posted {i}/{len(tasks)} {task['name']}")
        time.sleep(FETCH_PACE)

    payload = {"content": "\n".join(catalog)[:2000], "allowed_mentions": {"parse": []}}
    call(hook, method="POST", body=payload)
    time.sleep(SEND_PACE)
    print("catalog posted (unpinned) — done")


MODES = {
    "cses-intro": mode_cses_intro,
}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        print(f"usage: build_catalog.py [{'|'.join(MODES)}]")
        sys.exit(2)
    MODES[sys.argv[1]]()
