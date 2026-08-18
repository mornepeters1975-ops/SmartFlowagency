"""Unit tests for the agent-code normaliser against the variant table in CLAUDE.md."""

import json
from pathlib import Path

import pytest

from build import Normaliser, UNASSIGNED, load_aliases

ROOT = Path(__file__).parent.parent

ROSTER_CODES = {"MP120", "PC005", "PC014", "PC020", "PC004", "ML108", "ANM101", "IG021", "MP130"}
NAME_MAP = {"GARY OCTOBER": "MP130"}
VICIDIAL_MAP = {"6038": "ANM101", "5024": "IG021"}


@pytest.fixture
def normaliser():
    aliases = load_aliases(ROOT / "aliases.json")
    return Normaliser(
        roster_codes=ROSTER_CODES,
        code_aliases=aliases["code_aliases"],
        name_map={**NAME_MAP, **aliases["name_aliases"]},
        vicidial_map={**VICIDIAL_MAP, **aliases["vicidial_aliases"]},
    )


@pytest.mark.parametrize("raw,expected", [
    ("Mp120", "MP120"),
    ("MP12O", "MP120"),
    ("PCOO5", "PC005"),
    ("PCC014", "PC014"),
    ("PCC020", "PC020"),
    ("PC04", "PC004"),
    ("MLL108", "ML108"),
    ("ML10P8", "ML108"),
    ("6038", "ANM101"),
    ("5024", "IG021"),
    ("Gary October", "MP130"),
    ("PC014 FUNERAL POLICY OR LIFE COVER", "PC014"),
    ("  mp120  ", "MP120"),
    ("\tpc005\t", "PC005"),
])
def test_known_variants_resolve(normaliser, raw, expected):
    assert normaliser.resolve(raw) == expected


def test_unresolvable_code_goes_unassigned(normaliser):
    assert normaliser.resolve("ZZ999") == UNASSIGNED
    assert "ZZ999" in normaliser.unresolved


def test_none_and_nan_go_unassigned(normaliser):
    import pandas as pd
    assert normaliser.resolve(None) == UNASSIGNED
    assert normaliser.resolve(float("nan")) == UNASSIGNED


def test_aliases_file_has_the_documented_variants():
    aliases = json.loads((ROOT / "aliases.json").read_text())
    for key in ["PCOO5", "MP12O", "PCC014", "PCC020", "PC04", "MLL108", "ML10P8"]:
        assert key in aliases["code_aliases"], f"{key} missing from code_aliases"
    assert "GARY OCTOBER" in aliases["name_aliases"]
    assert aliases["vicidial_aliases"]["6038"] == "ANM101"
    assert aliases["vicidial_aliases"]["5024"] == "IG021"
