"""Shared-password session auth -- deliberately not a user account system:
the setting is always exactly one licensed operator (docs/PROJECT_PLAN.md
section 1), so a single server-side password plus an opaque session token
per logged-in browser tab is the whole model. No password is ever
hardcoded: WEB_TRX_PASSWORD must be set, or one is generated and printed
to stderr once at startup (the same "generate and print" pattern Jupyter
uses) -- either way nothing guessable ships in source.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys
import time

COOKIE_NAME = "web_trx_token"
DEFAULT_TOKEN_TTL_S = 12 * 3600


class AuthManager:
    def __init__(self, password: str | None = None, token_ttl_s: float = DEFAULT_TOKEN_TTL_S):
        self.password = password or os.environ.get("WEB_TRX_PASSWORD") or self._generate_and_print()
        self.token_ttl_s = token_ttl_s
        self._tokens: dict[str, float] = {}  # token -> issued_at (time.monotonic())

    @staticmethod
    def _generate_and_print() -> str:
        password = secrets.token_urlsafe(12)
        print(
            f"WEB_TRX_PASSWORD not set -- generated one-time password for this run: {password}",
            file=sys.stderr,
        )
        return password

    def check_password(self, candidate: str) -> bool:
        # Constant-time compare -- a login endpoint is exactly the kind of
        # place a timing side-channel on string comparison matters.
        return hmac.compare_digest(candidate, self.password)

    def issue_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = time.monotonic()
        return token

    def validate(self, token: str | None) -> bool:
        if not token or token not in self._tokens:
            return False
        if time.monotonic() - self._tokens[token] > self.token_ttl_s:
            del self._tokens[token]
            return False
        return True

    def revoke(self, token: str | None) -> None:
        if token:
            self._tokens.pop(token, None)
