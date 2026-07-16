"""PD-aware pre-check: classify a stale entity as POST (refresh) or SKIP (with reason),
using its own PD date and its peer group's PD date. Pure logic — no DB/network here.

See docs/superpowers/specs/2026-07-15-pd-aware-presubmission-validation-design.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

POSTABLE_TYPES = {"custom", "private"}


def month_start(today: date) -> date:
    """First day of ``today``'s month — the target period for 'current PD'."""
    return today.replace(day=1)


def is_pd_current(entity_type: str, pd_date: date | None, ref_month_start: date) -> bool:
    """True if ``pd_date`` counts as the current period's PD.

    custom PDs land on the 1st; private/public land any day in the month. Both are
    'current' when the date is in the current month (>= ref_month_start).
    """
    if pd_date is None:
        return False
    return pd_date >= ref_month_start


def pd_periods_match(entity_type: str, entity_pd: date | None, group_pd: date | None) -> bool:
    """True if entity and peer-group PD are the 'same' period for the type.

    custom: exact date equality (both on the 1st). private/public: same calendar month.
    """
    if entity_pd is None or group_pd is None:
        return False
    if entity_type == "custom":
        return entity_pd == group_pd
    return (entity_pd.year, entity_pd.month) == (group_pd.year, group_pd.month)


@dataclass(frozen=True)
class Classification:
    category: str            # already_fresh | standalone | peer_unknown | matches_group | peer_lag
    action: str              # POST | SKIP
    reason: str
    group_fresh: bool | None = None


def classify(
    *,
    entity_type: str,
    is_peer_driven: bool,
    entity_pd: date | None,
    group_pd: date | None,
    ref_month_start: date,
) -> Classification:
    """Decide POST vs SKIP for one stale entity. See spec §4.1 decision table."""
    if is_pd_current(entity_type, entity_pd, ref_month_start):
        return Classification("already_fresh", "SKIP", "entity already has a current PD")
    if not is_peer_driven:
        return Classification("standalone", "POST", "not peer-driven; stale PD")
    if group_pd is None:
        return Classification("peer_unknown", "POST", "peer-driven but peer-group PD unknown")
    if pd_periods_match(entity_type, entity_pd, group_pd):
        return Classification("matches_group", "SKIP", "entity PD matches peer-group PD")
    group_fresh = is_pd_current(entity_type, group_pd, ref_month_start)
    return Classification(
        "peer_lag", "POST", "entity PD older than peer-group PD", group_fresh=group_fresh
    )


@dataclass(frozen=True)
class StaleRow:
    external_id: str
    tenant_id: str
    pd_last_known_date: date | None
    peer_id: str | None
    is_peer_driven: bool
    custom_id: str | None = None
    financials_process_id: str | None = None


class PeerGroupPdResolver(ABC):
    """Resolves each peer group's authoritative latest PD date."""

    @abstractmethod
    def resolve(self, peer_ids: Iterable[str]) -> dict[str, date | None]:
        ...


class DbMaxPeerGroupPdResolver(PeerGroupPdResolver):
    """Fallback resolver: group PD date = MAX(pd_last_known_date) over peerId.

    ``fetch(ids)`` returns ``[(peer_id, max_pd_date), ...]`` — injected so this is
    unit-testable offline and swappable for a live asyncpg query in the scripts.
    """

    def __init__(self, fetch: Callable[[list[str]], list[tuple[str, date | None]]]) -> None:
        self._fetch = fetch

    def resolve(self, peer_ids: Iterable[str]) -> dict[str, date | None]:
        ids = [pid for pid in dict.fromkeys(peer_ids) if pid]
        if not ids:
            return {}
        return {pid: pd for pid, pd in self._fetch(ids)}


class ApiPeerGroupPdResolver(PeerGroupPdResolver):
    """Authoritative external-source resolver. Endpoint/auth not wired yet (spec §8)."""

    def __init__(self, base_url: str, token_provider: Callable[[], str] | None = None) -> None:
        self.base_url = base_url
        self.token_provider = token_provider

    def resolve(self, peer_ids: Iterable[str]) -> dict[str, date | None]:
        raise NotImplementedError(
            "External peer-group PD endpoint not wired yet; use DbMaxPeerGroupPdResolver."
        )


def classify_all(
    rows: list[StaleRow],
    resolver: PeerGroupPdResolver,
    entity_type: str,
    ref_month_start: date,
) -> list[tuple[StaleRow, Classification]]:
    """Classify every row, batch-resolving peer-group PD dates once."""
    group = resolver.resolve([r.peer_id for r in rows if r.peer_id]) if rows else {}
    return [
        (
            r,
            classify(
                entity_type=entity_type,
                is_peer_driven=r.is_peer_driven,
                entity_pd=r.pd_last_known_date,
                group_pd=(group.get(r.peer_id) if r.peer_id else None),
                ref_month_start=ref_month_start,
            ),
        )
        for r in rows
    ]


def post_ids(
    rows: list[StaleRow],
    resolver: PeerGroupPdResolver,
    entity_type: str,
    ref_month_start: date,
) -> set[str]:
    """external_ids whose classification action is POST (used by the refresh pre-filter)."""
    return {
        r.external_id
        for r, c in classify_all(rows, resolver, entity_type, ref_month_start)
        if c.action == "POST"
    }


# ---------------------------------------------------------------------------
# Authoritative PD check via /edfx/v1/entities/pds (spec §8 resolver, now wired).
# The model computes on-demand with endDate=today; a refresh can only persist a
# current-period PD if the model can produce one. So: POST iff pds returns a `pd`
# whose `asOfDate` is in the current period; otherwise the post would be futile.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PdResult:
    as_of_date: date | None
    has_pd: bool
    message: str | None = None


def _parse_iso_date(value: object) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_pds_entity(obj: dict) -> PdResult:
    """Parse one entity object from a /edfx/v1/entities/pds response."""
    return PdResult(
        as_of_date=_parse_iso_date(obj.get("asOfDate")),
        has_pd=obj.get("pd") is not None,
        message=obj.get("message"),
    )


def pds_entity_id(row: StaleRow, entity_type: str) -> str | None:
    """The entityId to send to /edfx/v1/entities/pds.

    private/public: the external_id. custom: ``<external_id>-<financials_process_id>``
    (from entity_custom_data). Returns None for custom lacking a financials_process_id.
    """
    if entity_type == "custom":
        if not row.financials_process_id:
            return None
        return f"{row.external_id}-{row.financials_process_id}"
    return row.external_id


def classify_by_pds(
    entity_type: str, result: "PdResult | None", ref_month_start: date
) -> Classification:
    """Decide POST vs SKIP from the authoritative pds result."""
    if result is None:
        return Classification("pds_unknown", "POST", "no pds result; posting conservatively")
    if not result.has_pd:
        return Classification("no_pd", "SKIP", f"model returns no PD ({result.message or 'no pd'})")
    if is_pd_current(entity_type, result.as_of_date, ref_month_start):
        return Classification("current_pd", "POST", "model has a current-period PD; refresh will persist it")
    return Classification("source_stale", "SKIP", "model's latest PD predates the current period")


class EntityPdResolver(ABC):
    """Resolves each entity's authoritative PD (as_of_date + whether a pd exists)."""

    @abstractmethod
    def resolve(self, rows: list[StaleRow], entity_type: str) -> dict[str, PdResult]:
        ...


class StaticEntityPdResolver(EntityPdResolver):
    """Offline/test resolver: fixed {external_id: PdResult} mapping."""

    def __init__(self, mapping: dict[str, PdResult]) -> None:
        self._mapping = mapping

    def resolve(self, rows: list[StaleRow], entity_type: str) -> dict[str, PdResult]:
        return dict(self._mapping)


def classify_all_pds(
    rows: list[StaleRow],
    resolver: EntityPdResolver,
    entity_type: str,
    ref_month_start: date,
) -> list[tuple[StaleRow, Classification]]:
    results = resolver.resolve(rows, entity_type) if rows else {}
    return [
        (r, classify_by_pds(entity_type, results.get(r.external_id), ref_month_start))
        for r in rows
    ]


def post_ids_pds(
    rows: list[StaleRow],
    resolver: EntityPdResolver,
    entity_type: str,
    ref_month_start: date,
) -> set[str]:
    return {
        r.external_id
        for r, c in classify_all_pds(rows, resolver, entity_type, ref_month_start)
        if c.action == "POST"
    }
