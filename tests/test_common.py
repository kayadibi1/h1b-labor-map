"""Unit tests for common utilities."""

from src.common import normalize_employer_name, normalize_wage_to_annual


def test_normalize_employer_name_strips_suffixes():
    assert normalize_employer_name("Google LLC") == "GOOGLE"
    assert normalize_employer_name("Microsoft Corporation") == "MICROSOFT"
    assert normalize_employer_name("Meta Platforms, Inc.") == "META PLATFORMS"
    assert normalize_employer_name("Tata Consultancy Services Ltd.") == "TATA CONSULTANCY SERVICES"


def test_normalize_employer_name_handles_dba():
    assert "DBA" not in normalize_employer_name("Foo Bar DBA Baz")
    assert "INC" not in normalize_employer_name("Some Co. Inc.")


def test_normalize_employer_name_handles_ampersand():
    assert normalize_employer_name("Smith & Jones LLC") == "SMITH AND JONES"


def test_normalize_wage_to_annual_hourly():
    assert normalize_wage_to_annual(50.0, "Hour") == 50.0 * 2080


def test_normalize_wage_to_annual_yearly():
    assert normalize_wage_to_annual(100000.0, "Year") == 100000.0


def test_normalize_wage_to_annual_weekly():
    assert normalize_wage_to_annual(2000.0, "Week") == 2000.0 * 52


def test_normalize_wage_to_annual_unknown_returns_none():
    assert normalize_wage_to_annual(100.0, "Decade") is None
