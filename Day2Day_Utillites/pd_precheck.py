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
