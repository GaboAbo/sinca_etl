import pandas as pd

from scripts.writter import get_stations
from pathlib import Path


def read(path: Path, refresh: bool = False) -> pd.DataFrame:
    if refresh or not path.exists:
        df = get_stations(ids=None)
        return df
    
    df = pd.read_csv(f"{path}.csv")
    return df
