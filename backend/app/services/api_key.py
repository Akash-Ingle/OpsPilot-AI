"""API key generation and verification for project (tenant) authentication.

Keys look like ``opsp_<random>``. Only their SHA-256 hash is persisted; the raw
key is returned to the caller exactly once at creation time. Verification hashes
the presented key and looks it up by hash.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

_KEY_PREFIX = "opsp_"


@dataclass(frozen=True)
class GeneratedKey:
    raw: str          # full secret, shown to the user once
    key_hash: str     # SHA-256 hex, stored in the DB
    display_prefix: str  # short non-secret identifier, e.g. "opsp_a1b2c3"


def hash_key(raw: str) -> str:
    """Return the SHA-256 hex digest used to look a key up in the DB."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> GeneratedKey:
    """Create a new random API key and its stored hash + display prefix."""
    raw = f"{_KEY_PREFIX}{secrets.token_urlsafe(24)}"
    return GeneratedKey(
        raw=raw,
        key_hash=hash_key(raw),
        display_prefix=raw[: len(_KEY_PREFIX) + 6],
    )


__all__ = ["GeneratedKey", "generate_key", "hash_key"]
