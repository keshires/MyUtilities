# Contributing to MyUtilities

How to add new scripts, runbooks, SQL, or shared utilities to this repo.

## Adding a New Script

1. Drop the `.py` file in `<app>/scripts/` (e.g., `edfx/scripts/my_new_script.py`)

2. If the script uses `project_paths` (for input/output/logs paths), add this block
   at the top, before the `project_paths` import:
   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
   ```

3. If the script reads a `.env` file, use:
   ```python
   load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
   ```
   (`.parent.parent` because `.env` is at the app root, one level above `scripts/`)

4. Add any new environment variables to `<app>/.env.example` with a description comment.

5. Add any new Python dependencies to `<app>/requirements.txt`.

6. Add an entry to `<app>/utilities.yaml` (EDFX only) — this feeds the dashboard and
   Claude Code skills:
   ```yaml
   - name: my_new_script
     description: "One-line description"
     script: scripts/my_new_script.py
     env_vars: [VAR_ONE, VAR_TWO]
   ```

7. Write a runbook in `<app>/runbooks/` if this is an operational procedure
   someone will follow step-by-step.

8. Add tests in `<app>/tests/test_my_new_script.py`.

## Adding a Runbook Only (No Script)

1. Drop the `.md` file in `<app>/runbooks/`

2. Follow this structure:
   ```markdown
   # Runbook: <Title>

   **App:** EDFX | Credit Edge | RiskCalc
   **Env vars required:** LIST_THEM_HERE

   ## Prerequisites
   - ...

   ## Steps
   1. ...
   2. ...

   ## Troubleshooting
   ...
   ```

## Adding a SQL File

1. Drop the `.sql` file in `<app>/sql/`
2. Reference it from the relevant runbook with a relative path

## Adding a Shared Utility

1. Only add to `shared/` if the utility is used by **two or more apps**
2. Drop the file in `shared/`
3. Update `shared/README.md` with the new file's purpose and consumers
4. In each consuming script, add the `sys.path.insert` block (see above)

## Archiving an Old Script

1. `git mv <app>/scripts/old_script.py <app>/archive/`
2. Add a one-line comment at the top of the file explaining why it was archived

## Branch and PR Conventions

- Branch name: `<app>/<short-description>` (e.g., `edfx/add-entity-audit-script`)
- PR title: `feat(<app>): <description>` or `fix(<app>): <description>`
- One PR per logical change — don't bundle unrelated scripts
