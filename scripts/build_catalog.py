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
import subprocess
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
    while time.time() - start < 600:
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
    res = call(hook, method="POST", body=payload)
    if res is None:
        raise RuntimeError(f"webhook gone: {hook}")
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
    s = re.sub(r"<li>(.*?)</li>", lambda m: "\n• " + m.group(1).strip(), s, flags=re.S)
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


CSES_SECTIONS = [
    "Introductory Problems", "Sorting and Searching", "Dynamic Programming",
    "Graph Algorithms", "Range Queries", "Tree Algorithms", "Mathematics",
    "String Algorithms", "Geometry", "Advanced Techniques", "Additional Problems",
]


def dump_cses_section(hooks, token, section, tasks):
    key = "cses-" + section.lower().replace(" ", "-")
    hook = hooks.get(key)
    if not hook:
        print(f"[{section}] no webhook key {key} — skipped")
        return
    channel_id = find_channel_id(token, key[5:])  # channel names drop the cses- prefix
    print(f"[{section}] {len(tasks)} tasks")

    clear_channel(token, channel_id)

    send_embed(hook, {
        "author": {"name": "CSES Problem Set"},
        "title": section,
        "url": "https://cses.fi/problemset/list/",
        "color": 0x2C3E50,
        "description": ("All tasks in order, full statement on each card. "
                        "Catalog at the end."),
        "footer": {"text": f"{len(tasks)} tasks"},
    })

    catalog = [f"**Catalog — {section}**", ""]
    for i, task in enumerate(tasks, 1):
        try:
            detail = scrape_cses_task(task["id"])
        except Exception as exc:
            print(f"scrape failed {task['id']}: {exc}")
            detail = {"tl": "", "ml": "", "body": "*(scrape failed — solve at the link)*"}
        send_embed(hook, fmt_task_embed(i, len(tasks), task, detail))
        catalog.append(f"**{i}.** {task['name']}")
        print(f"[{section}] posted {i}/{len(tasks)} {task['name']}")
        time.sleep(FETCH_PACE)

    payload = {"content": "\n".join(catalog)[:2000], "allowed_mentions": {"parse": []}}
    call(hook, method="POST", body=payload)
    time.sleep(SEND_PACE)
    print(f"[{section}] catalog posted — done")


def mode_cses_all(only=None):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    tasks_by_section = {}
    for t in json.load(open("data/cses.json")):
        tasks_by_section.setdefault(t["category"], []).append(t)
    if only:
        sections = [only]
    else:  # stable site-like order: by each section's first task id
        sections = sorted(tasks_by_section, key=lambda s: min(t["id"] for t in tasks_by_section[s]))
    for section in sections:
        tasks = sorted(tasks_by_section.get(section, []), key=lambda t: t["id"])
        if not tasks:
            print(f"[{section}] no tasks in dataset — skipped")
            continue
        dump_cses_section(hooks, token, section, tasks)


LATEX_SYMBOLS = [
    (r"\leq", "≤"), (r"\le", "≤"), (r"\geq", "≥"), (r"\ge", "≥"),
    (r"\neq", "≠"), (r"\ne", "≠"), (r"\approx", "≈"), (r"\equiv", "≡"),
    (r"\ldots", "…"), (r"\dots", "…"), (r"\cdots", "…"), (r"\hdots", "…"),
    (r"\times", "×"), (r"\cdot", "·"), (r"\div", "÷"), (r"\pm", "±"),
    (r"\mp", "∓"), (r"\infty", "∞"), (r"\sum", "Σ"), (r"\prod", "Π"),
    (r"\to", "→"), (r"\rightarrow", "→"), (r"\leftarrow", "←"),
    (r"\Rightarrow", "⇒"), (r"\Leftarrow", "⇐"), (r"\leftrightarrow", "↔"),
    (r"\dagger", "†"), (r"\ddagger", "‡"), (r"\oplus", "⊕"),
    (r"\ominus", "⊖"), (r"\otimes", "⊗"), (r"\cap", "∩"), (r"\cup", "∪"),
    (r"\subseteq", "⊆"), (r"\supseteq", "⊇"), (r"\in%", "∈"), (r"\in", "∈"),
    (r"\notin", "∉"), (r"\forall", "∀"), (r"\exists", "∃"), (r"\neg", "¬"),
    (r"\land", "∧"), (r"\lor", "∨"), (r"\lfloor", "⌊"), (r"\rfloor", "⌋"),
    (r"\lceil", "⌈"), (r"\rceil", "⌉"), (r"\{", "{"), (r"\}", "}"),
    (r"\%", "%"), (r"\$", "$"), (r"\&", "&"), (r"\#", "#"),
    (r"\_", "_"), (r"\max", "max"), (r"\min", "min"), (r"\log", "log"),
    (r"\ln", "ln"), (r"\gcd", "gcd"), (r"\deg", "deg"),
    (r"\quad", " "), (r"\qquad", "  "), (r"\!", ""), (r"\,", " "),
    (r"\;", " "), (r"\:", " "),
]

SUBSCRIPT_MAP = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
                 "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
                 "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
                 "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ",
                 "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ",
                 "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ",
                 "v": "ᵥ", "x": "ₓ"}

SUPERSCRIPT_MAP = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
                   "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
                   "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
                   "n": "ⁿ", "i": "ⁱ"}


def _map_script(content, table):
    if all(c in table for c in content):
        return "".join(table[c] for c in content)
    return None


def _latex_to_plain(s):
    """Discord has no LaTeX — turn $...$ tex into readable plain text."""
    if not s:
        return s
    out = []
    # split on math segments ($...$) so replacements only touch math
    for i, chunk in enumerate(re.split(r"\$([^$]+)\$", s)):
        if i % 2 == 0:
            out.append(chunk)
            continue
        m = chunk
        # text/color/font wrappers: keep the visible word only
        m = re.sub(r"\\(?:text|textrm|textbf|mathrm|mathbf|mathit|mathcal|"
                   r"mathbb|mathsf|mbox|operatorname)\s*\{([^{}]*)\}", r"\1", m)
        while True:
            new = re.sub(r"\\color\s*\{[^{}]*\}\s*", "", m)
            if new == m:
                break
            m = new
        # functions with arguments
        for _ in range(4):
            m = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", m)
            m = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", m)
            m = re.sub(r"\\binom\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"C(\1, \2)", m)
        for cmd, sym in LATEX_SYMBOLS:
            m = m.replace(cmd + " ", sym + " ").replace(cmd, sym)
        # subscripts / superscripts
        def script_repl(mo):
            base, kind, arg = mo.group(1), mo.group(2), mo.group(3)
            table = SUBSCRIPT_MAP if kind == "_" else SUPERSCRIPT_MAP
            mapped = _map_script(arg, table)
            if mapped is not None:
                return f"{base}{mapped}"
            if len(arg) > 1:
                return f"{base}{kind}({arg})"
            return f"{base}{kind}{arg}"
        m = re.sub(r"([A-Za-z0-9\)\]])\s*([\^_])\s*\{([^{}]*)\}",
                   script_repl, m)
        m = re.sub(r"([A-Za-z0-9\)\]])\s*([\^_])\s*([A-Za-z0-9])",
                   script_repl, m)
        # leftover grouping braces
        m = m.replace("{", "").replace("}", "")
        m = re.sub(r"\s*([≤≥≠≈≡])\s*", r" \1 ", m)
        m = re.sub(r"\s{2,}", " ", m).strip()
        out.append(m)
    return "".join(out)


CF_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
         "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15")


def _curl_text(args, timeout_s):
    try:
        proc = subprocess.run(["curl", "-s", "--max-time", str(timeout_s)] + args,
                              capture_output=True, timeout=timeout_s + 10)
        return proc.returncode == 0, proc.stdout.decode("utf-8", "replace")
    except Exception:
        return False, ""


def fetch_cf_html(url):
    """Codeforces blocks bots (Cloudflare). Strategy: Wayback Machine first
    (problem pages are immutable), then r.jina.ai HTML mode as fallback."""
    ok, meta = _curl_text(
        ["http://archive.org/wayback/available?url=" + url], 30)
    if ok and meta.strip():
        try:
            closest = json.loads(meta)["archived_snapshots"]["closest"]
            snap = closest["url"]
            ts_end = snap.find("/", len("http://web.archive.org/web/"))
            snap = snap[:ts_end] + "id_" + snap[ts_end:]
            ok, h = _curl_text(["-L", snap], 90)
            if '<div class="problem-statement"' in h:
                return h
        except Exception:
            pass

    # fallback: reader proxy in html mode
    start = time.time()
    while time.time() - start < 300:
        ok, out = _curl_text(["-H", "X-Return-Format: html", "-A", CF_UA,
                              "https://r.jina.ai/" + url], 90)
        if ok and '<div class="problem-statement"' in out:
            return out
        time.sleep(15)
    raise RuntimeError(f"cf fetch exhausted: {url}")


def _strip_tags(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</div>|</p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return htmllib.unescape(s).strip()


def scrape_cf_problem(url):
    h = fetch_cf_html(url)
    i = h.find('<div class="problem-statement"')
    if i < 0:
        raise RuntimeError("no problem-statement div")
    seg = h[i:]

    def rx(pat, flags=re.S):
        m = re.search(pat, seg, flags)
        return m

    tl_m = rx(r'class="time-limit".*?</div>\s*([0-9.]+)\s*second')
    ml_m = rx(r'class="memory-limit".*?</div>\s*([0-9.]+)\s*(megabytes|gigabytes)')
    tl = f"{tl_m.group(1)}s" if tl_m else ""
    ml = (f"{ml_m.group(1)}{'G' if ml_m.group(2).startswith('g') else ''}B"
          if ml_m else "")

    in_spec_m = rx(r'<div class="input-specification">(.*?)<div class="(output-specification|sample-tests|note)"')
    out_spec_m = rx(r'<div class="output-specification">(.*?)<div class="(sample-tests|note)"')
    note_m = rx(r'<div class="note"[^>]*>(.*)', )

    def _clean(inner):
        # MathJax delimiters on CF are literal '$$$' — collapse to single '$'.
        inner = re.sub(r"\$\$\$(.+?)\$\$\$", lambda m: "$" + m.group(1) + "$",
                       inner, flags=re.S)
        # keep figures as plain links
        def img_repl(m):
            src = m.group(1)
            if src.startswith("//"):
                src = "https:" + src
            return f"\n\n(figure: {src})\n"
        inner = re.sub(r'<img[^>]*src="([^"]+)"[^>]*>', img_repl, inner, flags=re.S)
        return inner

    def section(inner):
        inner = re.sub(r'<div class="section-title">.*?</div>', "", inner, count=1, flags=re.S)
        return _latex_to_plain(cses_html_to_md(_clean(inner)))

    in_md = section(in_spec_m.group(1)) if in_spec_m else ""
    out_md = section(out_spec_m.group(1)) if out_spec_m else ""

    stmt_start = seg.find("</div>", seg.find("output-file"))
    stmt_start = seg.find("</div>", stmt_start + 6) + 6
    stmt_end = in_spec_m.start() if in_spec_m else (
        out_spec_m.start() if out_spec_m else seg.find('<div class="sample-tests"'))
    stmt = _latex_to_plain(cses_html_to_md(_clean(seg[stmt_start:stmt_end])))

    parts = [stmt]
    if in_md:
        parts.append(f"**Input**\n\n{in_md}")
    if out_md:
        parts.append(f"**Output**\n\n{out_md}")

    ins = [_strip_tags(m.group(1)) for m in
           re.finditer(r'<div class="input"><div class="title">Input</div><pre[^>]*>(.*?)</pre>', seg, re.S)]
    outs = [_strip_tags(m.group(1)) for m in
            re.finditer(r'<div class="output"><div class="title">Output</div><pre[^>]*>(.*?)</pre>', seg, re.S)]
    n = max(len(ins), len(outs))
    if n:
        ex_lines = []
        for k in range(n):
            if len(ins) > 1 or len(outs) > 1:
                ex_lines.append(f"**Example {k + 1}**")
                ex_lines.append("")
            ex_lines.append("Input:")
            ex_lines.append(f"```\n{ins[k] if k < len(ins) else ''}\n```")
            ex_lines.append("")
            ex_lines.append("Output:")
            ex_lines.append(f"```\n{outs[k] if k < len(outs) else ''}\n```")
            ex_lines.append("")
        parts.append("\n".join(ex_lines).rstrip())

    if note_m:
        note_html = note_m.group(1)
        note_html = note_html.split("<script")[0]
        note_html = re.sub(r"</div>\s*$", "", note_html.strip())
        note_html = re.sub(r'<div class="section-title">.*?</div>', "", note_html,
                           count=1, flags=re.S)
        note_md = _latex_to_plain(cses_html_to_md(_clean(note_html)))
        if note_md.strip():
            parts.append(f"**Note**\n\n{note_md}")

    return {"tl": tl, "ml": ml, "body": "\n\n".join(parts)}


def truncate(text, limit, suffix="…"):
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " " + suffix


def fmt_cf_embed(band, total, p, detail):
    fields = []
    limits = " · ".join(x for x in (detail.get("tl"), detail.get("ml")) if x)
    fields.append({"name": "Limits", "value": limits or "—", "inline": True})
    if p.get("tags"):
        fields.append({"name": "Tags",
                       "value": truncate(", ".join(p["tags"]), 200, "…"),
                       "inline": True})
    fields.append({"name": "Position", "value": f"{p['slot']}/{total}",
                   "inline": True})
    return {
        "author": {"name": "Codeforces · CP-31 Sheet"},
        "title": f"{p['slot']}. {p['name']}",
        "url": p["url"],
        "color": 0x2E86C1,
        "description": truncate(detail["body"], 3900, "\n… *(truncated — full statement at the link)*"),
        "fields": fields,
        "footer": {"text": f"band {band} · {total} problems"},
    }


def dump_cp31_band(hooks, token, band, problems):
    key = f"cf-{band}"
    hook = hooks.get(key)
    if not hook:
        print(f"[cp31 {band}] no webhook key {key} — skipped")
        return
    channel_id = find_channel_id(token, str(band))
    problems.sort(key=lambda p: p["slot"])
    print(f"[cp31 {band}] {len(problems)} problems")

    clear_channel(token, channel_id)

    send_embed(hook, {
        "author": {"name": "CP-31 Sheet"},
        "title": f"Band {band}",
        "url": "https://codeforces.com/problemset/",
        "color": 0x2874A6,
        "description": ("31 problems rated " + str(band) + ", one slot per day. "
                        "Full statement on each card. Catalog at the end."),
        "footer": {"text": f"{len(problems)} problems"},
    })

    catalog = [f"**Catalog — band {band}**", ""]
    for p in problems:
        try:
            detail = scrape_cf_problem(p["url"])
        except Exception as exc:
            print(f"scrape failed {p['url']}: {exc}")
            detail = {"tl": "", "ml": "",
                      "body": "*(scrape failed — solve at the link)*"}
        send_embed(hook, fmt_cf_embed(band, len(problems), p, detail))
        catalog.append(f"**{p['slot']}.** {p['name']}")
        print(f"[cp31 {band}] posted {p['slot']}/{len(problems)} {p['name']}")
        time.sleep(max(FETCH_PACE, 2.0))

    payload = {"content": "\n".join(catalog)[:2000], "allowed_mentions": {"parse": []}}
    call(hook, method="POST", body=payload)
    time.sleep(SEND_PACE)
    print(f"[cp31 {band}] catalog posted — done")


CP31_BANDS = [800, 900, 1000, 1100, 1200, 1300,
              1400, 1500, 1600, 1700, 1800, 1900]


def load_cp31():
    d = json.load(open("data/cp31.json"))
    by_band = {}
    for p in d:
        by_band.setdefault(p["band"], []).append(p)
    return by_band


def mode_cp31_all(only=None):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    by_band = load_cp31()
    bands = [only] if only else CP31_BANDS
    for band in bands:
        problems = by_band.get(int(band), [])
        if not problems:
            print(f"[cp31 {band}] no problems in dataset — skipped")
            continue
        dump_cp31_band(hooks, token, int(band), problems)


MODES = {
    "cses-intro": lambda: mode_cses_all(only="Introductory Problems"),
    "cses-all": mode_cses_all,
    "cp31-all": mode_cp31_all,
}


def resolve_mode(mode):
    """cses-intro / cses-all / cses-<section-slug> for any single section."""
    if mode in MODES:
        return MODES[mode]
    m = re.fullmatch(r"cses-(.+)", mode)
    if m:
        slug = m.group(1)
        cats = {t["category"] for t in json.load(open("data/cses.json"))}
        for cat in cats:
            if cat.lower().replace(" ", "-") == slug:
                return lambda: mode_cses_all(only=cat)
        raise SystemExit(f"no CSES section matches slug '{slug}'")
    m = re.fullmatch(r"cp31-(\d{3,4})", mode)
    if m:
        return lambda: mode_cp31_all(only=int(m.group(1)))
    raise SystemExit(f"unknown mode '{mode}'")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: build_catalog.py [cses-all|cses-intro|cses-<section-slug>|...]")
        sys.exit(2)
    resolve_mode(sys.argv[1])()
