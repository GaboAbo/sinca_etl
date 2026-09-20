# SINCA Air Quality Pipeline

An ETL pipeline that ingests hourly air quality data from Chile's
[SINCA](https://sinca.mma.gob.cl) (Sistema de Información Nacional de Calidad del Aire)
network, cleans it, and loads it into a local SQLite database.

Default target: **La Florida station (D12)**, Región Metropolitana, PM2.5.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
git clone <repo-url>
cd sinca_laflorida
uv sync
```

## Usage

Run the pipeline with defaults (La Florida, PM2.5):

```bash
uv run python -m main
```

On first run it backfills the full history (2000-01-01 to today, ~234k hourly rows).
Afterwards it runs incrementally, refetching the last 30 days so that readings which
SINCA has since validated get upgraded in place.

### Options

| Flag | Description |
|------|-------------|
| `-f`, `--full` | Force a full backfill from 2000-01-01 |
| `-s`, `--station` | Station code (default: `D12`) |
| `-p`, `--pollutant` | Parameter to fetch (default: `PM25`) |
| `-n`, `--no-cache` | Ignore the local raw cache and refetch |

Examples:

```bash
uv run python -m main --pollutant PM10      # different pollutant
uv run python -m main --station D14         # different station
uv run python -m main --full                # full refresh
```

## Scheduling

Hourly incremental runs, plus a weekly full sweep to pick up late validations:

```cron
0 * * * *  cd /path/to/sinca_laflorida && uv run python -m main >> logs/pipeline.log 2>&1
0 3 * * 0  cd /path/to/sinca_laflorida && uv run python -m main --full >> logs/pipeline.log 2>&1
```

Create the log directory first: `mkdir -p logs`

## Output

Data lands in `data/sinca.db`, table `measurements`:

| Column | Type | Description |
|--------|------|-------------|
| `station` | TEXT | Station code (e.g. `D12`) |
| `pollutant` | TEXT | Parameter code (e.g. `PM25`) |
| `timestamp` | TEXT | Hour of the reading (ISO format) |
| `value` | REAL | Measured value, `NULL` where unknown |
| `quality` | TEXT | Validation tier of the source reading |
| `quality_rank` | INTEGER | Numeric rank of `quality` (0–3) |
| `is_imputed` | INTEGER | `1` if the value was interpolated |
| `updated_at` | DATETIME | When the row was last written |

Primary key: `(station, pollutant, timestamp)`

Example query:

```sql
SELECT quality, COUNT(*)
FROM measurements
GROUP BY quality
ORDER BY COUNT(*) DESC;
```

## Data quality

SINCA publishes each reading at one of three validation stages, which mature over time:

| `quality` | `quality_rank` | Meaning |
|-----------|----------------|---------|
| `validado` | 3 | Officially validated |
| `preliminar` | 2 | Under review |
| `no_validado` | 1 | Raw, recently recorded |
| `faltante` | 0 | No reading available |

The pipeline coalesces the three source columns into a single `value`, keeping the
highest-quality reading available for each hour and recording which tier it came from.

Gaps of **3 hours or less** are filled by time-weighted interpolation and flagged with
`is_imputed = 1`. Longer gaps are left as `NULL` rather than fabricated, since a
straight-line fill across a long outage can mask real pollution episodes. Interpolation
is restricted to interior gaps, so readings are never extrapolated past the last
measurement.

Loads are idempotent: re-running never duplicates rows, and an existing row is
overwritten only when the incoming reading has a *higher* validation rank. This means
the database self-heals as SINCA validates its data, and stale refetches can never
downgrade a good reading.

## Project structure

```
src/
├── extract.py     # fetch_data / load_raw — hits SINCA, caches raw responses
├── transform.py   # clean — parsing, typing, coalescing, gap handling
└── load.py        # to_sqlite / get_last_date — idempotent upsert into SQLite
main.py            # CLI entry point, orchestrates extract → transform → load
data/              # SQLite database and raw Parquet cache (gitignored)
logs/              # run logs (gitignored)
```

## Data source

Data is fetched from SINCA's public CSV export endpoint, which has no documented API.
The request format was reverse-engineered from the site's export function.