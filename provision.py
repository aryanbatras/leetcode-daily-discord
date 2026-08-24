"""One-shot Discord restructure: builds every feed channel group and emits
the new FEED_WEBHOOKS secret JSON. Idempotent — safe to re-run."""

import json
import re
import sys
import time
import urllib.error
import urllib.request

GUILD = 1541028379598397452
BASE = "https://discord.com/api/v10"
TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""
OUT = "/var/folders/y6/rr08l8t92zv7ztv48m74gjsr0000gn/T/opencode/feed_webhooks_v2.json"

TOPIC_SLUGS = [
    "array", "string", "hash-table", "two-pointers", "sliding-window",
    "prefix-sum", "binary-search", "stack", "monotonic-stack", "queue",
    "heap-priority-queue", "linked-list", "tree", "trie", "graph",
    "union-find", "backtracking", "greedy", "dynamic-programming",
    "bit-manipulation", "math", "matrix", "sorting", "design",
]
BANDS = [800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900]
SUBJECTS = ["operating-systems", "computer-networks", "dbms"]
CSES_SECTIONS = [
    "Introductory Problems", "Sorting and Searching", "Dynamic Programming",
    "Graph Algorithms", "Range Queries", "Tree Algorithms", "Mathematics",
    "String Algorithms", "Geometry", "Advanced Techniques", "Additional Problems",
]


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "User-Agent": "MFGrindBot/1.0",
        "Content-Type": "application/json",
    }
    time.sleep(0.12)
    last_exc = None
    for attempt in range(30):
        try:
            req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return json.loads(raw) if r.status != 204 and raw else None
        except urllib.error.HTTPError as e:
            code = e.code
            detail = e.read().decode()[:200]
            if code == 429:
                try:
                    doc = json.loads(detail)
                    pause = min(doc.get("retry_after", 5) + 0.5, 20)
                except Exception:
                    pause = 10
                print(f"  [429 {path.split('/')[-1]}] sleeping {pause:.1f}s")
                time.sleep(pause)
                continue
            if code >= 500:
                time.sleep(1 + attempt)
                continue
            raise RuntimeError(f"{method} {path} -> {code}: {detail}")
        except Exception as exc:
            last_exc = exc
            time.sleep(2 + attempt)
    raise RuntimeError(f"{method} {path} exhausted retries: {last_exc}")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    chans = api("GET", f"/guilds/{GUILD}/channels")
    cats_by_name = {c["name"]: c["id"] for c in chans if c["type"] == 4}
    text_by_name = {c["name"]: c for c in chans if c["type"] == 0}

    # prune legacy single-feed channels (only real text channels, only if present)
    for doomed in ["codeforces", "cp31", "cses", "core-subjects-channel", "rest-perm-test",
                   "Operating Systems", "Computer Networks", "DBMS"]:
        ch = text_by_name.pop(doomed, None)
        if ch:
            api("DELETE", f"/channels/{ch['id']}")
            print("deleted channel", doomed)

    # mechanism-named categories are misguided: dissolve any that survive
    for dead_cat in ("discord-server-bots", "bots", "chat", "focus-sessions"):
        cat_id = cats_by_name.get(dead_cat)
        if not cat_id:
            continue
        kids = [c for c in chans if c.get("parent_id") == cat_id]
        homes = {"daily-problem": "leetcode", "contests": "codeforces",
                 "leaderboard": None, "bot-guide": None, "general": None}
        for kid in kids:
            target = homes.get(kid["name"], "__unset__")
            if target == "__unset__":
                continue
            parent = cats_by_name.get(target) if target else None
            api("PATCH", f"/channels/{kid['id']}", {"parent_id": parent})
        if not [c for c in api("GET", f"/guilds/{GUILD}/channels") or []
                if c.get("parent_id") == cat_id]:
            api("DELETE", f"/channels/{cat_id}")
            print("dissolved category", dead_cat)

    # desired: category -> [(channel, webhook_name, key)]
    plan = {
        "leetcode": [("lc-" + s, "Topic Feed", s) for s in TOPIC_SLUGS],
        "core-subjects": [(n, "Subject Drill", n) for n in SUBJECTS],
        "tracks": [
            ("blind-75", "Track Feed", "blind-75"),
            ("neetcode-150", "Track Feed", "neetcode-150"),
            ("striver-a2z", "Track Feed", "striver-a2z"),
        ],
        "system-design": [
            ("low-level-design", "LLD Drill", "low-level-design"),
            ("high-level-design", "HLD Drill", "high-level-design"),
        ],
        "codeforces": [(str(b), "CF Feed", f"cf-{b}") for b in BANDS],
        "cses": [(slugify(s), "CSES Feed", f"cses-{slugify(s)}") for s in CSES_SECTIONS],
    }

    hooks_map = {}
    for cat_name, items in plan.items():
        if cat_name not in cats_by_name:
            cat = api("POST", f"/guilds/{GUILD}/channels", {"name": cat_name, "type": 4})
            cats_by_name[cat_name] = cat["id"]
            print("created category", cat_name)
        cat_id = cats_by_name[cat_name]

        for chan_name, hook_name, key in items:
            ch = text_by_name.get(chan_name)
            if not ch:
                ch = api("POST", f"/guilds/{GUILD}/channels",
                         {"name": chan_name, "type": 0, "parent_id": cat_id})
                text_by_name[chan_name] = ch
                print("created channel", chan_name)
            elif ch.get("parent_id") != cat_id:
                api("PATCH", f"/channels/{ch['id']}", {"parent_id": cat_id})
                print("re-parented", chan_name, "->", cat_name)
            hooks = api("GET", f"/channels/{ch['id']}/webhooks")
            hook = next((h for h in hooks if h["name"] == hook_name), None)
            if not hook:
                hook = api("POST", f"/channels/{ch['id']}/webhooks", {"name": hook_name})
                print("created webhook", hook_name, "->", chan_name)
            hooks_map[key] = f"https://discord.com/api/v10/webhooks/{hook['id']}/{hook['token']}"
            # archive channel: read-only top-level, but threads open for discussion
            api("PUT", f"/channels/{ch['id']}/permissions/{GUILD}",
                {"allow": 1024 + 65536 + 262144 + 2097152, "deny": 2048, "type": 0})

    for keep in ("blind-75", "neetcode-150", "striver-a2z"):
        pass  # handled inside plan above

    old = json.load(open("/var/folders/y6/rr08l8t92zv7ztv48m74gjsr0000gn/T/opencode/feed_webhooks.json"))
    for k, v in old.items():
        hooks_map.setdefault(k, v)
    # drop keys whose channels were pruned
    for dead in ("codeforces", "cp31", "cses", "core-subjects", *(f"cp31-{b}" for b in BANDS)):
        hooks_map.pop(dead, None)

    with open(OUT, "w") as fh:
        json.dump(hooks_map, fh, indent=1)
    print(f"\nwrote {len(hooks_map)} webhook urls -> {OUT}")


if __name__ == "__main__":
    main()
