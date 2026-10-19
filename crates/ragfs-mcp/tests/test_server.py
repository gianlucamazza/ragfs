"""Tests for RAGFS MCP server."""

from __future__ import annotations

import json
import os
from pathlib import Path

import blake3
import pytest


class TestMCPServerImports:
    """Test that MCP server can be imported."""

    def test_import_server(self):
        """Test importing the server module."""
        from ragfs_mcp import create_server, mcp

        assert create_server is not None
        assert mcp is not None

    def test_import_main(self):
        """Test importing the main function."""
        from ragfs_mcp import main

        assert main is not None


class TestSearchTools:
    """Tests for search and discovery tools."""

    @pytest.mark.asyncio
    async def test_ragfs_list_indices(self):
        """Test listing available indices."""
        from ragfs_mcp.server import ragfs_list_indices

        result = await ragfs_list_indices()
        data = json.loads(result)

        assert "indices" in data or "hint" in data

    @pytest.mark.asyncio
    async def test_ragfs_index_status_missing(self):
        """Test getting status of non-existent index."""
        from ragfs_mcp.server import ragfs_index_status

        result = await ragfs_index_status(index="nonexistent_test_index")
        data = json.loads(result)

        assert data["exists"] is False


class TestPathJail:
    """MCP destructive tools must stay inside the source root."""

    @pytest.mark.asyncio
    async def test_delete_to_trash_rejects_absolute_outside_root(
        self, source_path: Path, env_vars, allow_writes, tmp_path: Path
    ):
        pytest.importorskip("ragfs")
        from ragfs_mcp.server import ragfs_delete_to_trash

        secret = tmp_path / "secret.txt"
        secret.write_text("secret")

        result = json.loads(
            await ragfs_delete_to_trash(path=str(secret), index=str(source_path))
        )
        assert "error" in result
        assert "escapes" in result["error"]
        assert secret.exists()

    @pytest.mark.asyncio
    async def test_batch_rejects_parent_escape(
        self, source_path: Path, env_vars, allow_writes
    ):
        pytest.importorskip("ragfs")
        from ragfs_mcp.server import ragfs_batch_operations

        result = json.loads(
            await ragfs_batch_operations(
                operations=[
                    {
                        "action": "create",
                        "target": "../jailbreak.txt",
                        "content": "nope",
                    }
                ],
                atomic=True,
                dry_run=False,
                index=str(source_path),
            )
        )
        assert not (source_path.parent / "jailbreak.txt").exists()
        blob = json.dumps(result)
        assert "escapes" in blob
        assert result.get("success") is False


class TestSafetyTools:
    """Tests for safety layer tools."""

    @pytest.mark.asyncio
    async def test_ragfs_list_trash_import_error(self):
        """Test list_trash handles missing ragfs gracefully."""
        # This test verifies the tool handles import errors
        # In a real test environment with ragfs installed, this would work
        from ragfs_mcp.server import ragfs_list_trash

        result = await ragfs_list_trash()
        data = json.loads(result)

        # Either returns trash list or error about missing package
        assert "entries" in data or "error" in data

    @pytest.mark.asyncio
    async def test_ragfs_get_history(self):
        """Test getting operation history."""
        from ragfs_mcp.server import ragfs_get_history

        result = await ragfs_get_history(limit=10)
        data = json.loads(result)

        assert "entries" in data or "error" in data


class TestSemanticTools:
    """Tests for semantic operation tools."""

    @pytest.mark.asyncio
    async def test_ragfs_find_duplicates(self):
        """Test finding duplicates."""
        from ragfs_mcp.server import ragfs_find_duplicates

        result = await ragfs_find_duplicates(threshold=0.9)
        data = json.loads(result)

        assert "groups" in data or "error" in data

    @pytest.mark.asyncio
    async def test_ragfs_analyze_cleanup(self):
        """Test cleanup analysis."""
        from ragfs_mcp.server import ragfs_analyze_cleanup

        result = await ragfs_analyze_cleanup()
        data = json.loads(result)

        assert "categories" in data or "error" in data


class TestApprovalWorkflow:
    """Tests for approval workflow tools."""

    @pytest.mark.asyncio
    async def test_ragfs_list_pending_plans(self):
        """Test listing pending plans."""
        from ragfs_mcp.server import ragfs_list_pending_plans

        result = await ragfs_list_pending_plans()
        data = json.loads(result)

        assert "pending_plans" in data or "error" in data

    @pytest.mark.asyncio
    async def test_ragfs_get_plan_not_found(self):
        """Test getting a non-existent plan."""
        from ragfs_mcp.server import ragfs_get_plan

        result = await ragfs_get_plan(plan_id="nonexistent_plan_id")
        data = json.loads(result)

        # Should return error about plan not found
        assert "error" in data

    @pytest.mark.asyncio
    async def test_ragfs_propose_organization(self):
        """Test proposing organization."""
        from ragfs_mcp.server import ragfs_propose_organization

        result = await ragfs_propose_organization(
            scope="./",
            strategy="by_topic",
            max_groups=3,
        )
        data = json.loads(result)

        # Either returns plan or error
        assert "plan_id" in data or "error" in data


class TestBatchOperations:
    """Tests for batch operations tool."""

    @pytest.mark.asyncio
    async def test_ragfs_batch_operations_empty(self):
        """Test batch with empty operations list."""
        from ragfs_mcp.server import ragfs_batch_operations

        result = await ragfs_batch_operations(operations=[], atomic=True)
        data = json.loads(result)

        # Should handle empty list gracefully
        assert "results" in data or "error" in data

    @pytest.mark.asyncio
    async def test_ragfs_batch_operations_invalid_action(
        self, source_path: Path, env_vars, allow_writes
    ):
        """Test batch with invalid action type."""
        from ragfs_mcp.server import ragfs_batch_operations

        operations = [
            {"action": "invalid_action", "target": "/test/path"}
        ]
        result = await ragfs_batch_operations(
            operations=operations, index=str(source_path)
        )
        data = json.loads(result)

        assert "error" in data
        assert "Unknown action" in data["error"]

    @pytest.mark.asyncio
    async def test_ragfs_batch_operations_dry_run(self):
        """Test batch dry run mode."""
        from ragfs_mcp.server import ragfs_batch_operations

        operations = [
            {"action": "mkdir", "target": "/test/new_dir"}
        ]
        result = await ragfs_batch_operations(
            operations=operations,
            dry_run=True,
        )
        data = json.loads(result)

        # Dry run should return validation result
        assert data.get("dry_run") is True or "error" in data


class TestServerConfiguration:
    """Tests for server configuration."""

    def test_get_db_path_matches_cli_blake3_scheme(self, tmp_path, monkeypatch):
        """MCP must hash the canonical source path the same way as the CLI."""
        from ragfs_mcp.server import get_db_path, index_id_for_source

        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.delenv("RAGFS_DATA_DIR", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)

        source = tmp_path / "project"
        source.mkdir()
        canonical = str(source.resolve())
        expected_id = blake3.blake3(canonical.encode()).hexdigest()[:16]

        # Official BLAKE3 empty-input prefix (same as the Rust blake3 crate).
        assert blake3.blake3(b"").hexdigest().startswith("af1349b9f5f9a1a6")

        assert index_id_for_source(str(source)) == expected_id
        assert index_id_for_source(canonical) == expected_id

        path = get_db_path(str(source))
        assert path.endswith(f"indices/{expected_id}/index.lance")
        assert "default" not in Path(path).parts

    def test_get_db_path_relative_and_absolute_match(self, tmp_path, monkeypatch):
        """Relative and absolute forms of the same directory share one index id."""
        from ragfs_mcp.server import get_db_path

        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        source = tmp_path / "docs"
        source.mkdir()

        assert get_db_path("docs") == get_db_path(str(source.resolve()))

    def test_get_db_path_default_uses_source_path(self, tmp_path, monkeypatch):
        """Default index follows RAGFS_SOURCE_PATH, not a literal 'default' folder."""
        from ragfs_mcp.server import get_db_path

        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.delenv("RAGFS_DATA_DIR", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))

        expected_id = blake3.blake3(str(tmp_path.resolve()).encode()).hexdigest()[:16]
        path = get_db_path()
        assert path.endswith(f"indices/{expected_id}/index.lance")

    def test_get_db_path_hex_id_passthrough(self, monkeypatch):
        """A 16-hex id from ragfs_list_indices is used as-is."""
        from ragfs_mcp.server import get_db_path

        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.delenv("RAGFS_DATA_DIR", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)

        hex_id = "0123456789abcdef"
        path = get_db_path(hex_id)
        assert path.endswith(f"indices/{hex_id}/index.lance")

    def test_get_db_path_env_override(self, monkeypatch, tmp_path):
        """RAGFS_DB_PATH still wins when an explicit store path is set."""
        from ragfs_mcp.server import get_db_path

        override = str(tmp_path / "custom.lance")
        monkeypatch.setenv("RAGFS_DB_PATH", override)
        assert get_db_path("/some/source") == override
        assert get_db_path() == override

    def test_get_db_path_respects_data_dir(self, tmp_path, monkeypatch):
        """RAGFS_DATA_DIR is the same override the CLI data_dir() uses."""
        from ragfs_mcp.server import get_db_path

        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.setenv("RAGFS_DATA_DIR", str(tmp_path))
        source = tmp_path / "src"
        source.mkdir()
        expected_id = blake3.blake3(str(source.resolve()).encode()).hexdigest()[:16]
        assert get_db_path(str(source)) == str(
            tmp_path / "indices" / expected_id / "index.lance"
        )

    def test_get_data_dir_keeps_literal_tilde(self, monkeypatch):
        """CLI keeps RAGFS_DATA_DIR as-is; MCP must not expanduser()."""
        from ragfs_mcp.server import get_data_dir, get_db_path

        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.setenv("RAGFS_DATA_DIR", "~/ragfs-data")

        assert get_data_dir() == Path("~/ragfs-data")
        path = get_db_path("0123456789abcdef")
        assert path == str(Path("~/ragfs-data") / "indices" / "0123456789abcdef" / "index.lance")
        assert not path.startswith(str(Path.home() / "ragfs-data"))

    def test_get_data_dir_matches_cli_project_dirs(self, tmp_path, monkeypatch):
        """Fallback matches ProjectDirs::from("", "", "ragfs").data_dir()."""
        from ragfs_mcp.server import get_data_dir

        monkeypatch.delenv("RAGFS_DATA_DIR", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)

        monkeypatch.setattr("ragfs_mcp.server.sys.platform", "linux")
        assert get_data_dir() == Path.home() / ".local" / "share" / "ragfs"

        monkeypatch.setattr("ragfs_mcp.server.sys.platform", "darwin")
        assert get_data_dir() == Path.home() / "Library" / "Application Support" / "ragfs"

        monkeypatch.setattr("ragfs_mcp.server.sys.platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert get_data_dir() == tmp_path / "ragfs" / "data"

    def test_get_data_dir_xdg_matches_directories(self, tmp_path, monkeypatch):
        """XDG_DATA_HOME only on Linux-like OS and only when absolute."""
        from ragfs_mcp.server import get_data_dir

        monkeypatch.delenv("RAGFS_DATA_DIR", raising=False)
        xdg = tmp_path / "xdg-data"

        monkeypatch.setattr("ragfs_mcp.server.sys.platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
        assert get_data_dir() == xdg / "ragfs"

        monkeypatch.setenv("XDG_DATA_HOME", "rel-data")
        assert get_data_dir() == Path.home() / ".local" / "share" / "ragfs"

        monkeypatch.setenv("XDG_DATA_HOME", "~/xdg-data")
        assert get_data_dir() == Path.home() / ".local" / "share" / "ragfs"

        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
        monkeypatch.setattr("ragfs_mcp.server.sys.platform", "darwin")
        assert get_data_dir() == Path.home() / "Library" / "Application Support" / "ragfs"

        monkeypatch.setattr("ragfs_mcp.server.sys.platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        assert get_data_dir() == tmp_path / "Roaming" / "ragfs" / "data"

    def test_get_model_path(self):
        """Test model path."""
        from ragfs_mcp.server import get_model_path

        path = get_model_path()
        assert "models" in path

    def test_get_source_path_default_uses_allowlisted_source(
        self, tmp_path, monkeypatch
    ):
        """Default index uses realpath(RAGFS_SOURCE_PATH) when it is allowlisted."""
        from ragfs_mcp.server import get_source_path

        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        monkeypatch.delenv("RAGFS_ALLOWED_ROOTS", raising=False)
        assert get_source_path() == os.path.realpath(str(tmp_path))
        assert get_source_path("default") == os.path.realpath(str(tmp_path))

    def test_get_source_path_uses_index_directory(self, tmp_path, monkeypatch):
        """Passing an allowlisted source directory as index resolves that directory."""
        from ragfs_mcp.server import get_source_path

        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        monkeypatch.delenv("RAGFS_ALLOWED_ROOTS", raising=False)
        assert get_source_path(str(tmp_path)) == os.path.realpath(str(tmp_path))


class TestAllowlistedRoots:
    """Mutating tools only operate on allowlisted roots or a known index source."""

    def test_rejects_arbitrary_existing_directory(self, tmp_path, monkeypatch):
        """An existing directory outside the allowlist is not a jail root."""
        from ragfs_mcp.server import get_source_path

        allowed = tmp_path / "allowed"
        other = tmp_path / "other"
        allowed.mkdir()
        other.mkdir()
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(allowed))
        monkeypatch.delenv("RAGFS_ALLOWED_ROOTS", raising=False)

        with pytest.raises(ValueError, match="not an allowed root"):
            get_source_path(str(other))

    def test_rejects_home_directory_as_index(self, tmp_path, monkeypatch):
        """Home is an existing directory and must not become the jail root."""
        from ragfs_mcp.server import get_source_path

        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(allowed))
        monkeypatch.delenv("RAGFS_ALLOWED_ROOTS", raising=False)

        with pytest.raises(ValueError, match="not an allowed root"):
            get_source_path(str(Path.home()))

    def test_extra_allowed_roots_are_accepted(self, tmp_path, monkeypatch):
        from ragfs_mcp.server import get_source_path

        allowed = tmp_path / "allowed"
        extra = tmp_path / "extra"
        other = tmp_path / "other"
        allowed.mkdir()
        extra.mkdir()
        other.mkdir()
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(allowed))
        monkeypatch.setenv("RAGFS_ALLOWED_ROOTS", str(extra))

        assert get_source_path(str(extra)) == os.path.realpath(str(extra))
        with pytest.raises(ValueError, match="not an allowed root"):
            get_source_path(str(other))

    def test_hex_id_of_allowlisted_root_maps_to_that_root(self, tmp_path, monkeypatch):
        """A hex id that is the CLI hash of an allowlisted root uses that root."""
        from ragfs_mcp.server import get_source_path, index_id_for_source

        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        monkeypatch.delenv("RAGFS_ALLOWED_ROOTS", raising=False)
        hex_id = index_id_for_source(str(tmp_path))
        assert get_source_path(hex_id) == os.path.realpath(str(tmp_path))

    def test_hex_id_without_recorded_source_is_rejected(self, tmp_path, monkeypatch):
        """Hex ids must not fall back to RAGFS_SOURCE_PATH or cwd."""
        from ragfs_mcp.server import get_source_path

        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        monkeypatch.setenv("RAGFS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match="not an allowed root"):
            get_source_path("0123456789abcdef")

    def test_hex_id_maps_to_recorded_source(self, tmp_path, monkeypatch):
        """Writes for a hex id use that index's recorded source, not SOURCE_PATH."""
        from ragfs_mcp.server import (
            INDEX_SOURCE_FILENAME,
            get_indices_dir,
            get_source_path,
            index_id_for_source,
        )

        fallback = tmp_path / "fallback"
        recorded = tmp_path / "recorded"
        fallback.mkdir()
        recorded.mkdir()
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(fallback))
        monkeypatch.setenv("RAGFS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.chdir(fallback)

        hex_id = index_id_for_source(str(recorded))
        index_dir = get_indices_dir() / hex_id
        index_dir.mkdir(parents=True)
        (index_dir / INDEX_SOURCE_FILENAME).write_text(
            os.path.realpath(str(recorded)) + "\n"
        )

        assert get_source_path(hex_id) == os.path.realpath(str(recorded))
        assert get_source_path(hex_id) != os.path.realpath(str(fallback))
        assert get_source_path(hex_id) != os.getcwd()


class TestWriteToolGate:
    """Mutating MCP tools require RAGFS_MCP_ALLOW_WRITES=1."""

    @pytest.mark.asyncio
    async def test_delete_refuses_without_writes_flag(
        self, source_path: Path, env_vars
    ):
        from ragfs_mcp.server import ragfs_delete_to_trash

        target = source_path / "doc1.txt"
        result = json.loads(
            await ragfs_delete_to_trash(path="doc1.txt", index=str(source_path))
        )
        assert "error" in result
        assert "RAGFS_MCP_ALLOW_WRITES" in result["error"]
        assert target.exists()

    @pytest.mark.asyncio
    async def test_batch_create_refuses_without_writes_flag(
        self, source_path: Path, env_vars
    ):
        from ragfs_mcp.server import ragfs_batch_operations

        result = json.loads(
            await ragfs_batch_operations(
                operations=[
                    {"action": "create", "target": "new.txt", "content": "nope"}
                ],
                dry_run=False,
                index=str(source_path),
            )
        )
        assert "error" in result
        assert "RAGFS_MCP_ALLOW_WRITES" in result["error"]
        assert not (source_path / "new.txt").exists()

    @pytest.mark.asyncio
    async def test_restore_undo_approve_refuse_without_writes_flag(
        self, source_path: Path, env_vars
    ):
        from ragfs_mcp.server import (
            ragfs_approve_plan,
            ragfs_restore_from_trash,
            ragfs_undo,
        )

        restore = json.loads(
            await ragfs_restore_from_trash(undo_id="x", index=str(source_path))
        )
        undo = json.loads(await ragfs_undo(undo_id="x", index=str(source_path)))
        approve = json.loads(
            await ragfs_approve_plan(plan_id="x", index=str(source_path))
        )
        for data in (restore, undo, approve):
            assert "error" in data
            assert "RAGFS_MCP_ALLOW_WRITES" in data["error"]

    @pytest.mark.asyncio
    async def test_batch_dry_run_works_without_writes_flag(
        self, source_path: Path, env_vars
    ):
        pytest.importorskip("ragfs")
        from ragfs_mcp.server import ragfs_batch_operations

        result = json.loads(
            await ragfs_batch_operations(
                operations=[{"action": "mkdir", "target": "new_dir"}],
                dry_run=True,
                index=str(source_path),
            )
        )
        blob = json.dumps(result)
        assert "RAGFS_MCP_ALLOW_WRITES" not in blob
        assert result.get("dry_run") is True or "error" in result
        assert not (source_path / "new_dir").exists()

    @pytest.mark.asyncio
    async def test_delete_rejects_arbitrary_existing_dir_as_index(
        self, source_path: Path, env_vars, allow_writes, tmp_path: Path
    ):
        from ragfs_mcp.server import ragfs_delete_to_trash

        outsider = tmp_path / "outside_root"
        outsider.mkdir()
        secret = outsider / "secret.txt"
        secret.write_text("secret")

        result = json.loads(
            await ragfs_delete_to_trash(path="secret.txt", index=str(outsider))
        )
        assert "error" in result
        assert "not an allowed root" in result["error"]
        assert secret.exists()

    @pytest.mark.asyncio
    async def test_batch_create_rejects_arbitrary_existing_dir_as_index(
        self, source_path: Path, env_vars, allow_writes, tmp_path: Path
    ):
        from ragfs_mcp.server import ragfs_batch_operations

        outsider = tmp_path / "outside_root"
        outsider.mkdir()

        result = json.loads(
            await ragfs_batch_operations(
                operations=[
                    {"action": "create", "target": "planted.txt", "content": "nope"}
                ],
                dry_run=False,
                index=str(outsider),
            )
        )
        assert "error" in result
        assert "not an allowed root" in result["error"]
        assert not (outsider / "planted.txt").exists()

    @pytest.mark.asyncio
    async def test_allowed_path_delete_works_with_writes_flag(
        self, source_path: Path, env_vars, allow_writes
    ):
        pytest.importorskip("ragfs")
        from ragfs_mcp.server import ragfs_delete_to_trash

        target = source_path / "doc1.txt"
        assert target.exists()
        result = json.loads(
            await ragfs_delete_to_trash(path="doc1.txt", index=str(source_path))
        )
        assert result.get("success") is True
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_hex_id_writes_stay_inside_recorded_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        pytest.importorskip("ragfs")
        from ragfs_mcp.server import (
            INDEX_SOURCE_FILENAME,
            get_indices_dir,
            index_id_for_source,
            ragfs_delete_to_trash,
        )

        fallback = tmp_path / "fallback"
        recorded = tmp_path / "recorded"
        fallback.mkdir()
        recorded.mkdir()
        fallback_file = fallback / "fallback.txt"
        recorded_file = recorded / "keep.txt"
        fallback_file.write_text("fallback")
        recorded_file.write_text("recorded")

        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(fallback))
        monkeypatch.setenv("RAGFS_MCP_ALLOW_WRITES", "1")
        monkeypatch.setenv("RAGFS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.chdir(fallback)

        hex_id = index_id_for_source(str(recorded))
        index_dir = get_indices_dir() / hex_id
        index_dir.mkdir(parents=True)
        (index_dir / INDEX_SOURCE_FILENAME).write_text(
            os.path.realpath(str(recorded)) + "\n"
        )

        ok = json.loads(
            await ragfs_delete_to_trash(path="keep.txt", index=hex_id)
        )
        assert ok.get("success") is True
        assert not recorded_file.exists()
        assert fallback_file.exists()

        denied = json.loads(
            await ragfs_delete_to_trash(path=str(fallback_file), index=hex_id)
        )
        assert "error" in denied
        assert fallback_file.exists()
