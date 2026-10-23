from pathlib import Path

import pytest
from fastapi import FastAPI

from app.context import workspace_scan as scan
from app.context.manager import ContextManager, estimate_tokens
from app.context.redact import REDACTED, is_secret_file, redact
from app.db.models import Conversation, Message, Project


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "todo"
    files = {
        "package.json": (
            b'{"dependencies": {"react": "1"}, "devDependencies": {"vite": "1", "typescript": "5"}}'
        ),
        "src/todo.ts": b"export interface Todo { id: number; title: string; done: boolean }\n",
        "src/storage.ts": (
            b"export function saveTodos(todos) "
            b"{ localStorage.setItem('todos', JSON.stringify(todos)) }\n"
        ),
        "src/login/LoginPage.tsx": (
            b"export function LoginPage() { return <form className='login'/> }\n"
        ),
        "HEXMIND.md": b"Use functional React components.\n",
        ".env": b"GROQ_API_KEY=gsk_abcdefghijklmnopqrstuvwx\n",
        "node_modules/react/index.js": b"module.exports = {}\n",
        "logo.png": b"\x89PNG\x00\x00",
    }
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


# ---------- redaction ----------


@pytest.mark.parametrize(
    "path", [".env", ".env.local", "config/.ENV.production", "certs/server.pem", "id_rsa", ".npmrc"]
)
def test_secret_files_are_recognized(path: str) -> None:
    assert is_secret_file(path)


@pytest.mark.parametrize("path", ["env.ts", "src/environment.ts", "keys.ts", "README.md"])
def test_ordinary_files_are_not_secret(path: str) -> None:
    assert not is_secret_file(path)


def test_redact_masks_keys_and_secret_assignments() -> None:
    text = (
        "GROQ_API_KEY=gsk_abcdefghijklmnopqrstuvwx\n"
        'const apiKey = "AIzaSyA1234567890abcdefghijklmnopqrstu"\n'
        "password: hunter2hunter2\n"
        "token = ghp_abcdefghijklmnopqrstuvwxyz123456\n"
        "const title = 'keep me'\n"
    )
    redacted = redact(text)
    for secret in ("gsk_abc", "AIzaSy", "hunter2", "ghp_abc"):
        assert secret not in redacted
    assert redacted.count(REDACTED) == 4
    assert "keep me" in redacted


# ---------- workspace scanning ----------


def test_list_files_skips_ignored_dirs_and_secrets(project_dir: Path) -> None:
    paths = [f.path for f in scan.list_files(project_dir)]
    assert ".env" not in paths
    assert not any(p.startswith("node_modules/") for p in paths)
    assert "src/login/LoginPage.tsx" in paths


def test_detect_stack(project_dir: Path) -> None:
    assert scan.detect_stack(project_dir, scan.list_files(project_dir)) == [
        "node",
        "react",
        "vite",
        "typescript",
    ]


def test_mentioned_files_match_paths_and_unique_basenames(project_dir: Path) -> None:
    files = scan.list_files(project_dir)
    message = "Change LoginPage.tsx and src/todo.ts, but not missing.ts or .env"
    assert scan.mentioned_files(message, files) == ["src/login/LoginPage.tsx", "src/todo.ts"]


def test_search_ranks_by_distinct_terms(project_dir: Path) -> None:
    files = scan.list_files(project_dir)
    terms = scan.keywords("Where do we save todos to localStorage?")
    assert "localstorage" in terms and "where" not in terms
    assert scan.search_files(project_dir, files, terms)[0] == "src/storage.ts"


def test_render_tree_trims_depth_and_lines(project_dir: Path) -> None:
    tree = scan.render_tree(scan.list_files(project_dir), max_depth=2)
    assert "src/" in tree and "  login/" in tree
    assert "LoginPage.tsx" not in tree  # depth 3
    assert "more entries" in scan.render_tree(scan.list_files(project_dir), max_lines=2)


# ---------- ContextManager ----------


async def _setup(app: FastAPI, root: Path, history: list[tuple[str, str]] = []):  # noqa: B006
    async with app.state.sessionmaker.begin() as session:
        project = Project(name="todo", workspace_path=str(root))
        session.add(project)
        await session.flush()
        conversation = Conversation(project_id=project.id, title="t")
        session.add(conversation)
        await session.flush()
        for role, content in history:
            session.add(Message(conversation_id=conversation.id, role=role, content=content))
            await session.flush()
    return project, conversation


async def test_bundle_includes_sources_and_never_secrets(app: FastAPI, project_dir: Path) -> None:
    project, conversation = await _setup(
        app, project_dir, [("user", "My key is sk-abcdefghijklmnopqrstuv"), ("assistant", "noted")]
    )
    async with app.state.sessionmaker() as session:
        bundle = await ContextManager(5000).build(
            session,
            project=project,
            conversation=conversation,
            message="Make LoginPage.tsx dark and check saveTodos",
        )

    rendered = bundle.render()
    assert bundle.stack == ["node", "react", "vite", "typescript"]
    assert bundle.instructions == "Use functional React components.\n"
    assert [(f.path, f.reason) for f in bundle.files][:2] == [
        ("src/login/LoginPage.tsx", "mentioned"),
        ("src/storage.ts", "search"),
    ]
    assert bundle.recent_messages[0][1] == f"My key is {REDACTED}"
    assert "gsk_" not in rendered and "sk-abc" not in rendered
    assert "### File: src/login/LoginPage.tsx" in rendered
    assert bundle.sources()["files"][0] == {
        "path": "src/login/LoginPage.tsx",
        "reason": "mentioned",
        "truncated": False,
    }


async def test_files_are_read_fresh_from_disk(app: FastAPI, project_dir: Path) -> None:
    project, conversation = await _setup(app, project_dir)
    manager = ContextManager(5000)
    (project_dir / "src/todo.ts").write_bytes(b"export type Todo = { changed: true }\n")
    async with app.state.sessionmaker() as session:
        bundle = await manager.build(
            session, project=project, conversation=conversation, message="explain todo.ts"
        )
    assert "changed: true" in bundle.files[0].content


async def test_code_budget_truncates_and_omits(app: FastAPI, project_dir: Path) -> None:
    (project_dir / "src/big.ts").write_bytes(b"// big\n" + b"const filler = 1\n" * 2000)
    project, conversation = await _setup(app, project_dir)
    async with app.state.sessionmaker() as session:
        bundle = await ContextManager(1000).build(
            session,
            project=project,
            conversation=conversation,
            message="look at big.ts and todo.ts and LoginPage.tsx",
        )
    big = bundle.files[0]
    assert big.path == "src/big.ts" and big.truncated
    code_tokens = sum(estimate_tokens(f.content) for f in bundle.files)
    assert code_tokens <= 550 + 10  # 55% of 1000, plus truncation markers
    assert bundle.omitted_files  # later files did not fit


async def test_conversation_window_keeps_newest_within_budget(
    app: FastAPI, project_dir: Path
) -> None:
    history = [("user" if i % 2 == 0 else "assistant", f"message {i}") for i in range(20)]
    project, conversation = await _setup(app, project_dir, history)
    async with app.state.sessionmaker() as session:
        bundle = await ContextManager(5000).build(
            session, project=project, conversation=conversation, message="hi"
        )
    contents = [c for _, c in bundle.recent_messages]
    assert contents[-1] == "message 19"  # chronological, newest last
    assert contents == [f"message {i}" for i in range(20 - len(contents), 20)]
    assert len(contents) == 12  # recent window + unsummarized batch
