from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from etl.brands.catalog import Brand as CatalogBrand
from etl.brands.catalog import normalize_name
from etl.chains.common import digest, fail, read_json


class BrandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,79}$")
    name: str = Field(min_length=1, max_length=255)
    aliases: tuple[str, ...] = Field(min_length=1, max_length=100)
    legal_prefixes: tuple[str, ...] = ()
    source_url: str = Field(max_length=1024)
    reviewed_on: date
    branch_patterns: bool = False
    approved_short_aliases: tuple[str, ...] = ()
    ftc_refs: tuple[tuple[str, str], ...] = ()
    origin: Literal["reviewed_seed", "ftc_exact"] = "reviewed_seed"

    @property
    def canonical_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, "spoton:chain:" + self.key)

    @model_validator(mode="after")
    def valid(self) -> "BrandSpec":
        url = urlsplit(self.source_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.query
            or url.fragment
            or url.username
            or url.password
            or self.reviewed_on > datetime.now(ZoneInfo("Asia/Seoul")).date()
        ):
            raise ValueError("source")
        for value in (self.name, *self.aliases, *self.legal_prefixes):
            if not value.strip() or len(value) > 255 or any(ord(c) < 32 for c in value):
                raise ValueError("text")
        normalized = tuple(normalize_name(a) for a in self.aliases)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate_alias")
        if any(a not in self.aliases for a in self.approved_short_aliases):
            raise ValueError("short_alias")
        if any(
            sum(c.isalnum() for c in a) < 3 and a not in self.approved_short_aliases
            for a in self.aliases
        ):
            raise ValueError("short_alias")
        if self.origin == "ftc_exact" and (self.branch_patterns or self.approved_short_aliases):
            raise ValueError("catalog_pattern")
        return self


def load_registry(path: Path | None = None) -> tuple[BrandSpec, ...]:
    value = read_json(path or Path(__file__).with_name("registry.json"), 5 * 1024**2)
    try:
        if type(value) is not dict or set(value) != {"schema", "brands"}:
            fail("registry_contract")
        if value["schema"] != "chain-registry-v1" or type(value["brands"]) is not list:
            fail("registry_contract")
        if not 1 <= len(value["brands"]) <= 10000:
            fail("registry_size")
        result = tuple(BrandSpec.model_validate(row) for row in value["brands"])
        if len({b.key for b in result}) != len(result):
            fail("registry_duplicate")
        refs = [ref for b in result for ref in b.ftc_refs]
        if len(set(refs)) != len(refs):
            fail("registry_source_conflict")
        return tuple(sorted(result, key=lambda b: b.key))
    except (ValidationError, TypeError, KeyError):
        fail("registry_contract")


def registry_hash(brands: tuple[BrandSpec, ...]) -> str:
    return digest([b.model_dump(mode="json") for b in sorted(brands, key=lambda b: b.key)])


def catalog_links(
    seeds: tuple[BrandSpec, ...], rows: tuple[CatalogBrand, ...]
) -> dict[str, dict[str, str | int]]:
    result: dict[str, dict[str, str | int]] = {}
    identifiers = Counter(b.management_no for b in rows)
    for seed in seeds:
        aliases = {normalize_name(a) for a in seed.aliases}
        approved = [b for b in rows if (b.management_no, b.headquarter_no) in seed.ftc_refs]
        candidates = [b for b in rows if b.normalized_name in aliases]
        collisions = sum(
            (b.management_no, b.headquarter_no) not in seed.ftc_refs for b in candidates
        )
        if seed.ftc_refs:
            if len(approved) < len(seed.ftc_refs):
                status = "absent"
            elif len(approved) > len(seed.ftc_refs) or any(
                identifiers[b.management_no] > 1 for b in approved
            ):
                status = "multiple"
            elif any(b.normalized_name not in aliases for b in approved):
                status = "name_changed"
            else:
                status = "present"
        else:
            status = "unapproved_name_candidate" if candidates else "absent"
        result[seed.key] = dict(
            status=status,
            approved_rows=len(approved),
            name_candidates=len(candidates),
            alias_collision_rows=collisions,
        )
    return result


def extend_catalog(
    seeds: tuple[BrandSpec, ...], rows: tuple[CatalogBrand, ...], reviewed_on: date
) -> tuple[BrandSpec, ...]:
    """Catalog suffixes stay disabled; repeated source identities stay quarantined."""
    counts = Counter(b.management_no for b in rows)
    names = Counter(b.normalized_name for b in rows)
    approved = {ref: b for b in seeds for ref in b.ftc_refs}
    result = list(seeds)
    for row in rows:
        ref = (row.management_no, row.headquarter_no)
        if ref in approved:
            seed = approved[ref]
            # Check approved links before short-name/repeated-ID guards, including Bonjuk.
            if row.normalized_name not in {normalize_name(a) for a in seed.aliases}:
                fail("approved_catalog_alias_changed")
            continue
        if (
            row.industry != "외식"
            or counts[row.management_no] != 1
            or names[row.normalized_name] != 1
            or sum(c.isalnum() for c in row.normalized_name) < 3
            or not any(c.isalpha() for c in row.normalized_name)
        ):
            continue
        result.append(
            BrandSpec(
                key="ftc-" + digest(ref),
                name=row.name,
                aliases=(row.name,),
                source_url="https://www.data.go.kr/data/15125467/openapi.do",
                reviewed_on=reviewed_on,
                ftc_refs=(ref,),
                origin="ftc_exact",
            )
        )
    return tuple(sorted(result, key=lambda b: b.key))
