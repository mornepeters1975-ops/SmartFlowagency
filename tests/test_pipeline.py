"""End-to-end acceptance tests, run against the synthetic fixtures in
tests/fixtures/input/ (see tests/fixtures/make_fixtures.py for how they were
built and what each row is there to prove)."""

from datetime import date
from pathlib import Path

import pytest

from build import assemble, UNASSIGNED

ROOT = Path(__file__).parent.parent
INPUT_DIR = ROOT / "tests" / "fixtures" / "input"
TRACKER = INPUT_DIR / "YesUCan_Agent_Tracker.xlsx"
ALIASES = ROOT / "aliases.json"


@pytest.fixture(scope="module")
def result():
    return assemble(INPUT_DIR, TRACKER, ALIASES, as_of=date(2026, 8, 15))


def agent(result, code):
    match = next(a for a in result["agents"] if a["code"] == code)
    return match


def test_reconciliation_passes_with_zero_variance(result):
    recon = result["summary"]["reconciliation"]
    assert recon["passed"] is True
    assert recon["variance_summary"] == 0.0
    assert recon["failures"] == []


def test_known_agents_final_sale_matches_vendor_report_to_the_cent(result):
    assert agent(result, "MP120")["final_sale"] == 15000.00
    assert agent(result, "PC005")["final_sale"] == 12000.50
    assert agent(result, "ANM101")["final_sale"] == 8000.00
    assert agent(result, "MP130")["final_sale"] == 20000.00


def test_bkref_from_prior_month_lead_file_still_attributes(result):
    ml108 = agent(result, "ML108")
    assert ml108["closed"] == 1
    assert ml108["final_sale"] == 9500.25


def test_messy_variants_resolve_to_the_right_agent(result):
    # PCOO5 -> PC005 (production report + lead csv)
    assert agent(result, "PC005")["submissions"] == 6
    # Mp120 handled by case-only normalisation (no alias needed)
    assert agent(result, "MP120")["submissions"] == 10
    # 6038 -> ANM101 (vicidial ID)
    assert agent(result, "ANM101")["submissions"] == 3
    assert agent(result, "ANM101")["contacted"] == 1
    # Gary October -> MP130 (full name)
    assert agent(result, "MP130")["submissions"] == 4
    assert agent(result, "MP130")["closed"] == 1


def test_zero_value_policy_excluded_from_closed_count(result):
    pc014 = agent(result, "PC014")
    assert pc014["contacted"] == 1        # it was contacted...
    assert pc014["closed"] == 0           # ...but the R0.00 policy doesn't count as Closed
    assert pc014["final_sale"] == 0.0


def test_excluded_zero_value_policy_logged_for_managers_only(result):
    excluded = result["summary"]["excluded_zero_value_policies"]
    refs = {row["bk_Ref"] for row in excluded}
    assert "REF-1003" in refs
    # and it must never appear in any agent's numbers (already covered above),
    # nor should the agent view even receive this list — that's a frontend contract,
    # enforced here by keeping it exclusively under summary (manager) output.
    assert "excluded_zero_value_policies" not in result["agents"][0]


def test_cancellations_reinstatements_and_quotes_tabs_are_never_used(result):
    # if these leaked in, MP120's contacted/closed count (Cancellations/Reinstatements
    # fixtures both reference REF-1001) would be inflated beyond the Contacts/Gross Sales tabs
    mp120 = agent(result, "MP120")
    assert mp120["contacted"] == 1
    assert mp120["closed"] == 1


def test_unresolvable_codes_and_unattributed_refs_go_to_unassigned_bucket(result):
    unassigned = result["summary"]["unassigned"]
    assert unassigned["contacted"] == 2          # REF-9999 (bad code) + REF-0000 (no CSV match)
    assert unassigned["closed"] == 2
    assert unassigned["final_sale"] == 8000.00   # 5000 + 3000
    assert "ZZ999" in unassigned["unresolved_codes_seen"]
    assert "UNKNOWNCODE" in unassigned["unresolved_codes_seen"]
    assert "REF-0000" in unassigned["unattributed_bk_refs"]
    assert UNASSIGNED not in {a["code"] for a in result["agents"]}


def test_successful_plus_failed_equals_submissions_for_every_agent(result):
    for a in result["agents"]:
        assert a["successful"] + a["failed"] == a["submissions"], a["code"]


def test_all_teams_and_agents_from_tracker_are_present(result):
    codes = {a["code"] for a in result["agents"]}
    assert codes == {"MP120", "PC005", "PC014", "PC020", "PC004", "ML108", "ANM101", "IG021", "MP130"}
    teams = {a["team"] for a in result["agents"]}
    assert teams == {"Team A", "Team B"}


def test_trend_covers_both_dated_production_reports_in_month(result):
    mp120 = agent(result, "MP120")
    dates = {point["date"] for point in mp120["trend"]}
    assert dates == {"2026-08-14", "2026-08-15"}


def test_agent_record_has_exactly_the_seven_metrics_plus_identity(result):
    a = agent(result, "MP120")
    expected_keys = {
        "code", "name", "surname", "team",
        "submissions", "successful", "failed", "contacted", "quoted", "closed", "final_sale",
        "trend",
    }
    assert set(a.keys()) == expected_keys


def test_reconciliation_error_is_loud_when_totals_are_broken(tmp_path, monkeypatch):
    import shutil
    import pandas as pd
    from build import ReconciliationError

    broken_dir = tmp_path / "input"
    shutil.copytree(INPUT_DIR, broken_dir)

    # corrupt the TOTAL row in the latest Production Report so it disagrees with the data rows
    path = broken_dir / "Production_Report_2026-08-15.xlsx"
    sheets = pd.read_excel(path, sheet_name=None)
    sheets["Agent Activity"].loc[sheets["Agent Activity"]["Agent"] == "TOTAL", "Submissions"] = 99999
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    with pytest.raises(ReconciliationError):
        assemble(broken_dir, broken_dir / "YesUCan_Agent_Tracker.xlsx", ALIASES, as_of=date(2026, 8, 15))
