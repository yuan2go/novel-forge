from __future__ import annotations

from types import ModuleType
from typing import Any


def bind_product_symbols(namespace: dict[str, Any], services: ModuleType) -> None:
    """Expose existing product service symbols to transitional router modules.

    Phase 1 splits HTTP routing first while preserving internal imports used by
    workers and tests. Later phases can move these symbols into domain service
    modules and remove this bridge.
    """

    for name in dir(services):
        if name.startswith("__"):
            continue
        namespace.setdefault(name, getattr(services, name))
