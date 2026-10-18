"""Read the station catalog from disk or rebuild it by scraping SINCA."""

import pandas as pd

from scripts.writter import get_stations
from pathlib import Path


def read(path: Path, refresh: bool = False) -> pd.DataFrame:
    """Return the station catalog, from disk or freshly scraped.

    Args:
        path: Catalog location without the ``.csv`` extension; the file
            read is ``<path>.csv``.
        refresh: Scrape SINCA with :func:`scripts.writter.get_stations`
            instead of reading from disk.

    Returns:
        The station catalog.
    """
    if refresh or not path.exists:
        df = get_stations(ids=None)
        return df
    
    df = pd.read_csv(f"{path}.csv")
    return df
