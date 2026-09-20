import logging, argparse
from datetime import date, timedelta

from src.extract import load_raw
from src.transform import clean
from src.load import to_sqlite, get_last_date


DEFAULT_START = date(2000, 1, 1)
LOOKBACK_DAYS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

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
    parser = argparse.ArgumentParser(description="SINCA air quality pipeline")
    parser.add_argument("-f", "--full", action="store_true", help="force full backfill")
    parser.add_argument("-s", "--station", type=str, default="D12", help="station to work with")
    parser.add_argument(
        "-p", "--pollutant", type=str,
        choices=["SO2", "NO", "NO2", "CO", "O3", "NOX", "PM10", "PM25",
                 "RH", "RH3M", "TEMP", "TEMP3M", "WDIR", "WDIR10M", "WSPD", "WSPD10M"],
        default="PM25",
        help="""
        pollutant or meterological parameter to work with

        SO2:        Sulfur dioxide (SO2 - μg/m3N)
        NO:         Nitrogen monoxide (NO - ppb)
        NO2:        Nitrogen dioxide (NO2 - ppb)
        CO:         Carbon monoxide (CO - ppm)
        O3:         Ozone (O3 - ppb)
        NOX:        Nitrogen oxides (NOX - ppb)
        PM10:       Particulate matter PM10 (PM10 - μg/m3N)
        PM25:       Particulate matter PM2.5 (PM2.5 - μg/m3)
        RH:         Relative air humidity at sea level (Relative humidity - %)
        RH3M:       Relative air humidity at 3m over sea level (Relative humidity - %)
        TEMP:       Ambient temperature at sea level (Temperature - °C)
        TEMP3M:     Ambient temperature at 3m over sea level (Temperature - °C)
        WDIR:       Wind direction at sea level (Wind dir. - °)
        WDIR10M:    Wind direction at 10m over sea level (Wind dir. - °)
        WSPD:       Wind speed at sea level (Wind speed - m/s)
        WSPD10M:    Wind speed at 10m over sea level (Wind speed - m/s)
        """)
    parser.add_argument("-n", "--no_cache", action="store_true", help="ignore cache")
    args = parser.parse_args()
    MET_PARAMS = {"RH","RH3M","TEMP","TEMP3M","WDIR","WDIR10M","WSPD","WSPD10M"}
    kind = "Met" if args.pollutant in MET_PARAMS else "Cal"
    try:
        run(station=args.station, pollutant=args.pollutant, kind=kind, full=args.full, use_cache=not args.no_cache)
    except Exception:
        logger.exception("pipeline run failed")
        raise


if __name__ == "__main__":
    main()
