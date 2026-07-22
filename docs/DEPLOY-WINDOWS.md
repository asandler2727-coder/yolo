# Preparing the Windows desktop (paper mode is not approved)

**Current status:** do not start the bot. Family A and Family B are retired, and no strategy
has approval to begin the two-week paper gate. The launcher is fail-closed by default.

One-time setup:
1. Install Docker Desktop for Windows (docker.com) and start it. Enable
   "Start Docker Desktop when you sign in to your computer" in its settings.
2. Install Git for Windows (git-scm.com), open "Git Bash".
3. In Git Bash: `git clone https://github.com/asandler2727-coder/yolo.git && cd yolo`
4. `cp .env.example .env`, then edit `.env` in Notepad: set a long random
   FT_JWT_SECRET and a real FT_PASS.

Stop after the one-time setup. Do not run `docker compose up`, `docker compose run`, or any
Freqtrade trade command. The retained `MemeMomentum` class is retired research evidence.

Future launch instructions will be added only after a strategy passes the required research
review and Austin explicitly approves paper trading. That future approval must also record the
exact strategy and image version; merely cloning this repository never grants approval.
