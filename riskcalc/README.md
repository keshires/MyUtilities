# RiskCalc Utilities

Scripts for RiskCalc support operations — SecurityService SOAP calls and LC file processing.

## Setup

```powershell
cd riskcalc
copy .env.example .env          # fill in your credentials
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/SecurityService.py` | Authenticate via RiskCalc SOAP SecurityService and retrieve user info |
| `scripts/LC_Process.py` | Process LC batch files from a UNC file share |

## Archive

`archive/` contains older test scripts kept for reference — not actively used.

## Input / Output / Logs

Scripts read/write under `input/`, `output/`, `logs/`. These are gitignored.
