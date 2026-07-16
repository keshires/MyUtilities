"""PD-aware pre-check: classify a stale entity as POST (refresh) or SKIP (with reason),
using its own PD date and its peer group's PD date. Pure logic — no DB/network here.

See docs/superpowers/specs/2026-07-15-pd-aware-presubmission-validation-design.md.
"""
from __future__ import annotations

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
