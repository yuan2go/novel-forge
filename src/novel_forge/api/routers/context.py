from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProductRouterContext:
    app_settings: Any
    models: dict[str, Any]
    services: Any
