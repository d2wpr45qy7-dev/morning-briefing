#!/usr/bin/env python3
"""
daily_sync.py -- runs once a day via a local launchd job on Marcus's Mac.

WHAT IT DOES, in order:
  1. Rebuilds a Schwab client from the cached refresh token (schwab_client.py).
     No browser, no prompts -- fails loudly (see below) if the one-time
     --login step hasn't been done yet, or if the token has gone stale.
  2. Pulls current positions (symbol, shares, per-share cost basis).
  3. Writes them into scripts/portfolio-tracker/portfolio_config.json in the
     local clone of the morning-briefing repo, replacing the "holdings" list
     wholesale (whatever Schwab reports IS the current truth) but preserving
     the file's _comment.
  4. Commits and pushes that change to GitHub, so tomorrow's 7:07am briefing
     -- which clones the repo fresh in the cloud and never touches Schwab
     itself -- sees real numbers instead of nulls.

This also has a side effect that matters: touching the cached token here
every day is what keeps it alive. Schwab expires a refresh token 7 days
after its LAST use, so a daily run means Marcus never has to re-login,
as long as this job keeps firing (i.e. his Mac is on/awake at run time at
least once every 7 days).

FAILURE MODE: if the token has expired (Mac was off for a week, or the
one-time login was never done) this exits non-zero with a clear message
and changes NOTHING -- it does not silently write nulls over an existing
portfolio_config.json. Check sync.log in this directory when troubleshooting.

USAGE (normally invoked by the launchd plist, not by hand):
  python3 daily_sync.py [--repo /path/to/local/morning-briefing/clone]
"""
import argparse
import json
import os
import subprocess
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.abspath(os.path.join(HERE, "..", ".."))  # repo root, two levels up
CONFIG_PATH_REL = os.path.join("scripts", "portfolio-tracker", "portfolio_config.json")
LOG_PATH = os.path.join(HERE, "sync.log")


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_env_file():
    """Source SCHWAB_APP_KEY / SCHWAB_APP_SECRET from a local .env file if
    present, without requiring the launchd job's environment to have them
    pre-set (launchd jobs get a minimal environment by default)."""
    env_path = os.path.join(HERE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line[len("export "):] if line.startswith("export ") else line
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


def run(cmd, cwd, check=True):
    log(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout.strip():
        log(result.stdout.strip())
    if result.stderr.strip():
        log(result.stderr.strip())
    if check and result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO, help="path to local morning-briefing clone")
    args = ap.parse_args()

    load_env_file()
    sys.path.insert(0, HERE)
    import schwab_client  # local import, after HERE is on sys.path

    log("=== daily_sync starting ===")

    try:
        holdings = schwab_client.fetch_positions()
    except SystemExit:
        raise
    except Exception as e:
        log(f"ERROR fetching positions: {e}")
        raise SystemExit(1)

    if not holdings:
        log("WARNING: Schwab returned zero positions. Not overwriting portfolio_config.json "
            "with an empty list -- this is more likely an API hiccup than an empty account. "
            "Leaving the existing file untouched.")
        return

    config_path = os.path.join(args.repo, CONFIG_PATH_REL)
    if not os.path.exists(config_path):
        log(f"ERROR: expected config at {config_path}, not found. Is --repo pointed at a "
            "real local clone of the morning-briefing repo?")
        raise SystemExit(1)

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    config["holdings"] = holdings
    config["_comment"] = (
        "Real share counts and cost basis, synced automatically from Schwab by "
        "daily_sync.py. Do not hand-edit -- it'll be overwritten on the next sync."
    )
    config["_last_synced"] = datetime.date.today().isoformat()

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    log(f"Wrote {len(holdings)} holdings to {config_path}")

    # Pull first in case the cloud scheduled task committed something (e.g. history.jsonl)
    # since this last ran, then commit + push our change.
    run(["git", "pull", "--rebase", "-q", "origin", "main"], cwd=args.repo)
    run(["git", "add", CONFIG_PATH_REL], cwd=args.repo)
    status = run(["git", "status", "--porcelain"], cwd=args.repo, check=False)
    if not status.stdout.strip():
        log("No changes to commit (holdings unchanged since last sync).")
        return
    run(["git", "commit", "-q", "-m", f"Sync Schwab holdings {datetime.date.today().isoformat()}"], cwd=args.repo)
    run(["git", "push", "-q", "origin", "main"], cwd=args.repo)
    log("=== daily_sync complete ===")


if __name__ == "__main__":
    main()
