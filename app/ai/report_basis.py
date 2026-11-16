"""Stable content/edition tokens, separate from MVCC and opaque cache keys."""

import hashlib
import hmac
import json
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import Settings
from app.schemas.common import ApiResponse

T = TypeVar("T")
VERSION = "ai-report-basis-v1"


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def signing_key(settings: Settings) -> bytes | None:
    if settings.history_context_signing_key is None:
        return None
    master = settings.history_context_signing_key.get_secret_value().encode()
    # HKDF-SHA256 extract + single-block expand; output is 32 bytes.
    prk = hmac.digest(bytes(32), master, "sha256")
    return hmac.digest(prk, VERSION.encode() + b"\x01", "sha256")


def basis(
    kind: str, query: BaseModel, envelope: ApiResponse[T], settings: Settings
) -> ApiResponse[T]:
    key = signing_key(settings)
    if key is None:
        return envelope
    # include= is represented by the resulting data, not an order-sensitive query string.
    scope = query.model_dump(mode="json", exclude={"include", "context"})
    if "sub_category" in scope:
        scope["sub_category"] = sorted(scope["sub_category"] or [])
    raw = envelope.model_dump(mode="json")
    meta = raw.get("meta") or {}
    stable_meta = {
        k: v
        for k, v in meta.items()
        if k
        in {
            "as_of",
            "data_updated_at",
            "data_version",
            "data_version_hash",
            "rule_version",
            "observation_version_id",
            "grid_version_id",
            "input_sha256",
            "content_sha256",
            "grid_input_sha256",
            "grid_content_sha256",
            "sources",
            "collection_reason",
            "format_version",
            "source_catalog_digest",
            "source_refs",
            "history_policy_version",
            "address_index_version",
            "name_exclusion",
        }
    }
    # Batch IDs are a set: SQL row order must not create spurious baseline changes.
    data_version = stable_meta.get("data_version")
    if isinstance(data_version, dict):
        batches = data_version.get("stores_batch_ids")
        if isinstance(batches, list) and all(isinstance(v, str) for v in batches):
            data_version["stores_batch_ids"] = sorted(batches)
    payload = {
        "kind": kind,
        "version": VERSION,
        "scope": scope,
        "data": raw["data"],
        "versions": stable_meta,
    }
    token = hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()
    envelope.meta["ai_report_basis_token"] = token
    return envelope
