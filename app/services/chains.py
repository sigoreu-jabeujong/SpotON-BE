"""One immutable generation and one source revision per repeatable-read request."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, exists, false, literal, select, text, true, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.models import Store
from app.models.chain import (
    CHAIN_FIELDS,
    PUBLICATION_RULE,
    ChainPublication,
    ChainPublicationBrand,
    ChainPublicationState,
    ChainSourceState,
)
from app.models.chain import (
    StoreChainClassification as Evidence,
)
from app.schemas.chains import ChainBrand, ChainQuery
from app.schemas.common import ApiMeta, ErrorCode


def source_revision(session: Session) -> int:
    health = session.scalar(
        text("""
        SELECT count(*)=1 FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
        WHERE t.tgrelid='public.stores'::regclass
          AND t.tgname='spoton_chain_source_changed' AND NOT t.tgisinternal
          AND t.tgenabled='A' AND t.tgtype=60
          AND p.oid='public.spoton_chain_source_changed()'::regprocedure
          AND p.prosecdef AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']
    """)
    )
    revision = session.scalar(select(ChainSourceState.revision).where(ChainSourceState.id == 1))
    if health is not True or revision is None or revision < 0:
        raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
    return revision


@dataclass(frozen=True)
class ChainSelection:
    publication: ChainPublication | None
    drift: bool
    query: ChainQuery | None = None

    @classmethod
    def load(cls, session: Session, query: ChainQuery | None = None) -> "ChainSelection":
        revision = source_revision(session)
        state = session.get(ChainPublicationState, 1)
        if state is None:
            return cls(None, False, query)
        publication = session.get(ChainPublication, state.generation)
        if (
            publication is None
            or publication.rule_version != PUBLICATION_RULE
            or publication.manifest.get("schema") != PUBLICATION_RULE
            or state.validated_source_revision > revision
        ):
            raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
        return cls(publication, state.validated_source_revision != revision, query)

    def valid(self) -> ColumnElement[bool]:
        if self.publication is None:
            return false()
        identity = and_(
            Evidence.generation == self.publication.generation,
            Evidence.source == Store.source,
            Evidence.license_no == Store.license_no,
        )
        return and_(
            identity,
            *(
                getattr(Evidence, k).is_not_distinct_from(getattr(Store, k))
                for k in CHAIN_FIELDS
                if k not in {"source", "license_no"}
            ),
            Evidence.reason != "semas_address_corroborated" if self.drift else true(),
        )

    def estimated(self) -> ColumnElement[bool]:
        return exists(
            select(literal(1)).where(self.valid(), Evidence.classification_status == "estimated")
        )

    def status(self) -> Any:
        return case(
            (self.estimated(), literal("estimated")),
            (
                exists(
                    select(literal(1)).where(
                        self.valid(), Evidence.classification_status == "conflict"
                    )
                ),
                literal("conflict"),
            ),
            else_=literal("unknown"),
        )

    def count_status(self) -> Any:
        stale = (
            false()
            if self.publication is None
            else exists(
                select(literal(1)).where(
                    Evidence.generation == self.publication.generation,
                    Evidence.source == Store.source,
                    Evidence.license_no == Store.license_no,
                )
            )
        )
        return case(
            (self.status() != "unknown", self.status()),
            (stale, literal("stale_or_drift")),
            else_=literal("unknown"),
        )

    def predicate(self) -> ColumnElement[bool]:
        query = self.query
        if query is None:
            return true()
        positive = self.estimated() if query.brand_evidence == "include_estimates" else false()
        if query.brand_scope == "non_chain":
            return ~positive if query.brand_unknown == "include" else false()
        return true() if query.brand_unknown == "include" else positive

    def meta(self) -> ApiMeta:
        publication = self.publication
        return {
            "status": "estimate" if publication else "pending",
            "generation": str(publication.generation) if publication else None,
            "rule_version": PUBLICATION_RULE,
            "policy": "franchised_direct_small_chains",
            "source_drift": self.drift,
            "published_at": publication.created_at.isoformat() if publication else None,
            "source": {
                k: publication.manifest["sources"].get(k)
                for k in ("catalog_year", "semas_month", "semas_observed_at")
            }
            if publication
            else None,
            "brand_time_basis": "observed_record",
            "historical_membership": "not_verified",
            "capabilities": {
                "estimated_chain": True,
                "confirmed_chain": False,
                "confirmed_non_chain": False,
                "operation_type": False,
                "historical_membership": False,
            },
            "limitations": [
                "estimated_membership_not_contract",
                "license_records_not_outlet_count",
                "historical_membership_not_verified",
                "unknown_is_not_non_chain",
            ],
        }

    def brands(
        self, session: Session, identities: list[tuple[str, str]]
    ) -> dict[tuple[str, str], ChainBrand]:
        result: dict[tuple[str, str], ChainBrand] = {}
        if self.publication is None:
            return result
        for offset in range(0, len(identities), 500):
            rows = session.execute(
                select(
                    Store.source, Store.license_no, Evidence, ChainPublicationBrand, self.valid()
                )
                .select_from(Store)
                .join(
                    Evidence,
                    and_(
                        Evidence.generation == self.publication.generation,
                        Evidence.source == Store.source,
                        Evidence.license_no == Store.license_no,
                    ),
                )
                .outerjoin(
                    ChainPublicationBrand,
                    and_(
                        ChainPublicationBrand.generation == Evidence.generation,
                        ChainPublicationBrand.brand_key == Evidence.brand_key,
                    ),
                )
                .where(
                    tuple_(Store.source, Store.license_no).in_(identities[offset : offset + 500])
                )
            )
            for source, license_no, evidence, brand, valid in rows:
                if not valid:
                    result[(source, license_no)] = ChainBrand(
                        status="unknown",
                        reason="source_drift"
                        if self.drift and evidence.reason == "semas_address_corroborated"
                        else "stale_input",
                    )
                else:
                    sources = self.publication.manifest["sources"]
                    result[(source, license_no)] = ChainBrand(
                        status=evidence.classification_status,
                        brand_key=evidence.brand_key,
                        name=brand.name if brand else None,
                        basis=evidence.reason,
                        reason=evidence.reason,
                        reference_year=sources.get("catalog_year")
                        if evidence.reason == "catalog_exact_name_estimate"
                        else None,
                        reference_month=sources.get("semas_month")
                        if evidence.reason == "semas_address_corroborated"
                        else None,
                    )
        return result
