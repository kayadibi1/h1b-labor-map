"""Unit tests for geographic normalization."""

import polars as pl

from src.geo_normalize import attach_cbsa, city_state_to_cbsa


def test_dc_metro_cities_map_to_47900():
    assert city_state_to_cbsa("Washington", "DC") == "47900"
    assert city_state_to_cbsa("Arlington", "VA") == "47900"
    assert city_state_to_cbsa("Bethesda", "MD") == "47900"
    assert city_state_to_cbsa("McLean", "VA") == "47900"


def test_baltimore_separate_from_dc():
    assert city_state_to_cbsa("Baltimore", "MD") == "12580"


def test_seattle_metro():
    assert city_state_to_cbsa("Redmond", "WA") == "42660"
    assert city_state_to_cbsa("Bellevue", "WA") == "42660"


def test_attach_cbsa_to_dataframe(staging_dir):
    df = pl.DataFrame(
        {
            "worksite_city": ["Washington", "Seattle", "Made Up Town"],
            "worksite_state": ["DC", "WA", "ZZ"],
        }
    )
    out = attach_cbsa(df)
    assert "cbsa_code" in out.columns
    cbsa = out["cbsa_code"].to_list()
    assert cbsa[0] == "47900"
    assert cbsa[1] == "42660"
    assert cbsa[2] is None
