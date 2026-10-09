"""Application callers can only use explicitly configured, read-only MCP tools."""

from dataclasses import dataclass
from typing import Protocol


class ToolBackend(Protocol):
    def list_tools(self) -> list[dict]: ...

    def call_tool(self, name: str, arguments: dict) -> dict: ...


@dataclass(frozen=True)
class ReadOnlyApplicationBackend:
    backend: ToolBackend
    allowed_tools: frozenset[str]

    def list_tools(self) -> list[dict]:
        selected = []
        for tool in self.backend.list_tools():
            if tool["name"] not in self.allowed_tools:
                continue
            hints = tool.get("annotations") or {}
            if hints.get("readOnlyHint") is not True or hints.get("destructiveHint") is not False:
                raise PermissionError("A configured application tool is no longer read-only.")
            selected.append(tool)
        return selected

    def call_tool(self, name: str, arguments: dict) -> dict:
        if name not in self.allowed_tools or name not in {tool["name"] for tool in self.list_tools()}:
            raise PermissionError("This tool is not permitted for the application identity.")
        return self.backend.call_tool(name, arguments)
