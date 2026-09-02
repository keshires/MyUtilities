# shared/

Utilities and configuration shared across the EDFX, Credit Edge, and RiskCalc app folders.

## Contents

| File | Purpose | Used by |
|------|---------|---------|
| `project_paths.py` | Caller-aware path resolver: `PROJECT_ROOT`, `logs_dir()`, `output_dir()`, `input_dir()`, `resolve_project_relative()`, `resolve_cli_artifact()` | EDFX (14 scripts + dashboard), RiskCalc (LC_Process.py) |
| `REPOS.md` | EDFX fleet repo registry — 21 repos, languages, default branches | DocuProj (bootstrap.py, flow.py), developers adding repos |

## How to use project_paths from a script

Scripts live at `<app>/<subfolder>/script.py`. Add this block before the `project_paths` import:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from project_paths import logs_dir, output_dir  # import what you need
```

## How to add a new shared utility

1. Drop the file in `shared/`
2. Add it to the table above
3. Import it in consuming scripts using the same `sys.path.insert` pattern
