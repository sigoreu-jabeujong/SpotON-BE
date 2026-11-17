"""Shared annual CSV provenance and bounded single-member ZIP input."""

import hashlib
import io
import re
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, NoReturn


@dataclass(frozen=True, repr=False)
class AnnualArchive:
    source_year: int
    source_file_date: date
    input_sha256: str
    input_bytes: int
    member_name: str
    member_sha256: str
    member_bytes: int
    member_modified: str
    source_encoding: str
    source_rows: int
    rows: list[dict[str, Any]]
    markets: dict[str, dict[str, tuple[str, str]]]
    quarter_rows: dict[str, int]


def read_csv_member(
    path: Path,
    expected_sha256: str,
    *,
    root: Path,
    max_zip_bytes: int,
    max_csv_bytes: int,
    fail: Callable[[str], NoReturn],
) -> tuple[bytes, zipfile.ZipInfo, bytes]:
    if path.resolve().is_relative_to(root):
        fail("repository_input")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        fail("hash")
    with path.open("rb") as stream:
        raw = stream.read(max_zip_bytes + 1)
    if len(raw) > max_zip_bytes or hashlib.sha256(raw).hexdigest() != expected_sha256:
        fail("hash_or_size")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) != 1:
            fail("members")
        info = infos[0]
        if (
            not info.filename.lower().endswith(".csv")
            or any(c in info.filename for c in ("/", "\\", ":"))
            or any(ord(c) < 32 for c in info.filename)
            or info.is_dir()
            or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
            or info.flag_bits & 1
            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            or info.file_size > max_csv_bytes
        ):
            fail("member")
        with archive.open(info) as stream:
            data = stream.read(max_csv_bytes + 1)
        if len(data) > max_csv_bytes:
            fail("expanded_size")
    return raw, info, data
