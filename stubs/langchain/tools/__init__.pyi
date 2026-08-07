"""Type stubs for langchain.tools."""
from __future__ import annotations

from typing import Any, Callable, Optional, Type, TypeVar
from pydantic import BaseModel

_T = TypeVar("_T", bound="BaseTool")


class BaseTool:
    """Base class for LangChain tools."""

    name: str
    description: str
    args_schema: Optional[Type[BaseModel]]
    return_direct: bool
    verbose: bool

    def __init__(
        self,
        name: str = ...,
        description: str = ...,
        args_schema: Optional[Type[BaseModel]] = ...,
        return_direct: bool = False,
        verbose: bool = False,
        **kwargs: Any,
    ) -> None: ...

    def run(self, *args: Any, **kwargs: Any) -> Any: ...
    def invoke(self, *args: Any, **kwargs: Any) -> Any: ...
    async def arun(self, *args: Any, **kwargs: Any) -> Any: ...
    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any: ...

    @classmethod
    def from_function(
        cls: Type[_T], func: Callable[..., Any], **kwargs: Any
    ) -> _T: ...


class StructuredTool(BaseTool):
    """A tool that accepts structured input."""

    func: Callable[..., Any]
