"""Harakat natijasi va kontekst."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from ..osadapter.base import OSAdapter
    from .apps import AppCatalog
    from .phrases import Phrases


@dataclass(frozen=True)
class ActionResult:
    """Harakat natijasi. `spoken` - foydalanuvchiga aytiladigan matn."""

    spoken: str
    ok: bool = True
    detail: str = ""

    @classmethod
    def failure(cls, spoken: str, detail: str = "") -> "ActionResult":
        return cls(spoken=spoken, ok=False, detail=detail)


@dataclass
class ActionContext:
    """Harakatlarga kerak bo'ladigan hamma narsa."""

    adapter: "OSAdapter"
    config: "Config"
    phrases: "Phrases"
    catalog: "AppCatalog"
    last_reply: str = ""
    history: list[str] = field(default_factory=list)

    def screenshot_dir(self) -> Path:
        from .. import paths

        configured = self.config.actions.screenshot_dir
        if configured:
            return Path(configured)
        return paths.pictures_dir() / "Venera"
