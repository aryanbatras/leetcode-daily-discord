# leetcode-daily-discord

Mission Faang's automation: daily LeetCode problem + CodeGrind leaderboard, zero servers.

## What runs here
| Workflow | Schedule (IST) | What it does |
|---|---|---|
| Post LeetCode Daily | 06:00 daily | Fetches today's problem from LeetCode's API, posts full statement + examples + rating into #daily-problem, pings everyone |
| Post weekly board | 08:00 daily | Snapshots each member's solved totals, computes week-to-date deltas (Mon reset), posts the board |

The leaderboard is managed by **CodeGrind bot** — members join via `/add` in #leaderboard (no `!register` needed).

State (`data/*.json`) is committed back by the bot.

## Secrets
- `DISCORD_WEBHOOK_URL` — #daily-problem webhook
- `LEADERBOARD_WEBHOOK_URL` — #leaderboard webhook
- `DISCORD_BOT_TOKEN` — bot application token; needs MESSAGE CONTENT intent enabled in the dev portal

## Manual runs
```
gh workflow run post-daily.yml
gh workflow run register.yml
gh workflow run weekly-board.yml
```

Note: GitHub pauses cron workflows on repos with no commits for 60 days — any commit re-enables.
