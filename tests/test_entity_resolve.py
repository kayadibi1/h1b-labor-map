"""Unit tests for entity resolution."""

from src.entity_resolve import load_corporate_groups, resolve_employers


def test_corporate_groups_loaded():
    groups = load_corporate_groups()
    assert "GOOGLE" in groups
    assert "META PLATFORMS" in groups
    assert groups["META PLATFORMS"] == "META / FACEBOOK"


def test_resolve_exact_alias_match(staging_dir):
    resolved = resolve_employers(["Google LLC", "Microsoft Corporation"])
    assert resolved["Google LLC"] == "ALPHABET / GOOGLE"
    assert resolved["Microsoft Corporation"] == "MICROSOFT"


def test_resolve_unknown_employer_returns_none(staging_dir):
    resolved = resolve_employers(["Some Tiny Startup XYZ"])
    assert resolved["Some Tiny Startup XYZ"] is None
