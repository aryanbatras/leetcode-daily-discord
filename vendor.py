"""Refresh vendored datasets in data/. Runs weekly on Actions; safe to run locally."""

import json
import re
import sys
from urllib.parse import quote

from mfcommon import http_json, http_text, norm_name, save_json


DATA = "data"
KHUSH = "https://raw.githubusercontent.com/khush2808/dsa-sheets/main/web/data/json"


def gh_tree(repo, branch):
    return http_json(f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1")["tree"]


def raw_file(repo, branch, path):
    return http_text(
        f"https://raw.githubusercontent.com/{repo}/{branch}/{quote(path)}"
    )


def vendor_screenshots():
    tree = gh_tree("akhilkammila/leetcode-screenshotter", "main")
    index = {}
    for item in tree:
        path = item["path"]
        m = re.match(r"editorial-screenshots/[^/]+/(\d+)\. .+\.png$", path)
        if not m:
            continue
        index[m.group(1)] = (
            "https://raw.githubusercontent.com/akhilkammila/leetcode-screenshotter/main/"
            + quote(path)
        )
    save_json(f"{DATA}/screenshots.json", index)
    return len(index)


def vendor_neetcode():
    doc = http_json(f"{KHUSH}/neetcode-problems.json")
    problems = doc["problems"]
    video_map = {
        p["leetcode_slug"]: {"youtube": p.get("youtube"), "pattern": p.get("pattern")}
        for p in problems
        if p.get("youtube")
    }
    save_json(f"{DATA}/neetcode_map.json", video_map)

    ne150 = [
        {
            "name": p["problem_name"],
            "slug": p["leetcode_slug"],
            "difficulty": p["difficulty"],
            "pattern": p.get("pattern"),
            "youtube": p.get("youtube"),
            "order": p.get("order"),
        }
        for p in problems
        if p.get("list_membership", {}).get("neetcode150")
    ]
    ne150.sort(key=lambda x: (x["order"] is None, x["order"]))
    save_json(f"{DATA}/neetcode150.json", ne150)
    return len(video_map), len(ne150)


def vendor_blind75():
    doc = http_json(f"{KHUSH}/blind-75-sheet-problems.json")
    rows = [
        {
            "name": p["problem_name"],
            "difficulty": p["difficulty"],
            "category": p.get("category_name"),
            "leetcode": p.get("leetcode"),
            "youtube": p.get("youtube"),
            "article": p.get("article"),
        }
        for p in doc["problems"]
    ]
    save_json(f"{DATA}/blind75.json", rows)
    return len(rows)


def vendor_a2z():
    doc = http_json(f"{KHUSH}/strivers-a2z-problems.json")
    rows = [
        {
            "name": p["problem_name"],
            "difficulty": p.get("difficulty"),
            "category": p.get("subcategory_name") or p.get("category_name"),
            "leetcode": p.get("leetcode"),
            "youtube": p.get("youtube"),
            "article": p.get("article"),
            "order": p.get("order"),
        }
        for p in doc["problems"]
    ]
    rows.sort(key=lambda x: (x["order"] is None, x["order"]))
    save_json(f"{DATA}/a2z.json", rows)
    return len(rows)


def vendor_cf():
    doc = http_json("https://codeforces.com/api/problemset.problems")
    solved = {
        (s["contestId"], s["index"]): s["solvedCount"]
        for s in doc["result"]["problemStatistics"]
    }
    rows = []
    for p in doc["result"]["problems"]:
        if p.get("type") != "PROGRAMMING" or "rating" not in p:
            continue
        rows.append(
            {
                "contestId": p["contestId"],
                "index": p["index"],
                "name": p["name"],
                "rating": p["rating"],
                "tags": p.get("tags", []),
                "solvedCount": solved.get((p["contestId"], p["index"]), 0),
            }
        )
    save_json(f"{DATA}/cf_problems.json", rows)
    return len(rows)


def vendor_cp31(cf_rows):
    tree = gh_tree("virajchandra51/TLE_CP_31", "main")
    entries = []
    for item in tree:
        m = re.match(r"^(\d{3,4})/(\d+) - (.+)\.cpp$", item["path"])
        if not m:
            continue
        entries.append(
            {
                "band": int(m.group(1)),
                "slot": int(m.group(2)),
                "name": re.sub(r"\s+", " ", m.group(3)).strip(),
            }
        )
    entries.sort(key=lambda e: (e["band"], e["slot"]))

    by_norm_band = {}
    for row in cf_rows:
        by_norm_band.setdefault((norm_name(row["name"]), row["rating"]), row)

    out = []
    matched = 0
    for e in entries:
        row = by_norm_band.get((norm_name(e["name"]), e["band"]))
        if row:
            matched += 1
            out.append(
                {
                    "band": e["band"],
                    "slot": e["slot"],
                    "name": row["name"],
                    "url": f"https://codeforces.com/problemset/problem/{row['contestId']}/{row['index']}",
                    "tags": row.get("tags", []),
                    "solvedCount": row.get("solvedCount", 0),
                }
            )
        else:
            out.append(
                {
                    "band": e["band"],
                    "slot": e["slot"],
                    "name": e["name"],
                    "url": "https://codeforces.com/problemset?order=BY_RATING_ASC&search="
                    + quote(e["name"]),
                    "tags": [],
                    "solvedCount": 0,
                }
            )
    save_json(f"{DATA}/cp31.json", out)
    return len(out), matched


def vendor_cses():
    html = http_text("https://cses.fi/problemset/")
    tasks = []
    sections = re.split(r"<h2>(.*?)</h2>", html)
    # sections: [pre, name1, body1, name2, body2, ...]
    for i in range(1, len(sections) - 1, 2):
        section = sections[i]
        for m in re.finditer(r'<a href="/problemset/task/(\d+)">([^<]+)</a>', sections[i + 1]):
            tasks.append({"id": m.group(1), "name": m.group(2).strip(), "category": section})
    save_json(f"{DATA}/cses.json", tasks)
    return len(tasks)


def vendor_ratings():
    rows = http_json("https://zerotrac.github.io/leetcode_problem_rating/data.json")
    table = {r["TitleSlug"]: round(r["Rating"]) for r in rows}
    save_json(f"{DATA}/ratings.json", table)
    return len(table)


def main():
    results = {}
    n = vendor_screenshots()
    results["screenshots"] = n
    nv, n150 = vendor_neetcode()
    results["neetcode_map"], results["neetcode150"] = nv, n150
    results["blind75"] = vendor_blind75()
    results["a2z"] = vendor_a2z()
    cf_count = vendor_cf()
    results["cf_problems"] = cf_count
    with open(f"{DATA}/cf_problems.json", encoding="utf-8") as fh:
        cf_rows = json.load(fh)
    total, matched = vendor_cp31(cf_rows)
    results["cp31"] = total
    results["cp31_matched_to_cf"] = matched
    results["cses"] = vendor_cses()
    results["ratings"] = vendor_ratings()
    print(json.dumps(results, indent=1))
    if results["cp31_matched_to_cf"] < total * 0.9:
        print("WARNING: cp31 CF-match rate below 90% — inspect names", file=sys.stderr)


if __name__ == "__main__":
    main()
