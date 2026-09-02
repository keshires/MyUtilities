# Repository Architecture

`MyUtilities` is a shared support repo for EDFX, Credit Edge, and RiskCalc.
It provides operational scripts, runbooks, and analysis tools that any team member
can pick up and run.

## Folder Map

```
MyUtilities/
├── edfx/           EDFX scripts, runbooks, dashboard, tests
├── credit-edge/    Credit Edge scripts and runbooks
├── riskcalc/       RiskCalc scripts and runbooks
├── docuproj/       Cross-repo flow analyzer — standalone tool for EDFX fleet
├── shared/         Utilities shared across apps (project_paths.py, REPOS.md)
└── docs/           Repo-level docs (this file, contributing guide)
```

## Per-App Layout (consistent across all three apps)

```
<app>/
├── scripts/        Python utilities — one file per operation
├── runbooks/       Markdown step-by-step ops guides
├── sql/            SQL queries used by scripts or runbooks
├── tests/          pytest test files
├── archive/        Retired scripts — kept for reference, not actively run
├── docs/           Supporting docs, reports, slide decks
├── input/          Script input files (gitignored — create locally)
├── output/         Script output files (gitignored — create locally)
├── logs/           Run logs (gitignored — create locally)
├── .env.example    All env vars the app needs — copy to .env and fill in
├── requirements.txt Python dependencies for this app only
└── README.md       Setup + script catalog for this app
```

## Design Principles

- **App-first navigation** — start in your app folder; everything you need is there
- **Consistent anatomy** — same structure in every app; knowledge transfers instantly
- **Self-contained apps** — separate .env, requirements.txt, and venv per app; no shared secrets
- **One shared layer** — code used by 2+ apps lives in `shared/`, nowhere else
- **Runbooks alongside scripts** — operational procedures live next to the code they document

## DocuProj

`docuproj/` is a standalone project — a static analyzer that traces request flows
across the EDFX fleet of repos (endpoint → service → database). It is not part of
any single app. It reads `shared/REPOS.md` for the list of repos to analyze.
See `docuproj/README.md` for setup and usage.

## Claude Code Skills

Five Claude Code skills in `.claude/skills/` provide guided workflows for common
EDFX operations. They stay at the repo root so Claude Code discovers them regardless
of which app subfolder you are in. New skills for Credit Edge or RiskCalc follow the
same pattern, prefixed `credit-edge-*` or `riskcalc-*`.
