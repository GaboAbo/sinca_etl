"""Transform step: turn raw SINCA rows into a clean hourly series.

``CHOICE_LIST`` lists the quality tiers from worst to best and
``QUALITY_RANK`` maps each tier to its position, so a higher rank means a
better-validated reading.
"""

import pandas as pd
import numpy as np


CHOICE_LIST = ["faltante", "no_validado", "preliminar", "validado"]
QUALITY_RANK = {item: index for index, item in enumerate(CHOICE_LIST)}

def clean(df: pd.DataFrame, kind: str = "Cal", param: str = "PM25", interp_limit: int = 3) -> pd.DataFrame:
    """Parse, coalesce and gap-fill a raw SINCA series.

    1. Build a ``timestamp`` index from the date and time columns.
    2. Parse the three reading columns as floats (comma decimal separator;
       unparsable values become ``NaN``).
    3. Take ``value`` from the best tier available for each hour
       (validated, then preliminary, then not validated) and record the
       tier in ``quality`` and ``quality_rank``.
    4. Fill interior gaps by time-weighted interpolation and flag the
       filled rows in ``is_imputed``. At most ``interp_limit`` consecutive
       rows are filled per gap: in a longer gap the first
       ``interp_limit`` rows are filled and the rest stay ``NaN``. Leading
       and trailing gaps are never filled.

    Args:
        df: Raw rows as returned by :func:`src.extract.load_raw`.
        interp_limit: Maximum number of consecutive missing rows to fill
            in each gap.

    Returns:
        DataFrame indexed by ``timestamp`` with columns ``value`` (float),
        ``quality`` (a tier from ``CHOICE_LIST``), ``quality_rank`` (int)
        and ``is_imputed`` (bool). Imputed rows keep the ``faltante``
        quality they had before interpolation.
    """

    df['timestamp'] = pd.to_datetime(
        df['fecha'] + df["hora"],
        format="%y%m%d%H%M"
    )
    df = df.set_index('timestamp').sort_index()

    if kind == "Cal":
        cols = ['reg_val', 'reg_pre', 'reg_no_val']
        for col in cols:
            df[col] = pd.to_numeric(
                df[col].str.replace(",", ".", regex=False),
                errors="coerce"
            )

        df["value"] = df["reg_val"].combine_first(df["reg_pre"]).combine_first(df["reg_no_val"])
        df["quality"] = np.select(
            condlist=[df["value"].isna(), df["reg_no_val"].notna(), df["reg_pre"].notna(), df["reg_val"].notna()],
            choicelist=CHOICE_LIST,
            default=CHOICE_LIST[0]
        )
        df["quality_rank"] = df["quality"].map(QUALITY_RANK)
    else:
        df["value"] = pd.to_numeric(
            df["valor"].str.replace(",", ".", regex=False),
            errors="coerce"
        )
  
    
    was_na = df["value"].isna()
    df["value"] = df["value"].interpolate(method="time", limit=interp_limit, limit_area="inside")
    df["is_imputed"] = was_na & df["value"].notna()

    return df[["value", "quality", "quality_rank", "is_imputed"]]
