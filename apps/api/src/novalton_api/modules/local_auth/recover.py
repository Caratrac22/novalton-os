"""Local privileged owner recovery. No HTTP route or password arguments."""

import argparse
import asyncio
import getpass
import sys

from novalton_api.modules.local_auth.bootstrap import BootstrapDenied, run_recovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover the configured Novalton owner locally")
    parser.add_argument("login", help="Existing local owner login")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("Local terminal required", file=sys.stderr)
        return 1
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords differ", file=sys.stderr)
        return 1
    try:
        asyncio.run(run_recovery(args.login, password))
    except (BootstrapDenied, ValueError) as exc:
        print(f"Recovery unavailable: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Recovery unavailable: database operation failed", file=sys.stderr)
        return 1
    print("Password replaced; existing sessions revoked. Sign in again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
