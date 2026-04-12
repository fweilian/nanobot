#!/usr/bin/env python3
"""Generate JWT tokens for nanobot cloud API testing."""

import argparse
import os
import secrets
import sys
import time

import jwt


def make_token(user_id: str, shared_secret: str) -> str:
    """Create a JWT token for the nanobot cloud API."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iss": "nanobot-cloud-e2e",
        "aud": "nanobot-cloud",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, shared_secret, algorithm="HS256")


def main():
    parser = argparse.ArgumentParser(description="Generate JWT tokens for nanobot cloud API")
    parser.add_argument(
        "--shared-secret",
        default=os.environ.get("NANOBOT_CLOUD_AUTH__SHARED_SECRET"),
        help="Shared secret used by the backend (or NANOBOT_CLOUD_AUTH__SHARED_SECRET env var)",
    )
    parser.add_argument(
        "--generate-secret",
        action="store_true",
        help="Generate a new random shared secret (for testing only)",
    )
    parser.add_argument("users", nargs="*", default=["alice", "bob", "test"],
                        help="User IDs to generate tokens for (default: alice bob test)")
    args = parser.parse_args()

    if args.generate_secret:
        secret = secrets.token_urlsafe(32)
        print(f"# Generated secret (use with backend): {secret}")
        print()
    elif not args.shared_secret:
        print("Error: --shared-secret is required (or set NANOBOT_CLOUD_AUTH__SHARED_SECRET)", file=sys.stderr)
        print("Hint: If testing locally, you can use --generate-secret to create a secret", file=sys.stderr)
        sys.exit(1)
    else:
        secret = args.shared_secret

    print(f"# Tokens using secret: {secret[:8]}...")
    print()
    for user in args.users:
        token = make_token(user, secret)
        print(f"# {user}:")
        print(f"{token}")


if __name__ == "__main__":
    main()
