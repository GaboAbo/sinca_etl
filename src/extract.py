import pandas as pd
import requests, io

from urllib.parse import urlencode
from datetime import date
from pathlib import Path


RAW_DIR = Path("data/raw")
BASE = "https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi"

"""
This is the link I was able to get exploring and playing at the SINCA
    https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi?outtype=xcl&macro=./RM/D12/Cal/PM25//PM25.horario.horario.ic&from=000101&to=260908&path=/usr/airviro/data/CONAMA/&lang=esp&rsrc=&macropath=

    Base url:       https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi?
    File type:      outtype=xcl&
    Data selector
        RM (Region Metropolitana):      macro=./RM
        D12 station I was poiting at:   /D12
        Cal (Calidad):                  /Cal/PM25//PM25.horario.horario.ic&
    YYMMDD format: from=000101&
    YYMMDD format: to=260908&
    Untouched params: path=/usr/airviro/data/CONAMA/&lang=esp&rsrc=&macropath=
"""

def fetch_data(
        region: str = "RM",
        station: str = "D12",
        kind: str = "Cal",
        pollutant: str = "PM25",
        start: str = "000101",
        end: str | None = None) -> pd.DataFrame:

    params = {
        "outtype": "xcl",
        "macro": f"./{region}/{station}/{kind}/{pollutant}//{pollutant}.horario.horario.ic",
        "from": start,
        "to": end,
        "path": "/usr/airviro/data/CONAMA/",
        "lang": "esp", "rsrc": "", "macropath": "",
    }

    url = f"{BASE}?{urlencode(params, safe="./")}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = "latin-1"

    df = pd.read_csv(
        io.StringIO(resp.text),
        sep=";",
        decimal=",",
        usecols=[
            "FECHA (YYMMDD)",
            "HORA (HHMM)",
            "Registros validados",
            "Registros preliminares",
            "Registros no validados"
        ],
        dtype={
            "FECHA (YYMMDD)": str,
            "HORA (HHMM)": str,
            "Registros validados": str,
            "Registros preliminares": str,
            "Registros no validados": str
            }
        )

    df.to_parquet(RAW_DIR / f"{region}_{station}_{pollutant}_{start}_{end}.parquet")

    return df


def load_raw(
        region: str = "RM",
        station: str = "D12",
        kind: str = "Cal",
        pollutant: str = "PM25",
        start: date = date(2000, 1, 1),
        end: date | None = None,
        use_cache: bool = True) -> pd.DataFrame:

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    _start = start.strftime("%y%m%d")
    _end = (end or date.today()).strftime("%y%m%d")
    path = RAW_DIR / f"{region}_{station}_{pollutant}_{_start}_{_end}.parquet"

    if use_cache and path.exists():
        return pd.read_parquet(path)
    
    df = fetch_data(region, station, kind, pollutant, _start, _end)
    df.to_parquet(path, index=False)

    return df
