"""Tests for MCP ToolAnnotations on every registered tool.

Annotations are client UX hints only. They are not permissions: mutating
tools stay blocked unless RAGFS_MCP_ALLOW_WRITES=1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Expected hints per registered tool. Values match what the implementation
# actually does (local index / allowlisted filesystem; no open-world I/O).
# (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
EXPECTED_HINTS: dict[str, tuple[bool, bool, bool, bool]] = {
    "ragfs_search": (True, False, True, False),
    "ragfs_index_status": (True, False, True, False),
    "ragfs_similar": (True, False, True, False),
    "ragfs_list_indices": (True, False, True, False),
    "ragfs_list_trash": (True, False, True, False),
    "ragfs_get_history": (True, False, True, False),
    "ragfs_find_duplicates": (True, False, True, False),
    "ragfs_analyze_cleanup": (True, False, True, False),
    "ragfs_list_pending_plans": (True, False, True, False),
    "ragfs_get_plan": (True, False, True, False),
    "ragfs_propose_organization": (False, False, False, False),
    "ragfs_propose_cleanup": (False, False, False, False),
    "ragfs_restore_from_trash": (False, False, False, False),
    "ragfs_reject_plan": (False, False, False, False),
    "ragfs_delete_to_trash": (False, True, False, False),
    "ragfs_undo": (False, True, False, False),
    "ragfs_approve_plan": (False, True, False, False),
    "ragfs_batch_operations": (False, True, False, False),
}


async def _registered_tools():
    from ragfs_mcp.server import mcp

    return await mcp.list_tools()


def _hint_tuple(tool) -> tuple[bool, bool, bool, bool]:
    ann = tool.annotations
    assert ann is not None, f"{tool.name} has no annotations"
    dumped = ann.model_dump(by_alias=True)
    return (
        dumped["readOnlyHint"],
        dumped["destructiveHint"],
        dumped["idempotentHint"],
        dumped["openWorldHint"],
    )


class TestToolAnnotations:
    @pytest.mark.asyncio
    async def test_every_registered_tool_has_annotations(self):
        tools = await _registered_tools()
        assert tools, "expected registered MCP tools"
        missing = [
            tool.name
            for tool in tools
            if tool.annotations is None
            or any(
                value is None
                for value in (
                    tool.annotations.read_only_hint,
                    tool.annotations.destructive_hint,
                    tool.annotations.idempotent_hint,
                    tool.annotations.open_world_hint,
                )
            )
        ]
        assert missing == [], f"tools missing complete annotations: {missing}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,expected", list(EXPECTED_HINTS.items()), ids=list(EXPECTED_HINTS))
    async def test_hint_values_per_tool(self, name: str, expected: tuple[bool, bool, bool, bool]):
        tools = {tool.name: tool for tool in await _registered_tools()}
        assert set(tools) == set(EXPECTED_HINTS), (
            f"registered tools {sorted(tools)} != expected {sorted(EXPECTED_HINTS)}"
        )
        assert name in tools, f"missing tool {name}"
        assert _hint_tuple(tools[name]) == expected

    @pytest.mark.asyncio
    async def test_non_readonly_hint_is_not_a_write_permission(
        self, source_path: Path, env_vars
    ):
        from ragfs_mcp.server import ragfs_delete_to_trash

        tools = {tool.name: tool for tool in await _registered_tools()}
        delete = tools["ragfs_delete_to_trash"]
        assert delete.annotations is not None
        assert delete.annotations.read_only_hint is False

        target = source_path / "doc1.txt"
        result = json.loads(
            await ragfs_delete_to_trash(path="doc1.txt", index=str(source_path))
        )
        assert "error" in result
        assert "RAGFS_MCP_ALLOW_WRITES" in result["error"]
        assert target.exists()
