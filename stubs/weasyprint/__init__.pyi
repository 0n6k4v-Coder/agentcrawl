"""Type stubs for weasyprint."""
from __future__ import annotations

from io import BytesIO
from typing import IO, Any, Union

_HTMLInput = Union[str, "HTML"]
_StylesheetInput = Union[str, "CSS"]


class HTML:
    def __init__(
        self,
        filename: str | None = ...,
        string: str | None = ...,
        base_url: str | None = ...,
        encoding: str | None = ...,
    ) -> None: ...
    def write_pdf(
        self,
        target: str | IO[bytes] | None = ...,
        stylesheets: list[Any] | None = ...,
        presentational_hints: bool = ...,
        **kwargs: Any,
    ) -> bytes: ...


class CSS:
    def __init__(
        self,
        filename: str | None = ...,
        string: str | None = ...,
        base_url: str | None = ...,
        encoding: str | None = ...,
    ) -> None: ...
    def write_pdf(
        self,
        target: str | IO[bytes] | None = ...,
        stylesheets: list[Any] | None = ...,
        **kwargs: Any,
    ) -> bytes: ...


def write_pdf(
    *html_inputs: Any,
    target: str | IO[bytes] | None = ...,
    stylesheets: list[Any] | None = ...,
    **kwargs: Any,
) -> bytes: ...
