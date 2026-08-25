# leetcode-daily-discord

Mission Faang's automation: daily LeetCode problem, contests, and leaderboard — zero servers.

## What runs here
| Step | Schedule (IST) | What it does |
|---|---|---|
| Daily problem | 06:00 daily | Fetches today's LeetCode problem, posts to #daily-problem (clears old messages first) |
| Contest calendar | 06:00 daily | Posts upcoming LeetCode + Codeforces contests to #upcoming-contests |
| Poll registrations | 06:00 daily | Scans #register for new usernames, validates against LeetCode, reacts ✅/❌ |
| Leaderboard | 06:00 daily | Fetches stats for all registered members, posts ranked board to #leaderboard |

All automated via a single GitHub Actions workflow (`daily.yml`).

## How to join the leaderboard
1. Go to **#register**
2. Type your **LeetCode username**
3. Bot validates and reacts ✅ — you're in

## Secrets
- `DISCORD_BOT_TOKEN` — bot token (MESSAGE CONTENT intent required)
- `DISCORD_WEBHOOK_URL` — #daily-problem webhook
- `LEADERBOARD_WEBHOOK_URL` — #leaderboard webhook
- `FEED_WEBHOOKS` — full webhook map JSON for build_catalog.py

## Manual runs
```
gh workflow run daily.yml
```
