import pandas as pd
import numpy as np


CHOICE_LIST = ["faltante", "no_validado", "preliminar", "validado"]
QUALITY_RANK = {item: index for index, item in enumerate(CHOICE_LIST)}

def clean(df: pd.DataFrame, interp_limit: int = 3) -> pd.DataFrame:
    df = df.rename(
        columns={
            "FECHA (YYMMDD)": "fecha",
            "HORA (HHMM)": "hora",
            "Registros validados": "reg_val",
            "Registros preliminares": "reg_pre",
            "Registros no validados": "reg_no_val"
        }
    )

    df['timestamp'] = pd.to_datetime(
        df['fecha'] + df["hora"],
        format="%y%m%d%H%M"
    )
    df = df.set_index('timestamp').sort_index()

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

    was_na = df["value"].isna()
    df["value"] = df["value"].interpolate(method="time", limit=interp_limit, limit_area="inside")
    df["is_imputed"] = was_na & df["value"].notna()

    return df[["value", "quality", "quality_rank", "is_imputed"]]
