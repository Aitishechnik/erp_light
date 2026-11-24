"""Схемы конструктора прав: блоки, действия и настройка уровня."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ActionOut(BaseModel):
    key: str
    title: str


class BlockOut(BaseModel):
    key: str
    title: str
    group: str
    scoped: bool
    actions: list[ActionOut]


class BlockRightsIn(BaseModel):
    actions: list[str] = Field(default_factory=list)
    scope: str = "all"


class BlockRightsView(BaseModel):
    actions: list[str]
    scope: str = "all"


class LevelOut(BaseModel):
    key: str
    title: str
    description: str
    rights: dict[str, BlockRightsView]


class AccessOut(BaseModel):
    levels: list[LevelOut]
    blocks: list[BlockOut]


class LevelUpdate(BaseModel):
    rights: dict[str, BlockRightsIn]
