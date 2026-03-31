"""FastMCP server for ClawTeam."""

from __future__ import annotations

import inspect
from functools import wraps

from mcp.server.fastmcp import FastMCP

from clawteam.mcp.helpers import translate_error
from clawteam.mcp.tools import TOOL_FUNCTIONS

mcp = FastMCP("clawteam")


def _tool(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            raise translate_error(exc) from exc

    wrapped.__signature__ = inspect.signature(fn)
    return mcp.tool()(wrapped)


for tool_fn in TOOL_FUNCTIONS:
    _tool(tool_fn)


def main() -> None:
    mcp.run()
