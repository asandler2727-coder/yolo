# Running the bot on the Windows desktop (paper mode)

One-time setup:
1. Install Docker Desktop for Windows (docker.com) and start it. Enable
   "Start Docker Desktop when you sign in to your computer" in its settings.
2. Install Git for Windows (git-scm.com), open "Git Bash".
3. In Git Bash: `git clone https://github.com/asandler2727-coder/yolo.git && cd yolo`
4. `cp .env.example .env`, then edit `.env` in Notepad: set a long random
   FT_JWT_SECRET and a real FT_PASS.

Start the bot: `docker compose up -d`
Watch it: open http://127.0.0.1:8080 in a browser — login `yolo` / your FT_PASS.
Daily check: `docker compose logs --since 24h freqtrade | tail -50` and run
  `py scripts/health_check.py` (needs `py -m pip install freqtrade-client` once).
Stop the bot (kill switch): `docker compose down`
Update to latest code: `git pull && docker compose up -d --force-recreate`

The 2-week dry-run clock (spec §9) starts at the first `docker compose up -d`
and the decision date goes in docs/backtests.md the same day.
