# Portfolio KPI runner

Connects to Tessera Postgres, reads portfolio keys from the `portfolio` table (defaults: PK column **`id`**, tenant column **`Tenant_Id`**), then lists them and/or runs `calculate_portfolio_kpis` per id. Settings come from `.env` (see `.env.example`) or the environment.

If Postgres says `column "Id" does not exist` and hints `portfolio.id`, your PK is lowercase **`id`** — use the default or `PORTFOLIO_ID_COLUMN=id` in `.env`. Only use `Id` if the database was created with a quoted `"Id"` column.

Install once: `python -m pip install -r requirements.txt`

Required in `.env` (or the shell): `TESSERA_POSTGRES_HOST`, `TESSERA_POSTGRES_DB`, `TESSERA_POSTGRES_USER`, `TESSERA_POSTGRES_PASSWORD`. Optional: `TESSERA_POSTGRES_PORT` (default `5432`). Copy `.env.example` to `.env` and fill in values.

## Run commands

From the project folder (`run_portfolio_kpis_postgres.py` and `.env` must be here):

| Command |
|---------|
| `python run_portfolio_kpis_postgres.py --help` |
| `python run_portfolio_kpis_postgres.py` |
| `python run_portfolio_kpis_postgres.py --tenant-id <your-tenant-id>` |
| `python run_portfolio_kpis_postgres.py --list-only` |
| `python run_portfolio_kpis_postgres.py --tenant-id <your-tenant-id> --list-only` |
| `python run_portfolio_kpis_postgres.py --tenant-id <your-tenant-id> --list-only --export-list portfolio_ids.csv` |
| `python run_portfolio_kpis_postgres.py --portfolio-id 40657` |
| `python run_portfolio_kpis_postgres.py --portfolio-ids 40657,40658` |
| `python run_portfolio_kpis_postgres.py --export-list logs\ids.csv` |

Copy only the text inside the table cell—do not paste markdown `|` characters into the terminal.

Logs default to `logs\` with a name that includes the date and options used. Override with env var `KPI_LOG_FILE` if needed.

Do not use `--tenant-id` together with `--portfolio-id` or `--portfolio-ids`.
