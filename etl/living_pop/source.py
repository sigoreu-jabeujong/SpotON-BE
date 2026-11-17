import csv
import hashlib
import io
import json
import re
import stat
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import IO, Any
from zoneinfo import ZoneInfo

from etl.living_pop.data import SOURCES, Observation, PopulationImportError, canonical, fail
from etl.living_pop.fields import FIELDS

ROOT = Path(__file__).resolve().parents[2]
MAX_MANIFEST_BYTES = 32768
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_CSV_BYTES = 64 * 1024 * 1024
MAX_ROWS = 500000
MAX_FIELD = 4096
PAD = {"local": 0, "long": 7, "short": 9}
DATASETS = {"local": "OA-22784", "long": "OA-22785", "short": "OA-22786"}
GRID_PATTERN = r"[가-힣]{2}[0-9]{8}"


@dataclass(frozen=True, repr=False)
class FileInput:
    path: Path
    sha256: str
    file_date: date | None = None


@dataclass(frozen=True, repr=False)
class Manifest:
    day: date
    grid: FileInput
    sources: dict[str, FileInput]


def unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(dict(items)) != len(items):
        fail("duplicate_manifest_key")
    return dict(items)


def load_manifest(path: Path, *, today: date | None = None) -> Manifest:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            fail("manifest_size")
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
        if not isinstance(value, dict) or set(value) != {"observation_date", "grid", "sources"}:
            fail("manifest_shape")
        day = date.fromisoformat(value["observation_date"])
        now = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
        if not date(2000, 1, 1) <= day <= now:
            fail("date")
        if not isinstance(value["sources"], dict) or set(value["sources"]) != set(SOURCES):
            fail("sources")

        def entry(item: Any, dated: bool) -> FileInput:
            expected = {"path", "sha256", "file_date"} if dated else {"path", "sha256"}
            if not isinstance(item, dict) or set(item) != expected:
                fail("manifest_file")
            if (
                not isinstance(item["path"], str)
                or not item["path"]
                or not isinstance(item["sha256"], str)
                or not re.fullmatch("[0-9a-f]{64}", item["sha256"])
            ):
                fail("manifest_file")
            p = (path.resolve().parent / item["path"]).resolve()
            if p.is_relative_to(ROOT):
                fail("repository_input")
            d = date.fromisoformat(item["file_date"]) if dated else None
            if d is not None and not day <= d <= now:
                fail("file_date")
            return FileInput(p, item["sha256"], d)

        return Manifest(
            day, entry(value["grid"], False), {s: entry(value["sources"][s], True) for s in SOURCES}
        )
    except PopulationImportError:
        raise
    except Exception:
        raise PopulationImportError("living_pop:manifest_invalid") from None


def verified_bytes(item: FileInput, limit: int) -> bytes:
    if item.path.resolve().is_relative_to(ROOT):
        fail("repository_input")
    with item.path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != item.sha256:
        fail("hash_or_size")
    return raw


class CountingReader(io.RawIOBase):
    def __init__(self, stream: IO[bytes]) -> None:
        self.stream = stream
        self.count = 0
        self.sha = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        chunk = self.stream.read(min(len(buffer), MAX_CSV_BYTES - self.count + 1))
        self.count += len(chunk)
        if self.count > MAX_CSV_BYTES:
            fail("expanded_size")
        self.sha.update(chunk)
        buffer[: len(chunk)] = chunk
        return len(chunk)


def population_cell(value: str) -> tuple[Decimal | None, str]:
    if value == "*":
        return None, "suppressed"
    if value == "":
        return None, "missing"
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{0,5})?", value):
        fail("population_value")
    return Decimal(value).quantize(Decimal("0.00001")), "observed"


def read_source(
    kind: str,
    item: FileInput,
    day: date,
    grid_ids: set[str],
    admin_pool: dict[str, str],
    grid_pool: dict[str, str],
) -> tuple[list[Observation], dict[str, Any]]:
    raw = verified_bytes(item, MAX_ZIP_BYTES)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) != 1:
            fail("csv_members")
        info = infos[0]
        if (
            not info.filename.lower().endswith(".csv")
            or info.is_dir()
            or any(c in info.filename for c in ("/", "\\", ":"))
            or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
            or info.flag_bits & 1
            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            or info.file_size > MAX_CSV_BYTES
        ):
            fail("csv_member")
        rows: list[Observation] = []
        seen = set()
        hours = set()
        statuses: Counter[str] = Counter()
        trailing: Counter[str] = Counter()
        unlocated = set()
        grids = set()
        with archive.open(info) as binary:
            counted = CountingReader(binary)
            with io.BufferedReader(counted) as buffered:
                encoding = "utf-8-sig" if buffered.peek(3).startswith(b"\xef\xbb\xbf") else "cp949"
                with io.TextIOWrapper(
                    buffered, encoding=encoding, errors="strict", newline=""
                ) as text_stream:
                    reader = csv.reader(text_stream, strict=True)
                    headers = next(reader, [])
                    if headers != list(FIELDS[kind]):
                        fail("headers")
                    for cells in reader:
                        if (
                            len(rows) >= MAX_ROWS
                            or len(cells) != len(headers) + PAD[kind]
                            or any(len(v) > MAX_FIELD for v in cells)
                        ):
                            fail("row_shape")
                        if any(cells[len(headers) :]):
                            fail("padding")
                        if any(any(ord(c) < 32 for c in v) for v in cells):
                            fail("control")
                        raw_day, hour, admin, grid_id, total = cells[:5]
                        if (
                            raw_day != day.strftime("%Y%m%d")
                            or not re.fullmatch(r"[0-2][0-9]", hour)
                            or int(hour) > 23
                        ):
                            fail("observation_time")
                        if not re.fullmatch(r"11[0-9]{6}(?: {5})?", admin) or not re.fullmatch(
                            GRID_PATTERN, grid_id
                        ):
                            fail("codes")
                        admin = admin_pool.setdefault(admin[:8], admin[:8])
                        grid_id = grid_pool.setdefault(grid_id, grid_id)
                        key = (int(hour), admin, grid_id)
                        if key in seen:
                            fail("duplicate")
                        seen.add(key)
                        hours.add(int(hour))
                        grids.add(grid_id)
                        value, status = population_cell(total)
                        trailing["total"] += total.endswith(".")
                        for v in cells[5 : len(headers)]:
                            population_cell(v)
                            trailing["detail"] += v.endswith(".")
                        located = grid_id in grid_ids
                        if not located:
                            unlocated.add(grid_id)
                        statuses[status] += 1
                        row_hash = hashlib.sha256(
                            canonical({"headers": headers, "cells": cells})
                        ).digest()
                        rows.append(
                            Observation(
                                kind, int(hour), admin, grid_id, value, status, located, row_hash
                            )
                        )
        if hours != set(range(24)) or not rows:
            fail("incomplete_day")
        if counted.count != info.file_size:
            fail("member_size")
    metadata = dict(
        dataset=DATASETS[kind],
        source_url=f"https://data.seoul.go.kr/dataList/{DATASETS[kind]}/S/1/datasetView.do",
        input_sha256=item.sha256,
        input_bytes=len(raw),
        declared_file_date=item.file_date.isoformat() if item.file_date else None,
        member_name=info.filename,
        member_sha256=counted.sha.hexdigest(),
        member_bytes=counted.count,
        member_modified=datetime(*info.date_time).isoformat(),
        encoding=encoding,
        padding=PAD[kind],
        rows=len(rows),
        statuses={s: statuses[s] for s in ("observed", "suppressed", "missing")},
        trailing_decimal_points={k: trailing[k] for k in ("total", "detail")},
        grids=len(grids),
        unlocated_grids=len(unlocated),
        unlocated_rows=sum(not r.located for r in rows),
        hours=sorted(hours),
    )
    return rows, metadata
