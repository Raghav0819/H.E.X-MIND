"""Project profile: which checks the sandbox may run for a project (plan §6, §7).

Read from `.hexmind/profile.yaml` in the **user's workspace** (never the agent worktree, which
agents could edit). Without a profile, one is detected from the project files. Agents choose a
check by name; they never supply a command line.

    image: node:22-alpine
    checks:
      test: node --test
      lint: npx eslint .
"""

import json
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

PROFILE_PATH = ".hexmind/profile.yaml"
_CHECK_NAME = r"^[a-z][a-z0-9_-]{0,31}$"


class ProfileError(ValueError):
    pass


class Profile(BaseModel):
    image: str
    checks: dict[str, str] = Field(default_factory=dict)
    source: str = "detected"

    def command(self, name: str) -> str:
        if name not in self.checks:
            raise ProfileError(
                f"unknown check '{name}'; available: {', '.join(self.checks) or 'none'}"
            )
        return self.checks[name]


class _ProfileFile(BaseModel):
    image: str
    checks: dict[str, str]


def load_profile(workspace: Path, worktree: Path, allowed_images: list[str]) -> Profile:
    """The user's explicit profile if present, else one detected from the worktree's files
    (a new project may only gain its package.json during the run)."""
    path = workspace / PROFILE_PATH
    if path.exists():
        try:
            data = _ProfileFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (yaml.YAMLError, ValidationError) as exc:
            raise ProfileError(f"invalid {PROFILE_PATH}: {exc}") from exc

        bad = [name for name in data.checks if not re.match(_CHECK_NAME, name)]
        if bad:
            raise ProfileError(f"invalid check names: {', '.join(bad)}")
        profile = Profile(image=data.image, checks=data.checks, source=PROFILE_PATH)
    else:
        profile = detect_profile(worktree)
    if profile.image not in allowed_images:
        raise ProfileError(
            f"image '{profile.image}' is not allowed; allowed: {', '.join(allowed_images)}"
        )
    return profile


def detect_profile(root: Path) -> Profile:
    package = root / "package.json"
    if package.exists():
        checks = {"test": "node --test"}
        try:
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        # Only scripts that run without installed dependencies are usable offline; a project
        # that needs `npm ci` must declare its checks in a profile (dependency installs are a
        # separate, approved step).
        if isinstance(scripts.get("test"), str) and scripts["test"].startswith("node "):
            checks["test"] = "npm test --silent"
        return Profile(image="node:22-alpine", checks=checks)
    if any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")):
        return Profile(image="python:3.11-slim", checks={"test": "python -m unittest discover -q"})
    # Empty or unknown project: default to Node (the demo stack) with the built-in test runner.
    return Profile(image="node:22-alpine", checks={"test": "node --test"})
