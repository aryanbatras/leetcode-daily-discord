# leetcode-daily-discord

Posts the official LeetCode daily challenge to a Discord channel automatically via GitHub Actions.

## How it works
1. `post_daily.py` fetches the daily problem from LeetCode's public GraphQL API.
2. It posts an embed to Discord through a channel webhook.
3. GitHub Actions runs it on cron (`30 2 * * *` UTC = 08:00 IST) or on demand.

## Setup (already done for Mission Faang)
- Repo secret: `DISCORD_WEBHOOK_URL` — webhook of the target Discord channel.
- Trigger manually anytime: `gh workflow run post-daily.yml`

## Testing
GitHub Actions' minimum schedule granularity is 5 minutes; use `workflow_dispatch` for instant runs.
