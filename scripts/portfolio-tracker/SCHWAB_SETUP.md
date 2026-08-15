# One-time Schwab setup (Marcus does this part personally)

Everything that can be prepped ahead of time is done: `schwab_client.py`,
`daily_sync.py`, and a local automation job are already staged on your Mac.
This is the part that's yours alone -- it needs your actual Schwab login,
so nothing else can do it for you.

## Prerequisite: developer app approved

Wait for your app at https://developer.schwab.com to flip from "pending" to
"ready to use." Usually takes a few business days.

## Step 1 -- get your App Key and App Secret

In the developer portal, open your app and copy the App Key and App Secret.
When you registered it, the callback/redirect URL should have been set to
exactly `https://127.0.0.1:8182` -- if it isn't, edit the app and fix that
now (schwab_client.py's login flow listens on that exact address).

## Step 2 -- drop your credentials into the local .env file

A file has already been created at:

    ~/Claude/schwab-portfolio-sync/morning-briefing/scripts/portfolio-tracker/.env

Open it and fill in the two blanks:

    export SCHWAB_APP_KEY="paste your App Key here"
    export SCHWAB_APP_SECRET="paste your App Secret here"

This file is gitignored -- it will never get committed or leave your machine.

## Step 3 -- run the one-time login

Open Terminal and run:

    source ~/Claude/schwab-portfolio-sync/venv/bin/activate
    cd ~/Claude/schwab-portfolio-sync/morning-briefing/scripts/portfolio-tracker
    source .env
    python3 schwab_client.py --login

A browser window opens to Schwab's login page. Log in and approve access.
When it's done, you'll see "Success. Refresh token cached to: ..." -- that's
the whole thing. You will not need to do this again unless your Mac goes a
full 7 days without running the daily sync job (see below), in which case
just repeat this step.

## Step 4 -- sanity check

    python3 schwab_client.py --positions

Should print your actual Schwab positions as JSON. If it does, everything's
wired up correctly and the daily automated job (already installed, see
`~/Library/LaunchAgents/com.marcus.schwabsync.plist`) will keep it fresh
from here on -- no more manual steps.

## What you never have to do again

- Re-enter your Schwab password day to day.
- Manually update `portfolio_config.json` -- the daily job overwrites it
  with real data and pushes it to the repo automatically, every morning
  before your 7:07am briefing runs.
