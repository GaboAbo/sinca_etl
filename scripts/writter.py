import requests, time, re, logging, argparse
import pandas as pd

from datetime import date
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs


REGION_URL      = "https://sinca.mma.gob.cl/index.php/region/index/id/"
STATION_URL     = "https://sinca.mma.gob.cl/index.php/estacion/index/id/"
REGIONS         = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIV", "XV", "XVI", "M"]
COLUMNS         = ["page_id", "region", "station", "kind", "param", "header", "from", "to", "height_m", "macro"]
STATION_PAT     = re.compile(r"estacion/index/id/(\d+)")
REFERENCE_PATH  = Path("archive")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def write_catalogs(df: pd.DataFrame, path: Path = REFERENCE_PATH) -> None:    
    snapshots = path / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%y%m%d")
    df.to_csv(snapshots / f"catalog_{today}.csv", index=False)
    df.to_csv(path / "catalog.csv", index=False)
    logger.info("wrote %d stations to %s", len(df), path)
    

def get_ids(regions: list = REGIONS) -> list[str]:
    ids = set()

    for region in regions:
        response = requests.get(REGION_URL + region, timeout=30)
        response.raise_for_status()
        ids.update(STATION_PAT.findall(response.text))
        
        time.sleep(1)

    logger.info("%s ids extracted", len(ids))

    return sorted(ids, key=int)


def get_stations(ids: list[str] = []) -> pd.DataFrame:
    rows = []
    for i, id_ in enumerate(ids, start=1):
        response = requests.get(STATION_URL+id_, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        as_ = soup.find_all("a", class_="iframe", href=re.compile(r"macropath="))
        for a in as_:
            qs = parse_qs(urlparse(str(a["href"])).query)
            parts = qs.get("macropath", [""])[0].strip("./").split("/")
            if len(parts) != 4:
                continue

            macro   = qs.get("macro", [""])[0]
            is_hourly_cal = macro.endswith("horario.horario")
            is_hourly_met = macro.startswith("horario_")
            if not (is_hourly_cal or is_hourly_met):
                continue
            
            region, station, kind, param = parts
            header  = qs.get("header", [""])[0]
            from_   = qs.get("from", [""])[0]
            to_     = qs.get("to", [""])[0]
            
            rows.append({
                "page_id": id_,
                "region": region, "station": station, "kind": kind, "param": param,
                "header": header, "from": from_, "to": to_,
                "height_m": int(macro.split("_")[1]) if is_hourly_met else None,
                "macro": macro
        })

        time.sleep(1)
        if i % 25 == 0 or i == len(ids):
            logger.info("parsed %d/%d station pages, %d series so far", i, len(ids), len(rows))

    df = pd.DataFrame(rows, columns=COLUMNS)
    df["height_m"] = df["height_m"].astype("Int64") 
    return df.sort_values(["region", "station", "kind", "param", "macro"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the SINCA station catalog")
    parser.add_argument("-r", "--refresh", action="store_true", help="rebuild even if a catalog already exists")
    args = parser.parse_args()

    if (REFERENCE_PATH / "stations.csv").exists() and not args.refresh:
        logger.info("catalog exists at %s; use --refresh to rebuild", REFERENCE_PATH)
        return

    ids = get_ids()
    if not ids:
        raise RuntimeError("no station ids found; SINCA's layout may have changed")

    stations = get_stations(ids)
    write_catalogs(stations)


if __name__ == "__main__":
    main()
