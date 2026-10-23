from pathlib import Path

import httpx


async def _open(client: httpx.AsyncClient, workspace: Path) -> dict:
    response = await client.post("/api/projects", json={"workspace_path": str(workspace)})
    assert response.status_code == 200, response.text
    return response.json()


async def test_open_project_is_idempotent(client: httpx.AsyncClient, workspace: Path) -> None:
    first = await _open(client, workspace)
    second = await _open(client, workspace)
    assert first["id"] == second["id"]
    assert first["name"] == "workspace"
    assert first["git_enabled"] is True
    assert first["workspace_path"] == str(workspace.resolve())

    listed = (await client.get("/api/projects")).json()
    assert [p["id"] for p in listed] == [first["id"]]


async def test_open_project_validates_path(client: httpx.AsyncClient, workspace: Path) -> None:
    cases = [
        "relative/path",
        str(workspace / "missing"),
        str(workspace / "README.md"),
        workspace.anchor,  # drive / filesystem root
    ]
    for raw in cases:
        response = await client.post("/api/projects", json={"workspace_path": raw})
        assert response.status_code == 400, raw


async def test_tree_read_and_write_roundtrip(client: httpx.AsyncClient, workspace: Path) -> None:
    project = await _open(client, workspace)
    base = f"/api/projects/{project['id']}"

    tree = (await client.get(f"{base}/tree")).json()
    assert [e["path"] for e in tree] == ["src", "README.md"]
    assert (await client.get(f"{base}/tree", params={"path": "src"})).json()[0]["path"] == (
        "src/app.ts"
    )

    file = (await client.get(f"{base}/file", params={"path": "src/app.ts"})).json()
    assert file["content"] == "export const x = 1\n"

    saved = await client.put(
        f"{base}/file",
        json={"path": "src/app.ts", "content": "export const x = 2\n", "base_hash": file["hash"]},
    )
    assert saved.status_code == 200
    assert (workspace / "src/app.ts").read_text() == "export const x = 2\n"

    stale = await client.put(
        f"{base}/file",
        json={"path": "src/app.ts", "content": "stale", "base_hash": file["hash"]},
    )
    assert stale.status_code == 409
    assert stale.json()["current_hash"] == saved.json()["hash"]


async def test_file_api_rejects_traversal(client: httpx.AsyncClient, workspace: Path) -> None:
    (workspace.parent / "outside.txt").write_text("secret")
    project = await _open(client, workspace)
    base = f"/api/projects/{project['id']}"

    for path in ("../outside.txt", "..\\outside.txt", str(workspace.parent / "outside.txt")):
        assert (await client.get(f"{base}/file", params={"path": path})).status_code == 400
        assert (await client.get(f"{base}/tree", params={"path": path})).status_code == 400
        put = await client.put(
            f"{base}/file", json={"path": path, "content": "x", "base_hash": None}
        )
        assert put.status_code == 400
    assert (workspace.parent / "outside.txt").read_text() == "secret"

    git_write = await client.put(
        f"{base}/file", json={"path": ".git/HEAD", "content": "x", "base_hash": None}
    )
    assert git_write.status_code == 400


async def test_missing_resources_return_404(client: httpx.AsyncClient, workspace: Path) -> None:
    project = await _open(client, workspace)
    base = f"/api/projects/{project['id']}"
    assert (await client.get(f"{base}/file", params={"path": "nope.txt"})).status_code == 404
    assert (await client.get(f"{base}/file", params={"path": "src"})).status_code == 404
    assert (await client.get(f"{base}/tree", params={"path": "nope"})).status_code == 404
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/projects/{missing}/tree")).status_code == 404
