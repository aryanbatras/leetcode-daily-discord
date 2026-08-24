# MF Grind Roadmap — Discord as a full DSA learning machine

Principles locked by owner:
- **GitHub Actions only.** No Workers, no servers, no always-on anything.
- **Gentle to upstream APIs**: every design below costs <40 upstream calls/day combined.
- **Stateless-first**: schedules derive "what to post today" deterministically (date-seeded),
  so no database is needed beyond small JSON state we already commit back.
- Repo is public → unlimited Actions minutes; current burn is ~1–2 runner-minutes/day.

## Data sources (all verified live)

| Source | What it gives | Cost |
|---|---|---|
| LeetCode GraphQL `activeDailyCodingChallengeQuestion` | official daily | 1 call |
| LeetCode GraphQL `question(titleSlug)` | statement, difficulty, tags, acceptance | 1 call/problem |
| LeetCode GraphQL `problemsetQuestionList` with `filters:{tags:[...]}`, `skip=random`, `limit=1` | random problem for ANY topic tag (+`total` for range) | 1–2 calls/channel/day |
| zerotrac ratings JSON | difficulty rating for any LC problem | 1 cached file |
| kamyu104/LeetCode-Solutions | solution file for nearly every problem at deterministic path `C++/{slug}.cpp`, `Python/{slug}.py` | 0 calls (URL construction) |
| doocs/leetcode | alt multi-language solutions, same slug convention | 0 calls |
| NeetCode JSON (khush2808/dsa-sheets `data/neetcode-problems.json`) | Blind75/150/250 lists + video links | vendored weekly, 0 runtime calls |
| Striver sheets JSON (same repo: A2Z, SDE, 79, Blind-75-TUF) | curated curricula in order | vendored weekly, 0 runtime calls |
| Codeforces `api/problemset.problems` | ALL problems with `rating` 800–3500, `tags`, `solvedCount`; no auth | 1 call, cached weekly in-repo |
| Codeforces `api/contest.list` | upcoming contests | 1 call/day |

## Phases

### Phase 0 — shipped
- Daily problem card 06:00 IST with @everyone ping (#daily-problem)
- Weekly board 08:00 IST, Monday reset (#leaderboard)
- `!register` / `!remove` with reply confirmations + lifetime stats

### Phase 1 — editorial links on the daily (next up, ~zero risk)
Daily embed gains a "Learn" section:
- Solution (C++) and Solution (Python) → kamyu104 blob URLs (constructed, verified with HEAD request; omitted if missing)
- Community editorials → `leetcode.com/problems/{slug}/solutions/`
- NeetCode video if the slug appears in the vendored NeetCode JSON

### Phase 2 — topic channels
Channels like `arrays`, `strings`, `dynamic-programming`, `trees`, `graphs`, `binary-search`.
Each posts one random non-premium tagged problem daily (difficulty rotation Easy→Hard through the week).
Implementation: one workflow, loops a committed `topics.json` map {channel: webhook}; 1–2 LC calls per topic.

### Phase 3 — codeforces channel(s)
- Daily random CF problem, rating band rotates through the week (800 → 3500), tag filter optional.
- Problemset JSON fetched once weekly and committed; daily picks are date-seeded → reruns never duplicate.
- Bonus: `contest.list` powers an "upcoming contests" line in #general every morning.

### Phase 4 — curated tracks ("sheets")
Channels `blind-75`, `neetcode-150`, `striver-a2z`, `sde-79`: post the NEXT item in order daily
(index = days-since-launch mod length → inherently stateless). Vendored JSON refreshed weekly by CI.
Each entry links the LC/GfG problem + Striver/NeetCode article/video.

### Phase 5 — optional, only if asked
- CF rating-band ladders (newbie/pupil/specialist channels)
- Company-tagged interview channel (LC company tags need premium — would use community datasets instead)
- Per-track completion tracking (stateful; extends members.json)

## Runner-minute budget
Single consolidated daily workflow: fetch → compose → post everything ≈ 60–90s.
Poller: ~15s × 288 runs/day ≈ 70 min/day worst case, still far under limits; can drop to */10 anytime.
