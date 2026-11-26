"""Exercise actual FastMCP transport without invoking business operations."""

import asyncio

import pytest

pytest.importorskip("fastmcp")
from fastmcp import Client

from scitex_hpc._mcp.server import mcp


def test_real_mcp_registry_exposes_scheduler_neutral_operations():
    # Arrange
    async def catalog():
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    # Act
    names = asyncio.run(catalog())
    # Assert
    assert {
        "compute_plan",
        "compute_submit",
        "compute_status",
        "compute_cancel",
    } <= names


@pytest.mark.parametrize(
    "operation,arguments",
    [
        (
            "compute_submit",
            {
                "profile": "does-not-exist",
                "spec": {"argv": ["hostname"], "working_directory": "/work"},
            },
        ),
        (
            "compute_cancel",
            {
                "profile": "does-not-exist",
                "job": {"host": "example", "scheduler": "slurm", "native_id": "123"},
            },
        ),
    ],
)
def test_mcp_mutation_confirmation_precedes_host_lookup(operation, arguments):
    # Arrange
    async def execute():
        async with Client(mcp) as client:
            return await client.call_tool(operation, arguments)

    # Act
    call = execute
    # Assert
    with pytest.raises(Exception, match="confirm=true"):
        asyncio.run(call())


@pytest.mark.parametrize("invalid", [{"cpus": True}, {"unexpected_resource": 1}])
def test_actual_mcp_validation_rejects_resource_coercion_and_typos(invalid):
    # Arrange
    spec = {"argv": ["hostname"], "working_directory": "/work", **invalid}

    async def execute():
        async with Client(mcp) as client:
            return await client.call_tool(
                "compute_plan", {"profile": "does-not-exist", "spec": spec}
            )

    # Act
    call = execute
    # Assert
    with pytest.raises(Exception, match="(valid integer|Unexpected keyword)"):
        asyncio.run(call())
