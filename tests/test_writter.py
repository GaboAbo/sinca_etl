"""Unit tests for scripts/build_catalog.py.

No network access: requests.get is replaced with a fake that serves
canned HTML, and time.sleep is stubbed so the suite runs instantly.
Run with:  uv run pytest -v
"""
from datetime import date

import pandas as pd
import pytest
import requests

from scripts import writter as bc


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, text: str = "", status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def link(macropath: str, macro: str, header: str = "Estacion Centro",
         frm: str = "121019", to: str = "260101", css: str = "iframe") -> str:
    """Build an anchor shaped like SINCA's parameter links.

    Uses raw '&macropath=' and '&macro=' on purpose: '&macr' is an HTML
    entity, and html.parser would silently mangle these hrefs.
    """
    href = (f"//sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.htmlindico2.cgi?page=pageFrame"
            f"&header={header}&macropath={macropath}&macro={macro}&from={frm}&to={to}&")
    return f'<a class="{css}" href="{href}">x</a>'


STATION_HTML = "<html><body>" + "".join([
    link("./RII/236/Cal/PM25", "PM25.diario.diario"),                 # daily -> skipped
    link("./RII/236/Cal/PM25", "PM25.horario.horario"),               # hourly Cal -> kept
    link("./RII/236/Met/TEMP", "horario_010"),                        # 10 m -> kept
    link("./RII/236/Met/TEMP", "horario_002", to="200304"),           # 2 m -> kept
    link("./RII/236/Cal/PM10", "PM10.horario.horario", css="other"),  # wrong class -> skipped
    link("./RII/236/Cal", "PM10.horario.horario"),                    # malformed -> skipped
]) + "</body></html>"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(bc.time, "sleep", lambda seconds: None)


@pytest.fixture
def written(monkeypatch):
    """Stub write_catalog so get_stations doesn't write into the cwd."""
    calls = []
    monkeypatch.setattr(bc, "write_catalog", lambda df, path: calls.append((df, path)))
    return calls


def serve(monkeypatch, pages: dict[str, FakeResponse]) -> list[str]:
    """Route requests.get by URL; unknown URLs get a 404. Returns URLs requested."""
    requested = []

    def fake_get(url, timeout=None):
        requested.append(url)
        return pages.get(url, FakeResponse(status=404))

    monkeypatch.setattr(bc.requests, "get", fake_get)
    return requested


# ---------------------------------------------------------------------------
# get_ids
# ---------------------------------------------------------------------------

def test_get_ids_dedupes_across_regions_and_sorts_numerically(monkeypatch):
    serve(monkeypatch, {
        bc.REGION_URL + "I":  FakeResponse('<a href="/index.php/estacion/index/id/275">'
                                           '<a href="/index.php/estacion/index/id/88">'),
        bc.REGION_URL + "II": FakeResponse('<a href="/index.php/estacion/index/id/1042">'
                                           '<a href="/index.php/estacion/index/id/275">'),
    })

    # numeric order, not string order (which would put "1042" before "275")
    assert bc.get_ids(["I", "II"]) == ["88", "275", "1042"]


def test_get_ids_ignores_other_links(monkeypatch):
    serve(monkeypatch, {
        bc.REGION_URL + "M": FakeResponse('<a href="/index.php/region/index/id/XV">'
                                          '<a href="/index.php/estacion/index/key/B05">'),
    })

    assert bc.get_ids(["M"]) == []


def test_get_ids_requests_every_region(monkeypatch):
    requested = serve(monkeypatch, {
        bc.REGION_URL + r: FakeResponse("") for r in ["I", "M"]
    })

    bc.get_ids(["I", "M"])

    assert requested == [bc.REGION_URL + "I", bc.REGION_URL + "M"]


def test_get_ids_raises_on_http_error(monkeypatch):
    serve(monkeypatch, {})  # every URL -> 404

    with pytest.raises(requests.HTTPError):
        bc.get_ids(["M"])


# ---------------------------------------------------------------------------
# get_stations: parsing
# ---------------------------------------------------------------------------

def test_get_stations_keeps_only_hourly_iframe_links(monkeypatch):
    serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse(STATION_HTML)})

    df = bc.get_stations(["275"])

    assert len(df) == 3
    assert set(df["macro"]) == {"PM25.horario.horario", "horario_010", "horario_002"}


def test_get_stations_survives_macro_html_entity(monkeypatch):
    """Regression: html.parser turns '&macropath' into '¯opath' and finds nothing."""
    serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse(STATION_HTML)})

    df = bc.get_stations(["275"])

    assert not df.empty
    assert (df["region"] == "RII").all()


def test_get_stations_row_fields(monkeypatch):
    serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse(STATION_HTML)})

    pm25 = bc.get_stations(["275"]).query("param == 'PM25'").iloc[0]

    assert pm25["page_id"] == "275"
    assert pm25["region"] == "RII"
    assert pm25["station"] == "236"      # inner code, distinct from the page id
    assert pm25["kind"] == "Cal"
    assert pm25["header"] == "Estacion Centro"
    assert pm25["from"] == "121019"
    assert pm25["to"] == "260101"
    assert pd.isna(pm25["height_m"])     # Cal rows carry no height


def test_get_stations_keeps_every_met_height(monkeypatch):
    serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse(STATION_HTML)})

    temp = bc.get_stations(["275"]).query("param == 'TEMP'").sort_values("height_m")

    assert temp["height_m"].tolist() == [2, 10]
    assert temp["to"].tolist() == ["200304", "260101"]


def test_get_stations_output_columns_and_order(monkeypatch):
    serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse(STATION_HTML)})

    df = bc.get_stations(["275"])

    assert list(df.columns) == bc.COLUMNS
    assert list(df.index) == list(range(len(df)))   # index reset after sorting
    assert df["kind"].tolist() == ["Cal", "Met", "Met"]


def test_get_stations_combines_multiple_stations(monkeypatch):
    other = "<html>" + link("./RM/D12/Cal/PM25", "PM25.horario.horario",
                            header="La Florida") + "</html>"
    serve(monkeypatch, {
        bc.STATION_URL + "275": FakeResponse(STATION_HTML),
        bc.STATION_URL + "262": FakeResponse(other),
    })

    df = bc.get_stations(["275", "262"])

    assert len(df) == 4
    assert set(df["station"]) == {"236", "D12"}


def test_get_stations_page_without_series_gives_empty_frame(monkeypatch):
    serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse("<html><body></body></html>")})

    df = bc.get_stations(["275"])

    assert df.empty
    assert list(df.columns) == bc.COLUMNS


def test_get_stations_raises_on_http_error(monkeypatch):
    serve(monkeypatch, {})  # every URL -> 404

    with pytest.raises(requests.HTTPError):
        bc.get_stations(["275"])


# ---------------------------------------------------------------------------
# get_stations: id resolution and side effects
# ---------------------------------------------------------------------------

def test_get_stations_discovers_ids_when_none_given(monkeypatch):
    monkeypatch.setattr(bc, "get_ids", lambda: ["275"])
    requested = serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse(STATION_HTML)})

    bc.get_stations(None)

    assert requested == [bc.STATION_URL + "275"]


def test_get_stations_refresh_replaces_given_ids(monkeypatch):
    monkeypatch.setattr(bc, "get_ids", lambda: ["275"])
    requested = serve(monkeypatch, {bc.STATION_URL + "275": FakeResponse(STATION_HTML)})

    bc.get_stations(["999"], refresh=True)

    assert requested == [bc.STATION_URL + "275"]   # "999" was never fetched


# ---------------------------------------------------------------------------
# write_catalog
# ---------------------------------------------------------------------------

class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 9, 22)


def test_write_catalog_writes_snapshot_and_stable_file(monkeypatch, tmp_path):
    monkeypatch.setattr(bc, "date", FixedDate)
    df = pd.DataFrame({"station": ["236", "D12"], "param": ["PM25", "PM25"]})
    target = tmp_path / "stations"

    bc.write_catalog(df, target)

    snapshot = target / "260922.csv"
    stable = tmp_path / "stations.csv"
    assert snapshot.exists()
    assert stable.exists()
    for file in (snapshot, stable):
        pd.testing.assert_frame_equal(pd.read_csv(file, dtype=str), df)


def test_write_catalog_overwrites_stable_file(monkeypatch, tmp_path):
    monkeypatch.setattr(bc, "date", FixedDate)
    target = tmp_path / "stations"

    bc.write_catalog(pd.DataFrame({"station": ["old"]}), target)
    bc.write_catalog(pd.DataFrame({"station": ["new"]}), target)

    assert pd.read_csv(tmp_path / "stations.csv")["station"].tolist() == ["new"]