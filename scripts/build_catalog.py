"""Static catalog builder: dumps a complete ordered problem list into a channel.

Usage: python3 scripts/build_catalog.py <mode>
Modes:
    cses-intro   — all Introductory Problems tasks, full scraped statements
    core         — dump all 5 domain files (os, cn, db, lld, hld)
    core-<slug>  — single key from the domain files (e.g. core-tdgis)

Webhooks come from $FEED_WEBHOOKS or the local map file. Channel ids resolve
via the bot token in $DISCORD_BOT_TOKEN.
"""

import html as htmllib
import json
import os
import random
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
SEND_PACE = 0.25
FETCH_PACE = 0.2

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


def dump_cses_section(hooks, token, section, tasks, channel_id=None):
    key = "cses-" + section.lower().replace(" ", "-")
    hook = hooks.get(key)
    if not hook:
        print(f"[{section}] no webhook key {key} — skipped")
        return
    channel_id = channel_id or find_channel_id(token, key[5:])  # names drop the cses- prefix
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


def _wayback_variants(snap0):
    ts_end = snap0.find("/", len("http://web.archive.org/web/"))
    base_ts = snap0[:ts_end]
    path = snap0[ts_end:]
    yield base_ts + "id_" + path
    yield base_ts + "if_" + path
    yield snap0


def fetch_cf_html(url):
    """Wayback (closest + CDX alternates, 3 url variants) -> memento ->
    jina. Cycles until deadline."""
    deadline = time.time() + 90
    bare = url.replace("https://", "").replace("http://", "")
    tried = set()
    while time.time() < deadline:
        ok, meta = _curl_text(
            ["http://archive.org/wayback/available?url=" + url], 15)
        if ok and meta.strip():
            try:
                closest = json.loads(meta)["archived_snapshots"]["closest"]
                for snap in _wayback_variants(closest["url"]):
                    if snap in tried:
                        continue
                    tried.add(snap)
                    ok, h = _curl_text(["-L", snap], 30)
                    if '<div class="problem-statement"' in h:
                        return h
            except Exception:
                pass

        ok, cdx = _curl_text(
            ["http://web.archive.org/cdx/search/cdx?url=" + bare +
             "&output=json&filter=statuscode:200"], 15)
        if ok and cdx.strip():
            try:
                rows = json.loads(cdx)[1:]
                random.shuffle(rows)
                for row in rows[:4]:
                    snap = f"http://web.archive.org/web/{row[1]}id_/{row[2]}"
                    if snap in tried:
                        continue
                    tried.add(snap)
                    ok, h = _curl_text(["-L", snap], 30)
                    if '<div class="problem-statement"' in h:
                        return h
            except Exception:
                pass

        ok, mem = _curl_text(
            ["http://timetravel.mementoweb.org/api/json/2026/" + url], 15)
        if ok and mem.strip():
            try:
                data = json.loads(mem)
                snaps = data.get("mementos", {}).get("list", [])
                for s in snaps[:3]:
                    uri = s.get("uri")
                    if not uri or uri in tried:
                        continue
                    tried.add(uri)
                    ok, h = _curl_text(["-L", uri], 30)
                    if '<div class="problem-statement"' in h:
                        return h
            except Exception:
                pass

        ok, out = _curl_text(["-H", "X-Return-Format: html", "-A", CF_UA,
                              "https://r.jina.ai/" + url], 30)
        if ok and '<div class="problem-statement"' in out:
            return out
        time.sleep(3)
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


def _clear_from_slot(token, channel_id, start_slot):
    """Delete bot messages at slot >= start_slot and any catalog message.
    Keeps the intro embed and cards for earlier slots."""
    msgs = call(f"{BASE}/channels/{channel_id}/messages?limit=100", token=token)
    removed = 0
    for msg in msgs:
        if not msg.get("author", {}).get("bot"):
            continue
        embed = (msg.get("embeds") or [{}])[0]
        m = re.match(r"^(\d+)\.", embed.get("title") or "")
        is_catalog = (msg.get("content") or "").startswith("**Catalog")
        if is_catalog or (m and int(m.group(1)) >= start_slot):
            call(f"{BASE}/channels/{channel_id}/messages/{msg['id']}",
                 method="DELETE", token=token)
            time.sleep(0.15)
            removed += 1
    return removed


def dump_cp31_band(hooks, token, band, problems, start_slot=1):
    key = f"cf-{band}"
    hook = hooks.get(key)
    if not hook:
        print(f"[cp31 {band}] no webhook key {key} — skipped")
        return
    channel_id = find_channel_id(token, str(band))
    problems.sort(key=lambda p: p["slot"])
    print(f"[cp31 {band}] {len(problems)} problems (start slot {start_slot})")

    if start_slot <= 1:
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
    else:
        removed = _clear_from_slot(token, channel_id, start_slot)
        print(f"[cp31 {band}] resumed — removed {removed} stale messages")

    todo = [p for p in problems if p["slot"] >= start_slot]

    catalog = [f"**Catalog — band {band}**", ""]
    catalog += [f"**{p['slot']}.** {p['name']}" for p in problems]
    for p in todo:
        try:
            detail = scrape_cf_problem(p["url"])
        except Exception as exc:
            print(f"scrape failed {p['url']}: {exc}")
            detail = {"tl": "", "ml": "",
                      "body": "*(scrape failed — solve at the link)*"}
        send_embed(hook, fmt_cf_embed(band, len(problems), p, detail))
        print(f"[cp31 {band}] posted {p['slot']}/{len(problems)} {p['name']}")
        time.sleep(0.1)

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
    start_slot = int(os.environ.get("CP31_START_SLOT", "1"))
    for band in bands:
        problems = by_band.get(int(band), [])
        if not problems:
            print(f"[cp31 {band}] no problems in dataset — skipped")
            continue
        dump_cp31_band(hooks, token, int(band), problems,
                       start_slot=start_slot if len(bands) == 1 else 1)


LC_GRAPHQL = "https://leetcode.com/graphql"
LC_QUERY = """query q($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    title titleSlug difficulty content
    topicTags { name }
  }
}"""


def fetch_lc_question(slug):
    body = json.dumps({"query": LC_QUERY, "variables": {"titleSlug": slug}}).encode()
    req = urllib.request.Request(
        LC_GRAPHQL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": CF_UA,
                 "Referer": f"https://leetcode.com/problems/{slug}/"})
    start = time.time()
    while time.time() - start < 60:
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
                return (data.get("data") or {}).get("question")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10)
            else:
                return None
        except Exception:
            time.sleep(5)
    return None


def fmt_lc_embed(idx, total, name, slug, q):
    url = f"https://leetcode.com/problems/{slug}/" if slug else ""
    if not q or not q.get("content"):
        embed = {
            "author": {"name": "DSA Topics"},
            "title": f"{idx}. {name}",
            "color": 0x8E44AD,
            "description": ("Classic curated problem — find the statement on "
                            "LeetCode/GeeksforGeeks."),
        }
        if url:
            embed["url"] = url
        return embed
    body_md = _latex_to_plain(cses_html_to_md(q["content"]))
    tags = ", ".join(t["name"] for t in (q.get("topicTags") or [])[:4])
    fields = [{"name": "Difficulty", "value": q.get("difficulty") or "—", "inline": True}]
    if tags:
        fields.append({"name": "Topics", "value": truncate(tags, 200, "…"), "inline": True})
    fields.append({"name": "Position", "value": f"{idx}/{total}", "inline": True})
    return {
        "author": {"name": "DSA Topics · LeetCode"},
        "title": f"{idx}. {q.get('title') or name}",
        "url": url,
        "color": 0x8E44AD,
        "description": truncate(body_md, 3900, "\n… *(truncated — full statement at the link)*"),
        "fields": fields,
    }


def _dump_topic_list(hook, token, channel_name, author, color, items, theory=None, channel_id=None):
    channel_id = channel_id or find_channel_id(token, channel_name)
    clear_channel(token, channel_id)

    intro = {
        "author": {"name": author},
        "title": channel_name.replace("-", " ").title(),
        "color": color,
        "description": ("Curated sequence — every problem in order, statement on "
                        "each card. Catalog at the end."),
        "footer": {"text": f"{len(items)} problems"},
    }
    send_embed(hook, intro)

    if theory:
        send_embed(hook, {
            "author": {"name": author},
            "title": "Concepts first",
            "color": color,
            "description": truncate(theory, 3900, "\n…"),
        })

    catalog = [f"**Catalog — {channel_name.replace('-', ' ').title()}**", ""]
    for i, item in enumerate(items, 1):
        name = item[0]
        slug = item[1] if len(item) > 1 else ""
        q = fetch_lc_question(slug) if slug else None
        send_embed(hook, fmt_lc_embed(i, len(items), name, slug, q))
        catalog.append(f"**{i}.** {name}")
        print(f"[{channel_name}] posted {i}/{len(items)} {name}")
        time.sleep(0.1)

    payload = {"content": "\n".join(catalog)[:2000], "allowed_mentions": {"parse": []}}
    call(hook, method="POST", body=payload)
    time.sleep(SEND_PACE)
    print(f"[{channel_name}] catalog posted — done")


THEORY_KEYS = {
    "stacks-and-queues": "stacks-and-queues", "linked-list": "linked-list",
    "trees": "trees", "graphs": "graphs",
    "searching-and-sorting": "searching-and-sorting",
}


def mode_topics_all(only=None):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    sheet = json.load(open("data/topics_sheet.json"))
    topics = sheet["topics"]
    slugs = [only] if only else list(topics)
    for slug in slugs:
        hook = hooks.get(f"dsa-{slug}")
        if not hook:
            print(f"[{slug}] no webhook — skipped")
            continue
        items = [(it[0], it[1] if len(it) > 1 else "") for it in topics[slug]]
        theory = None
        key = THEORY_KEYS.get(slug)
        if key and key in sheet.get("theory", {}):
            theory = sheet["theory"][key]
        _dump_topic_list(hook, token, slug, "DSA Topics", 0x8E44AD, items, theory)


def mode_topics_concepts():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    sheet = json.load(open("data/topics_sheet.json"))
    hook = hooks.get("dsa-concepts")
    assert hook, "dsa-concepts webhook missing"
    channel_id = find_channel_id(token, "concepts")
    clear_channel(token, channel_id)

    send_embed(hook, {
        "author": {"name": "DSA Topics"},
        "title": "Core Concepts",
        "color": 0x7D3C98,
        "description": ("Foundations before the problem lists. One card per "
                        "concept area."),
        "footer": {"text": f"{len(sheet['theory'])} areas"},
    })
    titles = {
        "intro": "Introduction to Data Structures & Algorithms",
        "stacks-and-queues": "Stacks & Queues", "linked-list": "Linked Lists",
        "trees": "Trees", "graphs": "Graphs", "searching-and-sorting":
        "Sorting & Searching",
    }
    catalog = ["**Catalog — Core Concepts**", ""]
    for i, (key, text) in enumerate(sheet["theory"].items(), 1):
        send_embed(hook, {
            "author": {"name": "DSA Topics"},
            "title": f"{i}. {titles.get(key, key.replace('-', ' ').title())}",
            "color": 0x7D3C98,
            "description": truncate(text, 3900, "\n…"),
        })
        catalog.append(f"**{i}.** {titles.get(key, key)}")
        time.sleep(0.2)
    payload = {"content": "\n".join(catalog), "allowed_mentions": {"parse": []}}
    call(hook, method="POST", body=payload)
    time.sleep(SEND_PACE)
    print("[concepts] done")


def mode_revision():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    sheet = json.load(open("data/topics_sheet.json"))
    hook = hooks.get("dsa-revision")
    items = []
    for group, rows in sheet["revision"].items():
        for r in rows:
            items.append((f"[{group.replace('-', ' ').title()}] {r[0]}",
                          r[1] if len(r) > 1 else ""))
    _dump_topic_list(hook, token, "revision", "Revision Sprint", 0xD35400, items)


def mode_blind75():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    sheet = json.load(open("data/topics_sheet.json"))
    hook = hooks.get("blind-75")
    items = [(r[0], r[1]) for r in sheet["blind75"]]
    _dump_topic_list(hook, token, "blind-75", "Blind 75", 0x2471A3, items)


MODES = {
    "cses-intro": lambda: mode_cses_all(only="Introductory Problems"),
    "cses-all": mode_cses_all,
    "cp31-all": mode_cp31_all,
}



SDE_GROUPS = ["arrays", "linked-list", "stacks-queues-strings",
              "trees-heaps", "graphs", "dp-greedy"]


def mode_sde_all(only=None):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    sheet = json.load(open("data/sde_sheet.json"))
    groups = [only] if only else SDE_GROUPS
    for g in groups:
        hook = hooks.get(f"sde-{g}")
        if not hook:
            print(f"[sde {g}] no webhook — skipped")
            continue
        items = [(r[0], r[1] if len(r) > 1 else "") for r in sheet[g]]
        _dump_topic_list(hook, token, f"sde-{g}", "Striver SDE Sheet",
                         0x1A5276, items)


MODES.update({
    "topics-all": mode_topics_all,
    "topics-concepts": mode_topics_concepts,
    "revision": mode_revision,
    "blind75": mode_blind75,
    "sde-all": mode_sde_all,
})


def mode_notes(only=None):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    notes = json.load(open("data/core_notes.json"))
    keys = [only] if only else list(notes)
    for key in keys:
        note = notes[key]
        hook = hooks.get(key)
        if not hook:
            print(f"[{key}] no webhook — skipped")
            continue
        channel_id = find_channel_id(token, key)
        clear_channel(token, channel_id)
        send_embed(hook, {
            "author": {"name": "Core Engineering"},
            "title": note["title"],
            "color": note["color"],
            "description": ("Full syllabus, one card per topic area. "
                            "Catalog at the end."),
            "footer": {"text": f"{len(note['groups'])} areas"},
        })
        catalog = [f"**Catalog — {note['title']}**", ""]
        for i, (gtitle, gbody) in enumerate(note["groups"], 1):
            send_embed(hook, {
                "author": {"name": "Core Engineering"},
                "title": f"{i}. {gtitle}",
                "color": note["color"],
                "description": truncate(gbody, 3900, "\n…"),
            })
            catalog.append(f"**{i}.** {gtitle}")
            time.sleep(0.2)
        payload = {"content": "\n".join(catalog)[:2000],
                   "allowed_mentions": {"parse": []}}
        call(hook, method="POST", body=payload)
        time.sleep(SEND_PACE)
        print(f"[{key}] done")


def mode_langs(only=None, path="data/lang_notes.json"):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    notes = json.load(open(path))
    keys = [only] if only else list(notes)
    for key in keys:
        note = notes[key]
        hook = hooks.get(key)
        if not hook:
            print(f"[{key}] no webhook — skipped")
            continue
        channel_id = find_channel_id(token, key)
        clear_channel(token, channel_id)
        send_embed(hook, {
            "author": {"name": note["title"]},
            "title": note["title"],
            "color": note["color"],
            "description": note["intro"] + "\n\nOne card per question group, resources card, catalog at the end.",
            "footer": {"text": f"{len(note['groups'])} groups · {sum(len(g[1].splitlines()) for g in note['groups'])} items"},
        })
        catalog = [f"**Catalog — {note['title']}**", ""]
        for i, (gtitle, gbody) in enumerate(note["groups"], 1):
            send_embed(hook, {
                "author": {"name": note["title"]},
                "title": f"{i}. {gtitle}",
                "color": note["color"],
                "description": truncate(gbody, 3900, "\n…"),
            })
            catalog.append(f"**{i}.** {gtitle}")
            time.sleep(0.2)
        res = note.get("resources") or []
        if res:
            lines = [f"{n} → {u}" for n, u in res]
            send_embed(hook, {
                "author": {"name": note["title"]},
                "title": f"{len(note['groups']) + 1}. Topic-wise Resources",
                "color": note["color"],
                "description": "\n".join(lines)[:3900],
            })
            catalog.append(f"**{len(note['groups']) + 1}.** Topic-wise Resources")
        payload = {"content": "\n".join(catalog)[:2000],
                   "allowed_mentions": {"parse": []}}
        call(hook, method="POST", body=payload)
        time.sleep(SEND_PACE)
        print(f"[{key}] done")


def _load_domain_notes():
    merged = {}
    for fn in ["os_notes.json", "cn_notes.json", "db_notes.json",
               "lld_notes.json", "hld_notes.json"]:
        p = f"data/{fn}"
        if os.path.exists(p):
            merged.update(json.load(open(p)))
    return merged


DOMAIN_MAP = {
    "os": ("Operating Systems", "OS Deep Dive"),
    "cn": ("Computer Networks", "Networks Deep Dive"),
    "db": ("Databases", "Database Deep Dive"),
    "lld": ("Low-Level Design", "LLD Deep Dive"),
    "hld": ("High-Level Design", "HLD Deep Dive"),
}


def mode_core(only=None):
    token = os.environ.get("DISCORD_BOT_TOKEN")
    assert token, "DISCORD_BOT_TOKEN required"
    hooks = hooks_map()
    notes = _load_domain_notes()
    keys = [only] if only else list(notes)
    for key in keys:
        note = notes[key]
        hook = hooks.get(key)
        if not hook:
            print(f"[{key}] no webhook — skipped")
            continue
        channel_id = find_channel_id(token, key)
        clear_channel(token, channel_id)
        domain = key.split("-", 1)[0]
        author_name = DOMAIN_MAP.get(domain, ("Core Engineering", "Core"))[1]
        send_embed(hook, {
            "author": {"name": author_name},
            "title": note["title"],
            "color": note["color"],
            "description": note["intro"] + "\n\nOne card per topic group, resources card, catalog at the end.",
            "footer": {"text": f"{len(note['groups'])} groups · {sum(len(g[1].splitlines()) for g in note['groups'])} items"},
        })
        catalog = [f"**Catalog — {note['title']}**", ""]
        for i, (gtitle, gbody) in enumerate(note["groups"], 1):
            send_embed(hook, {
                "author": {"name": author_name},
                "title": f"{i}. {gtitle}",
                "color": note["color"],
                "description": truncate(gbody, 3900, "\n…"),
            })
            catalog.append(f"**{i}.** {gtitle}")
            time.sleep(0.2)
        res = note.get("resources") or []
        if res:
            lines = [f"{n} → {u}" for n, u in res]
            send_embed(hook, {
                "author": {"name": author_name},
                "title": f"{len(note['groups']) + 1}. Topic-wise Resources",
                "color": note["color"],
                "description": "\n".join(lines)[:3900],
            })
            catalog.append(f"**{len(note['groups']) + 1}.** Topic-wise Resources")
        payload = {"content": "\n".join(catalog)[:2000],
                   "allowed_mentions": {"parse": []}}
        call(hook, method="POST", body=payload)
        time.sleep(SEND_PACE)
        print(f"[{key}] done")


MODES.update({
    "notes": mode_notes,
    "langs": mode_langs,
    "core": mode_core,
})


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
    m = re.fullmatch(r"topics-(.+)", mode)
    if m and m.group(1) in json.load(open("data/topics_sheet.json"))["topics"]:
        return lambda: mode_topics_all(only=m.group(1))
    m = re.fullmatch(r"sde-(.+)", mode)
    if m and m.group(1) in SDE_GROUPS:
        return lambda: mode_sde_all(only=m.group(1))
    m = re.fullmatch(r"langs-(.+)", mode)
    if m and m.group(1) in json.load(open("data/lang_notes.json")):
        return lambda: mode_langs(only=m.group(1))
    m = re.fullmatch(r"core-(.+)", mode)
    if m and m.group(1) in _load_domain_notes():
        return lambda: mode_core(only=m.group(1))
    raise SystemExit(f"unknown mode '{mode}'")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: build_catalog.py [cses-all|cses-intro|cses-<section-slug>|...]")
        sys.exit(2)
    resolve_mode(sys.argv[1])()
