"""Type stubs for crewai.tools."""
from __future__ import annotations

from typing import Any, Optional, Type, TypeVar

_T = TypeVar("_T", bound="BaseTool")


class BaseTool:
    """Base class for CrewAI tools."""

    name: str
    description: str

    def __init__(
        self,
        name: str = ...,
        description: str = ...,
        **kwargs: Any,
    ) -> None: ...

    def run(self, *args: Any, **kwargs: Any) -> Any: ...
    async def arun(self, *args: Any, **kwargs: Any) -> Any: ...
    def execute(self, *args: Any, **kwargs: Any) -> Any: ...

    @classmethod
    def from_function(
        cls: Type[_T], func: Any, **kwargs: Any
    ) -> _T: ...


class CrewAIAgent:
    """Stub for CrewAI Agent."""
    def __init__(self, **kwargs: Any) -> None: ...


class Task:
    """Stub for CrewAI Task."""
    def __init__(self, **kwargs: Any) -> None: ...


class Crew:
    """Stub for CrewAI Crew."""
    def __init__(self, **kwargs: Any) -> None: ...
