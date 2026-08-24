# leetcode-daily-discord

Mission Faang's automation: daily LeetCode problem + local weekly leaderboard, zero servers.

## What runs here
| Workflow | Schedule (IST) | What it does |
|---|---|---|
| Post LeetCode Daily | 06:00 daily | Fetches today's problem from LeetCode's API, posts full statement + examples + rating into #daily-problem, pings everyone |
| Process registrations | every 10 min | Reads `!register <username>` / `!remove` in #leaderboard via the bot token, validates against LeetCode, reacts |
| Post weekly board | 08:00 daily | Snapshots each member's solved totals, computes week-to-date deltas (Mon reset), posts the board |

State (`data/*.json`) is committed back by Actions — that IS the database.

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
