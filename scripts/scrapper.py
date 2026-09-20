import requests, time, re
import pandas as pd

from datetime import date
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs


BASE_URL = "https://sinca.mma.gob.cl/index.php/region/index/id/"
REGIONS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIV", "XV", "XVI", "M"]

# Hit the base URL and try to extract all station IDs and their parameters
# If not possible, extract all station IDs and iterate thourgh them to take the parameters
# Store them in a json file within the data directory
# This job should be done once every 6 months or after a site change is made 
rows = []

for region_id in REGIONS:
    resp = requests.get(BASE_URL + region_id, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    for a in soup.find_all("a", href=re.compile(r"macropath=")):
        qs = parse_qs(urlparse(str(a["href"])).query)
        parts = qs.get("macropath", [""])[0].strip("./").split("/")
        if len(parts) != 4:
            continue
        region, station, kind, param = parts
        rows.append({"region": region, "station": station, "kind": kind, "param": param,
                    "name": qs.get("header", [""])[0],
                    "from": qs.get("from", [""])[0], "to": qs.get("to", [""])[0]})

    time.sleep(1)

Path("catalogs/").mkdir(parents=True, exist_ok=True)
today = date.today().strftime("%y%m%d")

df = pd.DataFrame(rows).sort_values(["region","station","kind","param"])
df.to_csv(f"catalogs/{today}.csv", index=False)
df.to_csv(f"catalog.csv", index=False)