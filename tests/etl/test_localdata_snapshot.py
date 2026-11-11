import json
from collections import Counter
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from etl.localdata.collection import AuthorityStats, CollectedSource
from etl.localdata.constants import SEOUL_AUTHORITY_CODES, Source
from etl.localdata.dto import LocalDataRow
from etl.localdata.snapshot import DTO_FIELDS, SnapshotError, load_snapshot, save_snapshot


def collection(rows: tuple[LocalDataRow, ...] | None = None) -> CollectedSource:
    if rows is None:
        rows = tuple(
            LocalDataRow.from_api(
                {
                    "OPN_ATMY_GRP_CD": "3000000",
                    "MNG_NO": f"synthetic-{index}",
                    "BPLC_NM": "private-name-canary",
                    "LOTNO_ADDR": "private-address-canary",
                    "LCPMT_YMD": "2024-01-01",
                    "SALS_STTS_CD": "01",
                    "SALS_STTS_NM": "영업/정상",
                    "SNTTN_BZSTAT_NM": "한식",
                    "TELNO": "phone-must-not-be-saved",
                    "DAT_UPDT_SE": "private-update-canary",
                }
            )
            for index in range(2)
        )
    counts = Counter(row.authority_code for row in rows)
    return CollectedSource(
        Source.GENERAL_RESTAURANT,
        datetime(2026, 11, 11, 12),
        tuple(
            AuthorityStats(code, counts[code], 1, counts[code]) for code in SEOUL_AUTHORITY_CODES
        ),
        rows,
    )


def test_allowlist_covers_exact_dto_and_roundtrip(tmp_path: Path) -> None:
    assert set(DTO_FIELDS) == {item.name for item in fields(LocalDataRow)}
    original = collection()
    path = save_snapshot(original, tmp_path)
    assert load_snapshot(path, original.source) == original
    assert "phone-must-not-be-saved" not in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize(
    "mutation", ["hash", "row_count", "authority", "extra", "missing", "type", "source", "version"]
)
def test_tampered_or_incomplete_snapshot_rejected(tmp_path: Path, mutation: str) -> None:
    original = collection()
    path = save_snapshot(original, tmp_path)
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "hash":
        payload["rows"][0]["business_name"] = "changed"
    elif mutation == "row_count":
        payload["row_count"] += 1
    elif mutation == "authority":
        payload["authorities"].pop()
    elif mutation == "extra":
        payload["rows"][0]["phone"] = "private-phone"
    elif mutation == "missing":
        payload["rows"][0].pop("raw_x")
    elif mutation == "type":
        payload["rows"][0]["raw_x"] = 1
    elif mutation == "source":
        payload["source"] = Source.REST_CAFE.value
    elif mutation == "version":
        payload["format_version"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_snapshot(path, original.source)


def test_partial_nonfinite_and_duplicate_authorities_rejected(tmp_path: Path) -> None:
    path = tmp_path / "partial.json"
    path.write_text('{"rows": NaN}', encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_snapshot(path, Source.GENERAL_RESTAURANT)
    path.write_text('{"rows":', encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_snapshot(path, Source.GENERAL_RESTAURANT)
    path.write_text('{"rows":[],"rows":[]}', encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_snapshot(path, Source.GENERAL_RESTAURANT)
    with pytest.raises(SnapshotError):
        load_snapshot(tmp_path / "file.part", Source.GENERAL_RESTAURANT)
    original = collection()
    duplicate = replace(original, authorities=(original.authorities[0],) * 25)
    with pytest.raises(SnapshotError):
        save_snapshot(duplicate, tmp_path)


def test_atomic_publish_failure_leaves_no_partial_or_final_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object) -> None:
        raise OSError("simulated-publish-failure")

    monkeypatch.setattr("etl.localdata.snapshot.os.link", fail)
    with pytest.raises(OSError):
        save_snapshot(collection(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_existing_snapshot_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr("etl.localdata.snapshot.uuid4", lambda: SimpleNamespace(hex="fixed"))
    original = collection()
    path = save_snapshot(original, tmp_path)
    previous = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_snapshot(original, tmp_path)
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.part"))
