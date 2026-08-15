#!/usr/bin/env python3
"""
schwab_client.py -- thin wrapper around the schwab-py library for two things:

  1. ONE-TIME interactive login (--login). Opens your default browser to
     Schwab's OAuth page, you log in and approve, and the resulting refresh
     token gets cached to .schwab_token_cache.json in this same directory.
     This step MUST be run by Marcus personally, on his own machine, in his
     own browser. Nothing else in this pipeline can or should do this step
     for him -- it requires his actual Schwab credentials + MFA.

  2. Everyday reuse (fetch_positions(), imported by daily_sync.py). Rebuilds
     an authenticated client from the cached token WITHOUT any browser
     interaction, as long as the refresh token is still valid. Schwab's
     refresh tokens hard-expire 7 days after they're last used -- there is no
     way around this, it's a platform rule, not a bug here. As long as
     daily_sync.py runs at least once a week (it's meant to run daily via
     launchd) the token never goes stale and you never see the login screen
     again after the initial --login.

REQUIRES (never committed to git -- see .gitignore):
  SCHWAB_APP_KEY     -- App Key from your app at https://developer.schwab.com
  SCHWAB_APP_SECRET  -- App Secret, same place
  Both must be set as real environment variables before running --login.
  The simplest way: create a file called .env in this directory (gitignored
  already) with:
      export SCHWAB_APP_KEY="..."
      export SCHWAB_APP_SECRET="..."
  and `source .env` before running this script, or let daily_sync.py source
  it automatically (it looks for .env in this same directory).

CALLBACK URL: when you register the app in the Schwab developer portal, set
its callback/redirect URI to exactly:
      https://127.0.0.1:8182
  schwab-py's login flow spins up a short-lived local HTTPS listener on that
  port to catch the redirect -- nothing needs to be internet-reachable.

USAGE:
  python3 schwab_client.py --login        # one-time, interactive, run by Marcus
  python3 schwab_client.py --check        # non-interactive sanity check of the cached token
  python3 schwab_client.py --positions    # print current positions as JSON (for manual testing)
"""
import argparse
import json
import os
import sys

TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".schwab_token_cache.json")


def _get_app_credentials():
    api_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_APP_SECRET")
    if not api_key or not app_secret:
        print(
            "ERROR: SCHWAB_APP_KEY / SCHWAB_APP_SECRET are not set in the environment.\n"
            "Create a .env file in this directory (see the module docstring) with both\n"
            "values from your app at https://developer.schwab.com, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    return api_key, app_secret


def _import_schwab_py():
    try:
        import schwab  # noqa: F401
        return schwab
    except ImportError:
        print(
            "ERROR: the schwab-py library isn't installed in this Python environment.\n"
            "Run: pip3 install schwab-py",
            file=sys.stderr,
        )
        sys.exit(1)


def login_flow():
    """One-time interactive login. Run this yourself, once, in a real terminal
    on your own machine. It opens a browser window -- log in to Schwab there
    and approve access. Do not run this unattended or hand it to anything
    else to run on your behalf."""
    schwab = _import_schwab_py()
    api_key, app_secret = _get_app_credentials()
    callback_url = "https://127.0.0.1:8182"
    print("Opening browser for Schwab login... complete the login and approval there.")
    client = schwab.auth.client_from_login_flow(
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=TOKEN_PATH,
    )
    print(f"Success. Refresh token cached to: {TOKEN_PATH}")
    print("From now on, daily_sync.py can pull positions without any browser step,")
    print("as long as it (or this script with --check) runs at least once every 7 days.")
    return client


def client_from_cache():
    """Rebuild an authenticated client from the cached token. No browser, no
    prompts. Raises SystemExit with a clear message if the cache is missing
    or the refresh token has expired (>7 days unused) -- in that case the
    only fix is re-running --login."""
    schwab = _import_schwab_py()
    api_key, app_secret = _get_app_credentials()
    if not os.path.exists(TOKEN_PATH):
        print(
            f"ERROR: no cached token at {TOKEN_PATH}.\n"
            "Run: python3 schwab_client.py --login   (one-time, interactive, do this yourself)",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        client = schwab.auth.client_from_token_file(TOKEN_PATH, api_key, app_secret)
    except Exception as e:
        print(
            f"ERROR: couldn't reuse the cached token ({e}).\n"
            "Most likely cause: it's been more than 7 days since this last ran successfully,\n"
            "and Schwab's refresh token expired. Fix: python3 schwab_client.py --login\n"
            "(one-time, interactive, do this yourself).",
            file=sys.stderr,
        )
        sys.exit(1)
    return client


def fetch_positions():
    """Returns a list of {symbol, shares, cost_basis_per_share} dicts for
    every equity/ETF/crypto-proxy position in the linked Schwab account(s).
    Used by daily_sync.py. Requires a valid cached token -- see client_from_cache()."""
    client = client_from_cache()
    resp = client.get_accounts(fields=[client.Account.Fields.POSITIONS])
    resp.raise_for_status()
    data = resp.json()

    holdings = []
    for account_wrapper in data:
        acct = account_wrapper.get("securitiesAccount", {})
        for pos in acct.get("positions", []):
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol")
            if not symbol:
                continue
            shares = pos.get("longQuantity", 0) - pos.get("shortQuantity", 0)
            if not shares:
                continue
            cost_basis_total = pos.get("averagePrice")  # per-share avg price, per Schwab's schema
            holdings.append({
                "symbol": symbol,
                "shares": shares,
                "cost_basis_per_share": cost_basis_total,
            })
    return holdings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="one-time interactive login (run this yourself)")
    ap.add_argument("--check", action="store_true", help="non-interactive check that the cached token still works")
    ap.add_argument("--positions", action="store_true", help="print current positions as JSON")
    args = ap.parse_args()

    if args.login:
        login_flow()
    elif args.check:
        client_from_cache()
        print("OK: cached token is valid.")
    elif args.positions:
        print(json.dumps(fetch_positions(), indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
