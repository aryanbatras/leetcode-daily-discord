# MF Grind Roadmap v2 — Discord as a full DSA learning machine

Principles locked by owner:
- GitHub Actions only. No Workers/servers. Public repo → unlimited minutes (~1–3/day used).
- Gentle upstream: <40 external calls/day total across everything below.
- Stateless-first: date-seeded schedules; small committed JSON state only where unavoidable.
- Editorials ≠ solutions: posts lead with explanations/screenshots; code links are clearly
  labeled reference-only.

## Verified data sources

| Feed | Source | Refresh |
|---|---|---|
| LC daily | GraphQL activeDailyCodingChallengeQuestion | live |
| LC random-by-tag | GraphQL problemsetQuestionList(filters.tags, skip=rand(total)) | live |
| LC statement/details | GraphQL question(titleSlug) | live |
| **Editorial screenshots** | akhil/leetcode-screenshotter `editorial-screenshots/{1-999,1000-1999,2000+}/{id}. {Title}.png` (~1077 PNGs, gaps exist) | index JSON vendored weekly via git-trees API (1 call/wk); lookup by frontendId at post time |
| LC editorials | leetcode.com/problems/{slug}/solutions/ | link only |
| NeetCode video | neetcode-problems.json (vendored) | 1 fetch/wk |
| Codeforces problems | api/problemset.problems (rating, tags, solvedCount) | 1 call/wk cached in-repo |
| Codeforces contests | api/contest.list | 1 call/day |
| **CP-31 (TLE)** | its-asif/TLE-CP-31 filenames `{contestId}{index}-{Name}.cpp` per rating folder 800–1900 (31/band) | parsed weekly into cp31.json (1 trees call) |
| CSES (~300 tasks) | scrape cses.fi/problemset/ → task ids + names | 1 scrape/mo |
| Curated DSA sheets | GFGSC-RTU/All-DSA-Sheets xlsx (Babbar450, Apna375, Arsh280, Fraz250…) + khush2808 JSONs (A2Z, SDE, Blind75, NeetCode150/250) | vendored weekly |
| TUF core subjects (OS/CN/DBMS) | takeuforward.org extraction (adapt khush2808 scripts) | vendored weekly |

## Channel architecture

```
leetcode/        arrays · strings · binary-search · linked-list
                 stacks-and-queues · trees · graphs · dynamic-programming
cp/              codeforces · cp31 · cses
tracks/          blind-75 · neetcode-150 · striver-a2z · core-subjects
existing         chat/general · focus-sessions/* · bots/daily-problem·leaderboard·bot-guide·contests
```

## Post formats

- **LC anywhere** (daily + topic): full rich card (statement/examples/difficulty/rating/tags)
  + "Learn" section: screenshot link (if indexed) → LC solutions page → NeetCode video →
  labeled "Reference code (spoilers)": kamyu104 C++/Python links.
- **codeforces**: name, rating color-coded by band, tags, solvedCount, contest link.
  Band rotates Mon→Sun: 800/900/1000/1100/1200/1400/1600+ (tunable).
- **cp31**: today's slot = day-number mod 372, ordered band asc → steady 372-day curriculum;
  card shows band, CF link, and "idea of the day" framing.
- **cses**: sequential task card (id order ≈ difficulty order) with technique hint from its set name.
- **tracks**: strictly next-in-order; progress = days since launch mod length (stateless).
- **core-subjects**: one interview Q&A per day, rotating OS→CN→DBMS.
- **#contests** (+ morning line in #general): upcoming LC + CF contests sorted by start time.

## Call budget (everything ON)
LC: daily(1) + topics(8×2) + zerotrac(cached) ≈ 17 · CF: problems(0, cached wkly) + contests(1)
Screenshots/trees/cp31/sheets: ~6 calls/WEEK · CSES: 1 scrape/MONTH → well under budget.

## Build order (each phase shipped + tested before next)
1. P1 Editorial upgrade on existing daily (+ vendored screenshot index + NeetCode map)
2. P2 `leetcode/` topic channels (8) with tagged random dailies
3. P3 `cp/`: codeforces + cp31 + cses channels
4. P4 `tracks/`: blind-75, neetcode-150, striver-a2z, core-subjects
5. P5 #contests feed + morning line
All consolidated into ONE daily workflow (~90s runner time) + existing poller/board jobs.
