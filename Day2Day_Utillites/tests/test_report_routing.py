import argparse

import portfolio_kpi_metrics_postgres as mod


def test_is_pivot():
    assert mod.is_pivot("entity_by_source")
    assert mod.is_pivot("portfolio_entity_source")
    assert not mod.is_pivot("status_summary")


def test_parser_accepts_env_and_top():
    # ensure --env and --top are wired without running a query.
    p = mod.build_arg_parser()
    assert isinstance(p, argparse.ArgumentParser)
    ns = p.parse_args([
        "--start", "2026-05-20 00:00:00",
        "--end", "2026-05-21 00:00:00",
        "--report", "entity_by_source",
        "--env", "qa",
        "--top", "25",
    ])
    assert ns.env == "qa"
    assert ns.top == 25
