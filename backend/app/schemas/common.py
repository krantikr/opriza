"""Shared API response shapes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    """A slice of a listing, with enough context to paginate."""

    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class Message(BaseModel):
    detail: str


class ActionResult(BaseModel):
    """Outcome of a state-changing action on a quotation."""

    ok: bool = True
    detail: str
    quotation_id: int | None = None
    status: str | None = None
    warnings: list[str] = Field(default_factory=list)
