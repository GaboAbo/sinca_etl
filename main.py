"""Command-line entry point for the SINCA air quality pipeline.

Reads the station catalog built by ``scripts/writter.py``, checks the
requested station and parameter against it, and runs extract -> transform ->
load for that one series, writing the result to the local SQLite database.

Run ``uv run python -m main --help`` to see the options and the available
parameter codes.
"""

import logging, argparse, sys
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
from scripts.writter import REFERENCE_PATH

from src.extract import load_raw
from src.transform import clean
from src.load import to_sqlite, get_last_date


DEFAULT_START = date(2000, 1, 1)
LOOKBACK_DAYS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def load_catalog(path: Path) -> pd.DataFrame:
    """Read the station catalog CSV into a typed DataFrame.

    Args:
        path: Catalog CSV written by ``scripts/writter.py``.

    Returns:
        One row per series. Columns are strings except ``height_m``
        (nullable ``Int64``) and ``from``/``to``, which are parsed from
        ``YYMMDD`` into ``datetime.date``.
    """
    cat = pd.read_csv(path, dtype=str)
    cat["height_m"] = pd.to_numeric(cat["height_m"]).astype("Int64")
    for col in ("from", "to"):
        cat[col] = pd.to_datetime(cat[col], format="%y%m%d").dt.date

    return cat


def params_help(cat: pd.DataFrame) -> str:
    """Build the list of parameter codes shown at the end of ``--help``.

    Args:
        cat: Catalog as returned by :func:`load_catalog`.

    Returns:
        A multi-line string listing the unique ``param`` codes, sorted,
        under "Air quality" (``Cal``) and "Meteorological" (``Met``).
    """
    lines = []
    for kind, label in (("Cal", "Air quality"), ("Met", "Meteorological")):
        lines.append(f"{label}:")
        lines += [f"  {p}" for p in sorted(cat.loc[cat["kind"] == kind, "param"].unique())]

    return "\n".join(lines)


def run(
        region: str = "RM",
        station: str = "D12",
        kind: str = "Cal",
        param: str = "PM25",
        start: date | None = None,
        end: date | None = None,
        macro: str = "PM25.horario.horario",
        full: bool = False,
        use_cache: bool = True) -> dict:
    """Run extract -> transform -> load for a single series.

    When ``start`` is ``None`` it is picked automatically:

    * ``full=True``: backfill from ``DEFAULT_START``.
    * No rows stored yet for this station and pollutant: backfill from
      ``DEFAULT_START``.
    * Otherwise: incremental run from ``LOOKBACK_DAYS`` before the last
      stored date, with the cache turned off so readings that SINCA has
      validated since the last run are refetched.

    Args:
        region: SINCA region code (e.g. ``"RM"``).
        station: Station code (e.g. ``"D12"``).
        kind: Series kind from the catalog, ``"Cal"`` (air quality) or
            ``"Met"`` (meteorological).
        pollutant: Parameter code (e.g. ``"PM25"``).
        start: First day to fetch, or ``None`` to pick it as above.
        end: Last day to fetch, or ``None`` for today.
        full: Force a full backfill. Ignored when ``start`` is given.
        use_cache: Reuse the cached raw file for the same date range if it
            exists. Always off in incremental mode.

    Returns:
        Load statistics from :func:`src.load.to_sqlite`.
    """
    if start is None:
        if full:
            start = DEFAULT_START
            logger.info("mode=full backfill")
        else:
            last = get_last_date(station=station, pollutant=param)
            if last is None:
                start= DEFAULT_START
                logger.info("mode=backfill (no existing data)")
            else:
                start = last - timedelta(days=LOOKBACK_DAYS)
                use_cache = False
                logger.info("mode=incremental last=%s lookback=%dd", last, LOOKBACK_DAYS)

    logger.info("start %s/%s %s from=%s to=%s.", region, station, param, start, end or "today")

    raw = load_raw(region=region, station=station, kind=kind, param=param, start=start, end=end, macro=macro, use_cache=use_cache)
    if raw.empty:
        logger.warning("rows not fetched - source may be unavailable")
    else:
        logger.info("fetched %s rows", len(raw))

    clean_df = clean(df=raw, kind=kind, param=param)
    logger.info("cleaned %s rows (%s imputed)", len(clean_df), int(clean_df["is_imputed"].sum()))

    stats = to_sqlite(df=clean_df, station=station, pollutant=param)
    logger.info("loaded %s", stats)

    return stats


def main() -> None:
    """Parse command-line arguments and run the pipeline for one series.

    Looks up ``--station`` and ``--param`` in the catalog, requiring
    ``--height`` when the parameter is measured at more than one height,
    and checks ``--start``/``--end`` against the series' available date
    range before calling :func:`run`. Invalid arguments exit with a usage
    error; any exception from the pipeline is logged and re-raised.
    """
    catalog_path = REFERENCE_PATH / "catalog.csv"
    if not catalog_path.exists():
        sys.exit(f"{catalog_path} not found: run the catalog builder first")

    catalog = load_catalog(catalog_path)

    parser = argparse.ArgumentParser(
        description="SINCA air quality pipeline",
        epilog=params_help(catalog),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-f", "--full", action="store_true", help="force full backfill")
    parser.add_argument("-t", "--station", default="D12", help="station code")
    parser.add_argument("-p", "--param", default="PM25",
                        choices=sorted(catalog["param"].unique()), metavar="PARAM",
                        help="parameter code (listed below)")
    parser.add_argument("-H", "--height", type=int, help="sensor height in metres (Met only)")
    parser.add_argument("-s", "--start", type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("-e", "--end", type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("-n", "--no-cache", action="store_true", help="ignore cache")
    args = parser.parse_args()

    series = catalog[(catalog["station"] == args.station) & (catalog["param"] == args.param)]
    if args.height is not None:
        series = series[series["height_m"] == args.height]
    if series.empty:
        parser.error(f"no {args.param} series at station {args.station}" + (f" at {args.height} m" if args.height is not None else ""))
    if len(series) > 1:
        heights = sorted(series["height_m"].dropna().tolist())
        parser.error(f"{args.param} at {args.station} is measured at {heights} m; choose one with --height")

    row = series.iloc[0]

    latest = min(row["to"], date.today())
    if args.start and args.start < row["from"]:
        parser.error(f"--start is before this series begins ({row['from']})")
    if args.end and args.end > latest:
        parser.error(f"--end is after the last available date ({latest})")
    if args.start and args.end and args.start > args.end:
        parser.error("--start must be on or before --end")

    try:
        run(region=row["region"], station=row["station"], kind=row["kind"],
            param=row["param"],
            start=args.start, end=args.end,
            full=args.full, use_cache=not args.no_cache, macro=row["macro"])
    except Exception:
        logger.exception("pipeline run failed")
        raise


if __name__ == "__main__":
    main()
