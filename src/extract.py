"""Extract step: download hourly series from SINCA's CSV export.

SINCA has no documented API; the request format was reverse-engineered from
the site's export link (see the URL notes below the constants). Raw
responses are cached as Parquet files in ``RAW_DIR`` so repeated runs over
the same date range don't hit the server again.
"""

import pandas as pd
import requests, io

from urllib.parse import urlencode
from datetime import date
from pathlib import Path


RAW_DIR = Path("data/snapshots")
BASE = "https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi"
COLUMNS_BY_KIND = {
    "Cal": ["fecha", "hora", "reg_val", "reg_pre", "reg_no_val"],
    "Met": ["fecha", "hora", "valor"],
}

"""
These are the links I was able to get exploring and playing at the SINCA site
    Cal params
    https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi?outtype=xcl&macro=./RM/D12/Cal/PM25//PM25.horario.horario.ic&from=000101&to=260908&path=/usr/airviro/data/CONAMA/&lang=esp&rsrc=&macropath=
    Met params
    https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi?outtype=xcl&macro=./RM/D11/Met/RHUM//horario_000.ic&from=220823&to=220830&path=/usr/airviro/data/CONAMA/&lang=esp&rsrc=&macropath=

    Base url:       https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi?
    File type:      outtype=xcl&
    Data selector
        RM (Region Metropolitana):      macro=./RM
        D12 station I was poiting at:   /D12
        Cal (Calidad):                  /Cal/PM25//PM25.horario.horario.ic&
        Met (Meteorologico):            /RM/D11/Met/RHUM//horario_000.ic&
    YYMMDD format: from=000101&
    YYMMDD format: to=260908&
    Untouched params: path=/usr/airviro/data/CONAMA/&lang=esp&rsrc=&macropath=
"""

def fetch_data(
        region: str = "RM",
        station: str = "D12",
        kind: str = "Cal",
        param: str = "PM25",
        start: str = "000101",
        end: str = "260924",
        macro: str = "PM25.horario.horario") -> pd.DataFrame:
    """Download one hourly series from SINCA's CSV export endpoint.

    Decodes the response as Latin-1, keeps the date, time and the three
    validation-tier columns as strings, and also writes the result to
    ``RAW_DIR`` as Parquet.

    Args:
        region: SINCA region code (e.g. ``"RM"``).
        station: Station code (e.g. ``"D12"``).
        kind: Series kind (e.g. ``"Cal"`` for air quality).
        pollutant: Parameter code (e.g. ``"PM25"``).
        start: First day to fetch, as ``YYMMDD``.
        end: Last day to fetch, as ``YYMMDD``.

    Returns:
        Raw rows with the columns ``FECHA (YYMMDD)``, ``HORA (HHMM)``,
        ``Registros validados``, ``Registros preliminares`` and
        ``Registros no validados``, all as strings.

    Raises:
        requests.HTTPError: If SINCA returns an error status.
    """
    params = {
        "outtype": "xcl",
        "macro": f"./{region}/{station}/{kind}/{param}//{macro}.ic",
        "from": start,
        "to": end,
        "path": "/usr/airviro/data/CONAMA/",
        "lang": "esp", "rsrc": "", "macropath": "",
    }
    
    url = f"{BASE}?{urlencode(params, safe="./")}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = "latin-1"

    names = COLUMNS_BY_KIND[kind]
    df = pd.read_csv(
        io.StringIO(resp.text),
        sep=";",
        decimal=",",
        header=0,
        names=names,
        usecols=range(len(names)),
        dtype=str
        )

    if not df["fecha"].fillna("").str.fullmatch(r"\d{6}").all():
        raise ValueError(f"{station}/{param}/{macro}: response is not an hourly series")

    return df


def load_raw(
        region: str = "RM",
        station: str = "D12",
        kind: str = "Cal",
        param: str = "PM25",
        start: date = date(2000, 1, 1),
        end: date | None = None,
        macro: str = "PM25.horario.horario",
        use_cache: bool = True) -> pd.DataFrame:
    """Return the raw series for a date range, from cache when possible.

    The cache file is
    ``RAW_DIR/<region>_<station>_<pollutant>_<start>_<end>.parquet`` with
    dates as ``YYMMDD``. On a cache miss, or with ``use_cache=False``, the
    data is fetched with :func:`fetch_data` and the cache file is
    overwritten.

    Args:
        region: SINCA region code (e.g. ``"RM"``).
        station: Station code (e.g. ``"D12"``).
        kind: Series kind (e.g. ``"Cal"`` for air quality).
        pollutant: Parameter code (e.g. ``"PM25"``).
        start: First day to fetch.
        end: Last day to fetch, or ``None`` for today.
        use_cache: Read the cache file if it exists.

    Returns:
        Raw rows in the format returned by :func:`fetch_data`.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    _start = start.strftime("%y%m%d")
    _end = (end or date.today()).strftime("%y%m%d")
    path = RAW_DIR / f"{region}_{station}_{param}_{macro}_{_start}_{_end}.parquet"

    if use_cache and path.exists():
        return pd.read_parquet(path)
    
    df = fetch_data(region, station, kind, param, _start, _end, macro)
    df.to_parquet(path, index=False)

    return df
