from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str, fallback: str = "asset") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def make_id(prefix: str, title: str = "") -> str:
    return f"{slugify(prefix)}-{slugify(title, prefix)}-{uuid.uuid4().hex[:8]}"
