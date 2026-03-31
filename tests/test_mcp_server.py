from __future__ import annotations

import inspect

from clawteam.mcp.server import mcp
from clawteam.mcp.tools import TOOL_FUNCTIONS
from clawteam.mcp.tools.team import team_create


def test_server_name_is_project_name():
    assert mcp.name == "clawteam"


def test_server_registers_core_tools():
    tool_names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert tool_names == {tool.__name__ for tool in TOOL_FUNCTIONS}


def test_server_preserves_tool_signature():
    registered = next(tool for tool in mcp._tool_manager.list_tools() if tool.name == "team_create")
    assert inspect.signature(registered.fn) == inspect.signature(team_create)


def test_server_registers_tool_descriptions_from_docstrings():
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    for tool_fn in TOOL_FUNCTIONS:
        description = tools[tool_fn.__name__].description
        assert description == inspect.getdoc(tool_fn)
        assert description
