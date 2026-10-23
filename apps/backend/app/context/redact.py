"""Secret handling for anything that may reach a model or a log (plan §7)."""

import re
from pathlib import PurePosixPath

# Files that are never read into model context.
_SECRET_FILE_PATTERNS = (
    re.compile(r"^\.env(\..*)?$"),
    re.compile(r"^.*\.(pem|key|p12|pfx|keystore|jks)$"),
    re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"^\.(npmrc|pypirc|netrc)$"),
    re.compile(r"^credentials(\.json)?$"),
)

_SECRET_VALUE_PATTERNS = (
    # Provider-style keys.
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{30,})\b"),
    re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)

# key = value / key: value assignments whose key looks secret.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|secret|token|password|passwd)[A-Z0-9_]*)"
    r"(\s*[:=]\s*)([\"']?)([^\s\"']{6,})\3"
)

REDACTED = "[REDACTED]"


def is_secret_file(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return any(pattern.match(name) for pattern in _SECRET_FILE_PATTERNS)


def redact(text: str) -> str:
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _SECRET_ASSIGNMENT.sub(lambda m: f"{m[1]}{m[2]}{m[3]}{REDACTED}{m[3]}", text)
