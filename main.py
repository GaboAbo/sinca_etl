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
    cat = pd.read_csv(path, dtype=str)
    cat["height_m"] = pd.to_numeric(cat["height_m"]).astype("Int64")
    for col in ("from", "to"):
        cat[col] = pd.to_datetime(cat[col], format="%y%m%d").dt.date

    return cat


def params_help(cat: pd.DataFrame) -> str:
    lines = []
    for kind, label in (("Cal", "Air quality"), ("Met", "Meteorological")):
        lines.append(f"{label}:")
        lines += [f"  {p}" for p in sorted(cat.loc[cat["kind"] == kind, "param"].unique())]

    return "\n".join(lines)


def run(
        region: str = "RM",
        station: str = "D12",
        kind: str = "Cal",
        pollutant: str = "PM25",
        start: date | None = None,
        end: date | None = None,
        full: bool = False,
        use_cache: bool = True) -> dict:
    
    if start is None:
        if full:
            start = DEFAULT_START
            logger.info("mode=full backfill")
        else:
            last = get_last_date(station=station, pollutant=pollutant)
            if last is None:
                start= DEFAULT_START
                logger.info("mode=backfill (no existing data)")
            else:
                start = last - timedelta(days=LOOKBACK_DAYS)
                use_cache = False
                logger.info("mode=incremental last=%s lookback=%dd", last, LOOKBACK_DAYS)

    logger.info("start %s/%s %s from=%s to=%s.", region, station, pollutant, start, end or "today")

    raw = load_raw(region=region, station=station, kind=kind, pollutant=pollutant, start=start, end=end, use_cache=use_cache)
    if raw.empty:
        logger.warning("rows not fetched - source may be unavailable")
    else:
        logger.info("fetched %s rows", len(raw))

    clean_df = clean(raw)
    logger.info("cleaned %s rows (%s imputed)", len(clean_df), int(clean_df["is_imputed"].sum()))

    stats = to_sqlite(df=clean_df, station=station, pollutant=pollutant)
    logger.info("loaded %s", stats)

    return stats


def main() -> None:
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
            pollutant=row["param"],
            start=args.start, end=args.end,
            full=args.full, use_cache=not args.no_cache)
    except Exception:
        logger.exception("pipeline run failed")
        raise


if __name__ == "__main__":
    main()
