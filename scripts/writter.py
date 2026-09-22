import requests, time, re
import pandas as pd

from datetime import date
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs


REGION_URL  = "https://sinca.mma.gob.cl/index.php/region/index/id/"
STATION_URL = "https://sinca.mma.gob.cl/index.php/estacion/index/id/"
REGIONS     = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIV", "XV", "XVI", "M"]
COLUMNS     = ["page_id", "region", "station", "kind", "param", "header", "from", "to", "height_m", "macro"]
STATION_PAT = re.compile(r"estacion/index/id/(\d+)")


def write_catalog(df: pd.DataFrame, path: Path) -> None:
    Path(f"{path}/").mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%y%m%d")
    df.to_csv(f"{path}/{today}.csv", index=False)
    df.to_csv(f"{path}.csv", index=False)


def get_ids(regions: list = REGIONS) -> list[str]:
    ids = set()

    for region in regions:
        response = requests.get(REGION_URL + region, timeout=30)
        response.raise_for_status()
        ids.update(STATION_PAT.findall(response.text))
        
        time.sleep(1)

    return sorted(ids, key=int)


def get_stations(ids: list[str] | None = None, refresh: bool = False) -> pd.DataFrame:
    if not ids or refresh:
        ids = get_ids()

    rows = []
    for id_ in ids:
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

    df = pd.DataFrame(rows, columns=COLUMNS)
    df["height_m"] = df["height_m"].astype("Int64") 
    return df.sort_values(["region", "station", "kind", "param", "macro"]).reset_index(drop=True)


if __name__ == "__writter__":
    df = get_stations(get_ids())
    write_catalog(df, Path("stations"))
