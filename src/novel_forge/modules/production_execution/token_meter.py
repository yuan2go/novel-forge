from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SYSTEM_CONTEXT_LIMIT = 512_000
TOKENIZER_METHODS = frozenset({"MODEL_TOKENIZER_V1", "PINNED_TOKENIZER_JSON_V1"})


@lru_cache(maxsize=32)
def _model_encoding(model: str):
    import tiktoken

    name = tiktoken.model.encoding_name_for_model(model)
    digests = {"o200k_base": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
               "cl100k_base": "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"}
    if name not in digests:
        raise ValueError("TOKENIZER_MODEL_UNSUPPORTED")
    cache = Path(os.environ.get("TIKTOKEN_CACHE_DIR") or os.environ.get("DATA_GYM_CACHE_DIR") or Path(tempfile.gettempdir()) / "data-gym-cache")
    key = hashlib.sha1(f"https://openaipublic.blob.core.windows.net/encodings/{name}.tiktoken".encode()).hexdigest()
    source = cache / key
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digests[name]:
        raise ValueError("TOKENIZER_ASSET_UNAVAILABLE: preinstall the official hash-checked tokenizer cache")
    return tiktoken.encoding_for_model(model)


def count_text(text: str, *, method: str, model: str, evidence_ref: str = "") -> int:
    try:
        return _count_text(text, method=method, model=model, evidence_ref=evidence_ref)
    except (ValueError, KeyError, OSError, ImportError) as error:
        from novel_forge.modules.command_kernel.errors import KernelError
        raise KernelError("PROVIDER_TOKENIZER_UNAVAILABLE", "Install and bind the matching immutable tokenizer before capacity admission",
                          details={"method": method, "model": model, "cause": str(error)}) from error


def _count_text(text: str, *, method: str, model: str, evidence_ref: str = "") -> int:
    if method == "MODEL_TOKENIZER_V1":
        return len(_model_encoding(model).encode(text, disallowed_special=()))
    if method == "PINNED_TOKENIZER_JSON_V1":
        prefix, digest, location = evidence_ref.split(":", 2)
        source = Path(location)
        if prefix != "tokenizer-json" or len(digest) != 64 or not source.is_absolute():
            raise ValueError("TOKENIZER_IDENTITY_INVALID")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("TOKENIZER_IDENTITY_DRIFT")
        return len(_json_tokenizer(digest, data.decode()).encode(text, add_special_tokens=False).ids)
    return len(text.encode("utf-8"))


@lru_cache(maxsize=4)
def _json_tokenizer(digest: str, data: str):
    from tokenizers import Tokenizer

    return Tokenizer.from_str(data)


def measure_input(text: str, *, method: str, model: str, evidence_ref: str = "") -> dict[str, Any]:
    count = count_text(text, method=method, model=model, evidence_ref=evidence_ref)
    return {
        "method": method,
        "model": model,
        "utf8_bytes": len(text.encode("utf-8")),
        "tokenized_text_tokens": count if method in TOKENIZER_METHODS else None,
        "input_token_upper_bound": count if "UPPER_BOUND" in method else None,
        "actual_provider_input_tokens": None,
        "input_tokens": count,
        "precision": "TOKENIZED_TEXT_WITH_PROTOCOL_ESTIMATE" if method in TOKENIZER_METHODS else
            "FIXTURE_BYTES_EXACT" if method == "SCRIPTED_UTF8_BYTES_EXACT_V1" else "BYTE_UPPER_BOUND",
    }


def serialized_tokens(value: Any, *, method: str, model: str, evidence_ref: str = "") -> int:
    return count_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                      method=method, model=model, evidence_ref=evidence_ref)


def route_input_tokens(route: Any, text: str, *, output_schema_json: str = "") -> int:
    from .provider_admission import provider_request_token_components

    components = provider_request_token_components(text, output_reserve=1,
        safety_margin=route.token_safety_margin, framing_overhead=route.token_framing_overhead,
        output_schema_json=output_schema_json, accounting_method=route.token_accounting_method,
        model=route.model_profile.model_id, accounting_evidence_ref=route.token_accounting_evidence_ref)
    return sum(components.values()) - 1


def route_request_size(route: Any, text: str, *, output_reserve: int, output_schema_json: str = "") -> tuple[int, int]:
    amount = route_input_tokens(route, text, output_schema_json=output_schema_json)
    model_limit = route.model_context_limit
    if model_limit <= 0 and route.model_profile.model_provider == "scripted_provider_v2":
        model_limit = SYSTEM_CONTEXT_LIMIT
    if model_limit <= 0:
        from novel_forge.modules.command_kernel.errors import KernelError
        raise KernelError("MODEL_CONTEXT_CAPACITY_UNKNOWN", "Complete request capacity requires a confirmed selected route window")
    limit = min(SYSTEM_CONTEXT_LIMIT, model_limit)
    reserve = 1 if getattr(route, "output_reservation_policy", "") else output_reserve
    return amount + reserve, limit


def capacity_route_contract(route: Any) -> dict:
    from .provider_admission import provider_request_protocol
    profile = route.model_profile
    return {"protocol": provider_request_protocol(profile.model_provider), "provider": profile.model_provider, "model": profile.model_id,
            "reasoning": profile.reasoning_effort, "backend": profile.backend_id,
            "context_limit": route.model_context_limit, "output_limit": route.model_output_limit,
            "method": route.token_accounting_method, "evidence": route.token_accounting_evidence_ref,
            "framing": route.token_framing_overhead, "safety": route.token_safety_margin,
            "output_policy": route.output_reservation_policy}


def capacity_route_binding(route: Any, decision: dict | None = None) -> dict:
    candidate = ((decision or {}).get("selected") or {}).get("candidate")
    return {"route": capacity_route_contract(route), **({"candidate": {key: candidate[key] for key in
        ("candidate_id", "provider", "model", "model_revision", "reasoning", "context_limit", "output_limit")}} if candidate else {})}
