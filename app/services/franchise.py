"""Read-time estimates: stale evidence never overrides current source or external flags."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, func, not_, or_, select, true, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import BrandCatalogVersion as Catalog
from app.models import BrandMappingRun as Run
from app.models import BrandMappingState as State
from app.models import Store
from app.models import StoreBrandMatch as Match
from app.schemas.common import ApiMeta, ErrorCode
from app.schemas.franchise import (
    BrandDataVersion,
    EstimatedClassification,
    PendingClassification,
)
from app.schemas.nearby import NearbyQuery


def automatic_match() -> ColumnElement[bool]:
    keys = (
        select(Match.source, Match.license_no, Match.name, Match.category, Match.sub_category)
        .join(State, State.run_id == Match.run_id)
        .where(State.id == 1)
    )
    return and_(
        Store.deleted_at.is_(None),
        Store.category_review_flag.is_not(True),
        func.coalesce(
            tuple_(
                Store.source, Store.license_no, Store.name, Store.category, Store.sub_category
            ).in_(keys),
            False,
        ),
    )


def automatic_franchise() -> ColumnElement[bool]:
    return and_(Store.is_franchise.is_(None), Store.brand_id.is_(None), automatic_match())


def effective_franchise() -> ColumnElement[bool | None]:
    return case(
        (or_(Store.is_franchise.is_not(None), Store.brand_id.is_not(None)), Store.is_franchise),
        (automatic_match(), True),
        else_=None,
    )


def franchise_filter(query: NearbyQuery) -> ColumnElement[bool]:
    if query.franchise == "all" and query.include_unknown_franchise:
        return true()
    if query.franchise == "franchise" and query.include_unknown_franchise:
        return Store.is_franchise.is_not(False)
    if query.franchise == "independent" and not query.include_unknown_franchise:
        return Store.is_franchise.is_(False)
    positive = or_(Store.is_franchise.is_(True), automatic_franchise())
    if query.franchise == "franchise":
        return positive
    if query.franchise == "independent":
        return not_(positive)
    return or_(Store.is_franchise.is_not(None), automatic_franchise())


@dataclass(frozen=True)
class BrandContext:
    classification: PendingClassification | EstimatedClassification
    version: BrandDataVersion | None = None


def brand_context(session: Session) -> BrandContext:
    row = session.execute(
        select(Catalog, Run)
        .select_from(State)
        .join(Catalog, State.catalog_version_id == Catalog.catalog_version_id)
        .join(
            Run,
            and_(State.run_id == Run.run_id, State.catalog_version_id == Run.catalog_version_id),
        )
        .where(State.id == 1)
    ).one_or_none()
    if row is None:
        return BrandContext(PendingClassification())
    try:
        catalog, run = row
        return BrandContext(
            EstimatedClassification(reference_year=catalog.reference_year),
            BrandDataVersion.model_validate(
                dict(
                    catalog_version_id=catalog.catalog_version_id,
                    mapping_run_id=run.run_id,
                    input_sha256=catalog.input_sha256,
                    content_sha256=catalog.content_sha256,
                    store_input_sha256=run.store_input_sha256,
                    catalog_rule=catalog.catalog_rule,
                    rule_version=run.rule_version,
                    reference_year=catalog.reference_year,
                )
            ),
        )
    except (ValueError, TypeError, AttributeError):
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE) from None


def enrich_meta(meta: ApiMeta, context: BrandContext) -> None:
    meta["franchise_classification"] = context.classification.model_dump(mode="json")
    if context.version is not None:
        version = meta.get("data_version")
        if not isinstance(version, dict):
            raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
        version["brand_mapping"] = context.version.model_dump(mode="json")


def franchise_fields(store: Store, value: bool | None, context: BrandContext) -> dict[str, Any]:
    if value is None:
        return dict(franchise="unknown", franchise_basis=None, franchise_reference_year=None)
    if store.is_franchise is None and store.brand_id is None:
        if value is not True or not isinstance(context.classification, EstimatedClassification):
            raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
        return dict(
            franchise="franchise",
            franchise_basis="catalog_exact_name",
            franchise_reference_year=context.classification.reference_year,
        )
    return dict(
        franchise="franchise" if value else "independent",
        franchise_basis="external_classification",
        franchise_reference_year=None,
    )
