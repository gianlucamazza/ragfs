"""MCP search sees the same default exclusions as `ragfs index` (ADR-010 PR 1)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _ragfs_cmd() -> list[str]:
    env_bin = os.environ.get("RAGFS_BIN")
    if env_bin:
        return [env_bin]
    which = shutil.which("ragfs")
    if which:
        return [which]
    for candidate in (
        REPO_ROOT / "target" / "debug" / "ragfs",
        REPO_ROOT / "target" / "release" / "ragfs",
    ):
        if candidate.is_file():
            return [str(candidate)]
    return [
        "cargo",
        "run",
        "--quiet",
        "-p",
        "ragfs",
        "--features",
        "test-backends",
        "--",
    ]


def _index_tree(source: Path, data_dir: Path, config_path: Path, extra: list[str] | None = None) -> None:
    cmd = [
        *_ragfs_cmd(),
        "--config",
        str(config_path),
        "-v",
        "index",
        str(source),
    ]
    if extra:
        cmd.extend(extra)
    env = os.environ.copy()
    env["RAGFS_TEST_EMBEDDER"] = "noop"
    env["RAGFS_DATA_DIR"] = str(data_dir)
    completed = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"ragfs index failed ({completed.returncode})\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


class _StoreRetriever:
    """Search the Lance index MCP would open, without downloading an embedder."""

    def __init__(self, db_path: str, model_path: str | None = None, hybrid: bool = True, k: int = 10):
        self.db_path = db_path
        self.k = k
        self._store = None

    async def init(self) -> None:
        from ragfs import RagfsVectorStore

        self._store = RagfsVectorStore(self.db_path, dimension=384)
        await self._store.init()

    async def search(self, query: str, hybrid: bool = True, k: int = 10):
        del query, hybrid
        assert self._store is not None
        return await self._store.similarity_search([0.0] * 384, k=k)


@pytest.mark.asyncio
async def test_mcp_search_omits_hidden_and_secret_paths(tmp_path, monkeypatch):
    source = tmp_path / "src"
    data_dir = tmp_path / "data"
    source.mkdir()
    data_dir.mkdir()
    (source / "notes").mkdir()
    (source / "notes" / "keyboard.md").write_text("VISIBLE_TOKEN keyboard shortcuts")
    (source / ".hidden.md").write_text("HIDDENFILE_TOKEN")
    (source / ".obsidian").mkdir()
    (source / ".obsidian" / "x.md").write_text("HIDDENDIR_TOKEN")
    (source / "server.pem").write_text("SECRETPEM_TOKEN")
    (source / ".ssh").mkdir()
    (source / ".ssh" / "id_rsa").write_text("SSHKEY_TOKEN")
    config_path = tmp_path / "config.toml"
    config_path.write_text("[query]\nhybrid = false\n")

    _index_tree(source, data_dir, config_path)

    monkeypatch.setenv("RAGFS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RAGFS_SOURCE_PATH", str(source))
    monkeypatch.setenv("RAGFS_TEST_EMBEDDER", "noop")

    import ragfs

    monkeypatch.setattr(ragfs, "RagfsRetriever", _StoreRetriever)

    from ragfs_mcp.server import get_db_path, ragfs_index_status, ragfs_search

    status = json.loads(await ragfs_index_status(index=str(source)))
    assert status.get("exists") is True, status
    assert Path(get_db_path(str(source))).exists()

    payload = json.loads(await ragfs_search(query="VISIBLE_TOKEN", index=str(source), limit=20))
    blob = json.dumps(payload)
    assert "SECRETPEM_TOKEN" not in blob
    assert "HIDDENFILE_TOKEN" not in blob
    assert "HIDDENDIR_TOKEN" not in blob
    assert "SSHKEY_TOKEN" not in blob
    assert "server.pem" not in blob
    assert "id_rsa" not in blob
    assert ".obsidian" not in blob
    files = [item.get("file_path", "") for item in payload.get("results", [])]
    assert all("server.pem" not in f and "id_rsa" not in f for f in files)


@pytest.mark.asyncio
async def test_mcp_search_include_hidden_still_blocks_secrets(tmp_path, monkeypatch):
    source = tmp_path / "src"
    data_dir = tmp_path / "data"
    source.mkdir()
    data_dir.mkdir()
    (source / ".notes.md").write_text("DOTFILE_TOKEN hidden but not secret")
    (source / "server.pem").write_text("SECRETPEM_TOKEN")
    config_path = tmp_path / "config.toml"
    config_path.write_text("[query]\nhybrid = false\n")

    _index_tree(source, data_dir, config_path, extra=["--include-hidden"])

    monkeypatch.setenv("RAGFS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RAGFS_SOURCE_PATH", str(source))
    import ragfs

    monkeypatch.setattr(ragfs, "RagfsRetriever", _StoreRetriever)

    from ragfs_mcp.server import ragfs_search

    payload = json.loads(await ragfs_search(query="DOTFILE_TOKEN", index=str(source), limit=20))
    blob = json.dumps(payload)
    assert "SECRETPEM_TOKEN" not in blob
    assert "server.pem" not in blob
