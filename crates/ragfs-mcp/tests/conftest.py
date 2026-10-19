"""Pytest configuration and fixtures for MCP server tests."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for testing."""
    temp = tempfile.mkdtemp(prefix="ragfs_mcp_test_")
    yield Path(temp)
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def sample_files(temp_dir: Path) -> Path:
    """Create sample files for testing."""
    (temp_dir / "doc1.txt").write_text(
        "Machine learning is a subset of artificial intelligence."
    )
    (temp_dir / "doc2.txt").write_text(
        "Deep learning is based on neural networks."
    )
    return temp_dir


@pytest.fixture
def db_path(temp_dir: Path) -> Path:
    """Get a path for the test database."""
    return temp_dir / "test_db"


@pytest.fixture
def source_path(sample_files: Path) -> Path:
    """Get the source path with sample files."""
    return sample_files


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


@pytest.fixture
def env_vars(source_path: Path, db_path: Path):
    """Set environment variables for MCP server."""
    old_source = os.environ.get("RAGFS_SOURCE_PATH")
    old_db = os.environ.get("RAGFS_DB_PATH")
    old_allowed = os.environ.get("RAGFS_ALLOWED_ROOTS")
    old_writes = os.environ.get("RAGFS_MCP_ALLOW_WRITES")

    os.environ["RAGFS_SOURCE_PATH"] = str(source_path)
    os.environ["RAGFS_DB_PATH"] = str(db_path)

    yield

    _restore_env("RAGFS_SOURCE_PATH", old_source)
    _restore_env("RAGFS_DB_PATH", old_db)
    _restore_env("RAGFS_ALLOWED_ROOTS", old_allowed)
    _restore_env("RAGFS_MCP_ALLOW_WRITES", old_writes)


@pytest.fixture
def allow_writes(monkeypatch: pytest.MonkeyPatch):
    """Opt in to mutating MCP tools."""
    monkeypatch.setenv("RAGFS_MCP_ALLOW_WRITES", "1")


@pytest.fixture(autouse=True)
def reset_mcp_rate_limiter():
    """Isolate the per-process tool-call window between tests."""
    from ragfs_mcp.server import reset_rate_limiter

    reset_rate_limiter()
    yield
    reset_rate_limiter()


def pytest_configure(config):
    """Add custom pytest markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks integration tests")
