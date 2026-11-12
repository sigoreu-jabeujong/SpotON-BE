import base64
import binascii
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from etl.brands.catalog import (
    ENDPOINT,
    MAX_PAGE_BYTES,
    MAX_SNAPSHOT_BYTES,
    PAGE_SIZE,
    RULE_VERSION,
    Catalog,
    build_catalog,
    canonical,
    digest,
    fail,
    parse_json,
)

WORKSPACE = Path(__file__).resolve().parents[3]


def external_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(WORKSPACE):
        fail("repository_path")
    return resolved


def _encode(raw: bytes) -> dict[str, str]:
    return dict(sha256=digest(raw), body=base64.b64encode(raw).decode("ascii"))


def _decode(value: Any) -> bytes:
    if (
        type(value) is not dict
        or set(value) != {"sha256", "body"}
        or type(value["body"]) is not str
        or type(value["sha256"]) is not str
        or len(value["body"]) > 4 * ((MAX_PAGE_BYTES + 2) // 3)
    ):
        fail("snapshot_page")
    try:
        raw = base64.b64decode(value["body"], validate=True)
    except (ValueError, binascii.Error):
        fail("snapshot_page")
    if digest(raw) != value["sha256"]:
        fail("snapshot_hash")
    return raw


def save_snapshot(path: Path, catalog: Catalog) -> None:
    path = external_path(path)
    payload = canonical(
        dict(
            schema="ftc-brand-snapshot-v1",
            endpoint=ENDPOINT,
            rule_version=RULE_VERSION,
            year=catalog.year,
            page_size=PAGE_SIZE,
            total_count=len(catalog.rows),
            collected_at=catalog.collected_at.isoformat(),
            content_sha256=catalog.content_sha256,
            pages=[_encode(raw) for raw in catalog.pages],
            verification_page=_encode(catalog.verification_page),
        )
    )
    if len(payload) > MAX_SNAPSHOT_BYTES:
        fail("snapshot_size")
    created = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def load_snapshot(path: Path) -> Catalog:
    return read_snapshot(path)[0]


def read_snapshot(path: Path) -> tuple[Catalog, str]:
    path = external_path(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
    if len(raw) > MAX_SNAPSHOT_BYTES:
        fail("snapshot_size")
    value = parse_json(raw)
    keys = {
        "schema",
        "endpoint",
        "rule_version",
        "year",
        "page_size",
        "total_count",
        "collected_at",
        "content_sha256",
        "pages",
        "verification_page",
    }
    if (
        type(value) is not dict
        or set(value) != keys
        or value["schema"] != "ftc-brand-snapshot-v1"
        or value["endpoint"] != ENDPOINT
        or type(value["page_size"]) is not int
        or value["page_size"] != PAGE_SIZE
    ):
        fail("snapshot_contract")
    if value["rule_version"] != RULE_VERSION:
        fail("rule_version_mismatch")
    if (
        type(value["pages"]) is not list
        or not 1 <= len(value["pages"]) <= 100
        or type(value["collected_at"]) is not str
    ):
        fail("snapshot_contract")
    try:
        collected_at = datetime.fromisoformat(value["collected_at"])
    except ValueError:
        fail("collection_time")
    catalog = build_catalog(
        value["year"],
        tuple(_decode(p) for p in value["pages"]),
        _decode(value["verification_page"]),
        collected_at,
    )
    if (
        type(value["total_count"]) is not int
        or value["total_count"] != len(catalog.rows)
        or value["content_sha256"] != catalog.content_sha256
    ):
        fail("snapshot_content")
    return catalog, digest(raw)
