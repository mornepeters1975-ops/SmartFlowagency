#!/usr/bin/env python3
"""Agent Performance Dashboard build pipeline.

Ingests the daily exports dropped in input/, normalises agent codes,
attributes vendor activity via bk_Ref, reconciles against source totals,
and writes data/agents.json + data/summary.json for the static frontend.

See CLAUDE.md for the full spec and the rules behind every decision here.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

UNASSIGNED = "Unassigned"

CODE_PATTERN = re.compile(r"^[A-Z]{2,5}\d{2,4}$")
LEADING_CODE_TOKEN = re.compile(r"^([A-Z0-9]{3,8})\b")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ReconciliationError(RuntimeError):
    """Raised when a build-time reconciliation check fails. Fails loudly."""


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

def load_aliases(path: Path) -> dict:
    if not path.exists():
        return {"code_aliases": {}, "name_aliases": {}, "vicidial_aliases": {}}
    raw = json.loads(path.read_text())
    return {
        "code_aliases": {k.upper().strip(): v.upper().strip() for k, v in raw.get("code_aliases", {}).items()},
        "name_aliases": {k.upper().strip(): v.upper().strip() for k, v in raw.get("name_aliases", {}).items()},
        "vicidial_aliases": {k.upper().strip(): v.upper().strip() for k, v in raw.get("vicidial_aliases", {}).items()},
    }


# ---------------------------------------------------------------------------
# Roster (Agent Tracker) — the only source of agent code -> name/team
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    code: str
    name: str
    surname: str
    team: str
    vicidial_user: Optional[str]

    @property
    def full_name(self) -> str:
        return f"{self.name} {self.surname}".strip()


def load_roster(path: Path, sheet_filter: Optional[set[str]] = None,
                 team_label: Optional[str] = None) -> dict[str, Agent]:
    """Parse the Agent Tracker workbook: one sheet per team.

    Some trackers are shared across multiple client companies (one sheet per
    company/campaign-leader team). Pass sheet_filter (case-insensitive sheet
    names) to load only specific teams, and team_label to relabel them —
    e.g. the tracker calls a sheet "Morne Peters" but the business is
    "SmartFlow Agency".
    """
    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    roster: dict[str, Agent] = {}
    wanted = {s.strip().lower() for s in sheet_filter} if sheet_filter else None
    for team, df in sheets.items():
        if wanted is not None and team.strip().lower() not in wanted:
            continue
        df = df.rename(columns=lambda c: str(c).strip())
        required = {"Name", "Surname", "Agent number"}
        if not required.issubset(df.columns):
            continue  # not a team roster sheet (e.g. a notes/instructions tab)
        for _, row in df.iterrows():
            code = _clean_str(row.get("Agent number"))
            if not code:
                continue
            code = code.upper()
            vicidial = _clean_str(row.get("Vicidial User"))
            roster[code] = Agent(
                code=code,
                name=_clean_str(row.get("Name")) or "",
                surname=_clean_str(row.get("Surname")) or "",
                team=team_label or team.strip(),
                vicidial_user=vicidial.upper() if vicidial else None,
            )
    return roster


def _clean_str(value) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


def build_name_map(roster: dict[str, Agent]) -> dict[str, str]:
    return {agent.full_name.upper(): code for code, agent in roster.items() if agent.full_name.strip()}


def build_vicidial_map(roster: dict[str, Agent]) -> dict[str, str]:
    return {agent.vicidial_user: code for code, agent in roster.items() if agent.vicidial_user}


# ---------------------------------------------------------------------------
# Agent-code normalisation
# ---------------------------------------------------------------------------

@dataclass
class Normaliser:
    roster_codes: set[str]
    code_aliases: dict[str, str]
    name_map: dict[str, str]
    vicidial_map: dict[str, str]
    unresolved: list[str] = field(default_factory=list)

    def resolve(self, raw) -> str:
        cleaned = self._clean(raw)
        if cleaned is None:
            self.unresolved.append(str(raw))
            return UNASSIGNED

        code = self._try_resolve(cleaned)
        if code:
            return code

        # code plus free text, e.g. "PC014 FUNERAL POLICY OR LIFE COVER"
        token_match = LEADING_CODE_TOKEN.match(cleaned)
        if token_match:
            token = token_match.group(1)
            code = self._try_resolve(token)
            if code:
                return code

        # generic letter-O-for-zero fallback beyond the explicit alias map
        o_fixed = cleaned.replace("O", "0")
        code = self._try_resolve(o_fixed)
        if code:
            return code

        self.unresolved.append(str(raw))
        return UNASSIGNED

    def _try_resolve(self, s: str) -> Optional[str]:
        if s in self.roster_codes:
            return s
        if s in self.code_aliases:
            resolved = self.code_aliases[s]
            if resolved in self.roster_codes:
                return resolved
        if s in self.name_map:
            return self.name_map[s]
        if s in self.vicidial_map:
            return self.vicidial_map[s]
        return None

    @staticmethod
    def _clean(raw) -> Optional[str]:
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return None
        s = str(raw).upper().strip()
        s = re.sub(r"\s+", " ", s)
        return s or None


# ---------------------------------------------------------------------------
# Production Report — Submissions / Successful / Failed / Quoted
# ---------------------------------------------------------------------------

AGENT_CODE_COLUMN_CANDIDATES = ["Agent", "Agent Code", "Agent Number", "Code"]
OFFICE_COLUMN_CANDIDATES = ["Office", "Company", "Client"]


def _find_agent_column(df: pd.DataFrame) -> str:
    for candidate in AGENT_CODE_COLUMN_CANDIDATES:
        if candidate in df.columns:
            return candidate
    raise ReconciliationError(
        f"Could not find an agent-code column in Agent Activity sheet. "
        f"Looked for {AGENT_CODE_COLUMN_CANDIDATES}, found columns: {list(df.columns)}"
    )


def _office_mask(df: pd.DataFrame, office_filter: Optional[str]) -> pd.Series:
    """True = keep. Some source files are shared across multiple client
    companies via an Office/Company column. When office_filter is set, keep
    rows tagged for that company plus rows with no company tag at all (those
    still get a chance to resolve through the roster); drop rows explicitly
    tagged for a different company. No-op (keep everything) when there's no
    such column or no filter was requested — preserves single-tenant use."""
    if not office_filter:
        return pd.Series(True, index=df.index)
    for candidate in OFFICE_COLUMN_CANDIDATES:
        if candidate in df.columns:
            office = df[candidate].astype(str).str.strip().str.lower()
            target = office_filter.strip().lower()
            return (office == target) | (office == "") | (office == "nan")
    return pd.Series(True, index=df.index)


def parse_production_report(path: Path, normaliser: Normaliser,
                             office_filter: Optional[str] = None) -> tuple[pd.DataFrame, dict[str, float]]:
    """Returns (per-agent metrics df, totals row to reconcile against).

    Without office_filter, totals come from the report's own TOTAL row (an
    independent check against source). With office_filter, the report's
    TOTAL row covers every company sharing the file, not just this one, so
    the reconciliation target is the sum of the scoped rows themselves."""
    df = pd.read_excel(path, sheet_name="Agent Activity")
    df = df.rename(columns=lambda c: str(c).strip())
    agent_col = _find_agent_column(df)

    is_total = df[agent_col].astype(str).str.strip().str.upper() == "TOTAL"
    totals_rows = df[is_total]
    data_rows = df[~is_total].copy()
    data_rows = data_rows[_office_mask(data_rows, office_filter)]

    metric_cols = ["Submissions", "Successful", "Failed", "Quoted"]
    for col in metric_cols:
        if col not in data_rows.columns:
            raise ReconciliationError(f"Agent Activity sheet in {path.name} is missing column '{col}'")
        data_rows[col] = pd.to_numeric(data_rows[col], errors="coerce").fillna(0)

    data_rows["agent_code"] = data_rows[agent_col].apply(normaliser.resolve)
    per_agent = data_rows.groupby("agent_code")[metric_cols].sum()

    if office_filter:
        report_totals = {col: float(data_rows[col].sum()) for col in metric_cols}
    elif len(totals_rows):
        report_totals = {col: float(pd.to_numeric(totals_rows[col], errors="coerce").fillna(0).sum()) for col in metric_cols}
    else:
        report_totals = {col: float(data_rows[col].sum()) for col in metric_cols}

    return per_agent, report_totals


# ---------------------------------------------------------------------------
# Lead CSVs — bk_Ref -> agent code lookup, most recent file wins
# ---------------------------------------------------------------------------

LEAD_FILE_RE = re.compile(r"kp-leads-(\d{4}-\d{2}-\d{2})\.csv$", re.IGNORECASE)


def _lead_files_most_recent_first(input_dir: Path) -> list[Path]:
    files = []
    for p in sorted(input_dir.glob("kp-leads-*.csv")):
        m = LEAD_FILE_RE.search(p.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        files.append((file_date, p))
    files.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in files]


def build_bkref_lookup(input_dir: Path, normaliser: Normaliser,
                        office_filter: Optional[str] = None) -> dict[str, str]:
    """bk_Ref (Reference) -> normalised agent code. Most recent lead file wins;
    older files only fill in refs not already seen. Rows explicitly tagged
    for a different company (see _office_mask) are skipped entirely, so
    their bk_Refs never enter the lookup at all — a later Vendor Report row
    for one of those refs then reads as out-of-scope, not unattributed."""
    lookup: dict[str, str] = {}
    for path in _lead_files_most_recent_first(input_dir):
        df = pd.read_csv(path, dtype=str)
        df = df.rename(columns=lambda c: str(c).strip())
        if "Reference" not in df.columns or "Submitted By" not in df.columns:
            continue
        df = df[_office_mask(df, office_filter)]
        for _, row in df.iterrows():
            ref = _clean_str(row.get("Reference"))
            if not ref or ref in lookup:
                continue
            lookup[ref] = normaliser.resolve(row.get("Submitted By"))
    return lookup


# ---------------------------------------------------------------------------
# Vendor Report — Contacted / Closed / Final Sale, attributed via bk_Ref
# ---------------------------------------------------------------------------

VENDOR_HEADER_ROW = 2  # row 3 in the file (0-indexed) -> pandas header=2


def _read_vendor_tab(path: Path, sheet_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (data_rows, total_rows) — the tab's own Total row(s) are the
    ground truth for reconciliation, kept separate rather than folded in."""
    df = pd.read_excel(path, sheet_name=sheet_name, header=VENDOR_HEADER_ROW)
    df = df.rename(columns=lambda c: str(c).strip())
    if "Channel" not in df.columns:
        return df, df.iloc[0:0]
    is_total = df["Channel"].astype(str).str.strip().str.upper() == "TOTAL"
    return df[~is_total].copy(), df[is_total].copy()


@dataclass
class VendorResult:
    contacted: pd.Series          # agent_code -> count
    closed: pd.Series             # agent_code -> count
    final_sale: pd.Series         # agent_code -> rand sum
    report_gross_sales_total: float  # the Gross Sales tab's own Total row, ground truth for reconciliation
    unattributed_bkrefs: list[str]
    excluded_zero_value: list[dict]


OUT_OF_SCOPE = "_OutOfScope"


def parse_vendor_report(path: Path, bkref_lookup: dict[str, str],
                         strict_scope: bool = False) -> VendorResult:
    """strict_scope=True means bkref_lookup was itself built from a single
    company's leads (see build_bkref_lookup's office_filter): a bk_Ref that
    doesn't resolve almost certainly belongs to a different company sharing
    this file, not a genuine attribution problem — so it's dropped silently
    instead of being logged as unattributed / dumped into Unassigned."""
    contacts, _ = _read_vendor_tab(path, "Contacts")
    sales, sales_total_rows = _read_vendor_tab(path, "Gross Sales")

    if strict_scope:
        report_gross_sales_total = None  # the file's Total row spans every company — not our ground truth
    elif len(sales_total_rows):
        report_gross_sales_total = float(
            pd.to_numeric(sales_total_rows["Gross SPV (Ex VAT)"], errors="coerce").fillna(0).sum()
        )
    else:
        report_gross_sales_total = None  # no Total row in the source — can't reconcile against it

    unattributed: list[str] = []

    def attribute(df: pd.DataFrame) -> pd.Series:
        codes = []
        for ref in df["bk_Ref"]:
            ref = _clean_str(ref)
            code = bkref_lookup.get(ref) if ref else None
            if not code:
                if strict_scope:
                    code = OUT_OF_SCOPE
                else:
                    if ref:
                        unattributed.append(ref)
                    code = UNASSIGNED
            codes.append(code)
        return pd.Series(codes, index=df.index)

    contacts = contacts.copy()
    contacts["agent_code"] = attribute(contacts)
    contacts = contacts[contacts["agent_code"] != OUT_OF_SCOPE]
    contacted = contacts.groupby("agent_code").size()

    sales = sales.copy()
    sales["agent_code"] = attribute(sales)
    sales = sales[sales["agent_code"] != OUT_OF_SCOPE]
    sales["Gross SPV (Ex VAT)"] = pd.to_numeric(sales["Gross SPV (Ex VAT)"], errors="coerce").fillna(0)

    is_zero = sales["Gross SPV (Ex VAT)"] == 0
    excluded_zero_value = sales[is_zero][["bk_Ref", "agent_code"]].to_dict("records")

    priced_sales = sales[~is_zero]
    closed = priced_sales.groupby("agent_code").size()
    final_sale = priced_sales.groupby("agent_code")["Gross SPV (Ex VAT)"].sum()

    if report_gross_sales_total is None:
        report_gross_sales_total = float(sales["Gross SPV (Ex VAT)"].sum())

    return VendorResult(
        contacted=contacted,
        closed=closed,
        final_sale=final_sale,
        report_gross_sales_total=report_gross_sales_total,
        unattributed_bkrefs=unattributed,
        excluded_zero_value=excluded_zero_value,
    )


# ---------------------------------------------------------------------------
# Production report discovery (dated files, for current-month trend)
# ---------------------------------------------------------------------------

PRODUCTION_FILE_RE = re.compile(r"Production_Report_(\d{4}-\d{2}-\d{2})\.xlsx$", re.IGNORECASE)


def _production_files_in_month(input_dir: Path, year: int, month: int) -> list[tuple[date, Path]]:
    out = []
    for p in sorted(input_dir.glob("Production_Report_*.xlsx")):
        m = PRODUCTION_FILE_RE.search(p.name)
        if not m:
            continue
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        if d.year == year and d.month == month:
            out.append((d, p))
    out.sort(key=lambda t: t[0])
    return out


def _latest_production_file(input_dir: Path) -> Path:
    files = sorted(input_dir.glob("Production_Report_*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No Production_Report_*.xlsx files found in {input_dir}")
    dated = [(datetime.strptime(PRODUCTION_FILE_RE.search(p.name).group(1), "%Y-%m-%d").date(), p)
             for p in files if PRODUCTION_FILE_RE.search(p.name)]
    dated.sort(key=lambda t: t[0])
    return dated[-1][1]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble(input_dir: Path, tracker_path: Path, aliases_path: Path,
             as_of: Optional[date] = None, tracker_sheets: Optional[set[str]] = None,
             team_label: Optional[str] = None, office_filter: Optional[str] = None) -> dict:
    """tracker_sheets/team_label/office_filter scope a multi-tenant source
    (one Agent Tracker / Production Report / lead export shared across
    several client companies) down to a single company: tracker_sheets picks
    which tracker sheet(s) are that company's roster, team_label relabels
    them for display, and office_filter matches the Office/Company column
    where the Production Report and lead CSVs carry one."""
    as_of = as_of or date.today()

    aliases = load_aliases(aliases_path)
    roster = load_roster(tracker_path, sheet_filter=tracker_sheets, team_label=team_label)
    if not roster:
        raise ReconciliationError(f"Agent Tracker at {tracker_path} produced an empty roster")

    name_map = build_name_map(roster)
    vicidial_map = build_vicidial_map(roster)
    roster_codes = set(roster.keys())

    normaliser = Normaliser(
        roster_codes=roster_codes,
        code_aliases=aliases["code_aliases"],
        name_map={**name_map, **aliases["name_aliases"]},
        vicidial_map={**vicidial_map, **aliases["vicidial_aliases"]},
    )

    production_path = _latest_production_file(input_dir)
    per_agent_production, production_totals = parse_production_report(production_path, normaliser, office_filter)

    bkref_lookup = build_bkref_lookup(input_dir, normaliser, office_filter)
    vendor_path = input_dir / "Marketing_KPI_Vendor_Report_-_Detail.xlsx"
    if not vendor_path.exists():
        raise FileNotFoundError(f"Vendor report not found at {vendor_path}")
    vendor = parse_vendor_report(vendor_path, bkref_lookup, strict_scope=bool(office_filter))

    # trend across the month, from every dated Production Report present
    month_files = _production_files_in_month(input_dir, as_of.year, as_of.month)
    trend_by_agent: dict[str, list[dict]] = {code: [] for code in roster_codes}
    trend_by_agent[UNASSIGNED] = []
    for d, path in month_files:
        per_agent, _ = parse_production_report(path, normaliser, office_filter)
        for code, row in per_agent.iterrows():
            trend_by_agent.setdefault(code, []).append({
                "date": d.isoformat(),
                "submissions": int(row["Submissions"]),
                "successful": int(row["Successful"]),
                "failed": int(row["Failed"]),
                "quoted": int(row["Quoted"]),
            })

    all_codes = set(per_agent_production.index) | set(vendor.contacted.index) | set(vendor.closed.index) | roster_codes
    all_codes.discard(UNASSIGNED)

    agents_out = []
    for code in sorted(all_codes):
        agent = roster.get(code)
        prod = per_agent_production.loc[code] if code in per_agent_production.index else None
        agents_out.append({
            "code": code,
            "name": agent.name if agent else None,
            "surname": agent.surname if agent else None,
            "team": agent.team if agent else None,
            "submissions": int(prod["Submissions"]) if prod is not None else 0,
            "successful": int(prod["Successful"]) if prod is not None else 0,
            "failed": int(prod["Failed"]) if prod is not None else 0,
            "quoted": int(prod["Quoted"]) if prod is not None else 0,
            "contacted": int(vendor.contacted.get(code, 0)),
            "closed": int(vendor.closed.get(code, 0)),
            "final_sale": float(vendor.final_sale.get(code, 0.0)),
            "trend": trend_by_agent.get(code, []),
        })

    unassigned_production = per_agent_production.loc[UNASSIGNED] if UNASSIGNED in per_agent_production.index else None
    unassigned_bucket = {
        "submissions": int(unassigned_production["Submissions"]) if unassigned_production is not None else 0,
        "successful": int(unassigned_production["Successful"]) if unassigned_production is not None else 0,
        "failed": int(unassigned_production["Failed"]) if unassigned_production is not None else 0,
        "quoted": int(unassigned_production["Quoted"]) if unassigned_production is not None else 0,
        "contacted": int(vendor.contacted.get(UNASSIGNED, 0)),
        "closed": int(vendor.closed.get(UNASSIGNED, 0)),
        "final_sale": float(vendor.final_sale.get(UNASSIGNED, 0.0)),
        "unresolved_codes_seen": sorted(set(normaliser.unresolved)),
        "unattributed_bk_refs": sorted(set(vendor.unattributed_bkrefs)),
    }

    reconciliation = run_reconciliation(agents_out, production_totals, vendor, unassigned_bucket)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "as_of": as_of.isoformat(),
        "production_report_used": production_path.name,
        "vendor_report_used": vendor_path.name,
        "lead_files_used": [p.name for p in _lead_files_most_recent_first(input_dir)],
        "reconciliation": reconciliation,
        "unassigned": unassigned_bucket,
        "excluded_zero_value_policies": vendor.excluded_zero_value,
        "teams": sorted({a.team for a in roster.values()}),
    }

    return {"agents": agents_out, "summary": summary, "_normaliser": normaliser}


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def run_reconciliation(agents_out: list[dict], production_totals: dict[str, float],
                        vendor: VendorResult, unassigned_bucket: dict) -> dict:
    checks = []
    failures = []

    def check(name: str, expected: float, actual: float, tolerance: float = 0.01):
        variance = round(actual - expected, 2)
        ok = abs(variance) <= tolerance
        checks.append({"check": name, "expected": expected, "actual": actual, "variance": variance, "passed": ok})
        if not ok:
            failures.append(f"{name}: expected {expected}, got {actual} (variance {variance})")

    for metric, key in [("Submissions", "submissions"), ("Successful", "successful"),
                         ("Failed", "failed"), ("Quoted", "quoted")]:
        total = sum(a[key] for a in agents_out) + unassigned_bucket[key]
        check(f"Sum of agents' {metric} vs Production Report TOTAL", production_totals.get(metric, 0.0), total)

    total_final_sale = sum(a["final_sale"] for a in agents_out) + unassigned_bucket["final_sale"]
    check("Sum of agents' Final Sale vs Vendor Gross Sales Total row", vendor.report_gross_sales_total, total_final_sale)

    for a in agents_out:
        if a["successful"] + a["failed"] != a["submissions"]:
            failures.append(
                f"Agent {a['code']}: Successful ({a['successful']}) + Failed ({a['failed']}) "
                f"!= Submissions ({a['submissions']})"
            )
    su = unassigned_bucket
    if su["successful"] + su["failed"] != su["submissions"]:
        failures.append(
            f"Unassigned bucket: Successful ({su['successful']}) + Failed ({su['failed']}) "
            f"!= Submissions ({su['submissions']})"
        )

    passed = not failures
    variance_total = round(sum(c["variance"] for c in checks), 2)
    result = {"passed": passed, "checks": checks, "failures": failures, "variance_summary": variance_total}
    if not passed:
        diff = "\n".join(failures)
        raise ReconciliationError(f"Reconciliation failed:\n{diff}")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_agent(result: dict, code: str) -> None:
    resolved = result["_normaliser"].resolve(code)
    agent = next((a for a in result["agents"] if a["code"] == resolved), None)
    if agent is None:
        print(f"No such agent: {code}", file=sys.stderr)
        sys.exit(1)
    print(f"{agent['code']} — {agent['name']} {agent['surname']} ({agent['team']})")
    print(f"  Submissions : {agent['submissions']}")
    print(f"  Successful  : {agent['successful']}")
    print(f"  Failed      : {agent['failed']}")
    print(f"  Contacted   : {agent['contacted']}")
    print(f"  Quoted      : {agent['quoted']}")
    print(f"  Closed      : {agent['closed']}")
    print(f"  Final Sale  : R{agent['final_sale']:,.2f}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Agent Performance Dashboard data.")
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--tracker", type=Path, default=None,
                         help="Path to YesUCan_Agent_Tracker.xlsx (default: <input-dir>/YesUCan_Agent_Tracker.xlsx)")
    parser.add_argument("--aliases", type=Path, default=Path("aliases.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    parser.add_argument("--agent", type=str, default=None, help="Print one agent's numbers to the terminal")
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD, defaults to today")
    parser.add_argument("--tracker-sheets", type=str, default=None,
                         help="Comma-separated Agent Tracker sheet name(s) to use, for a tracker shared "
                              "across multiple client companies (default: use every sheet)")
    parser.add_argument("--team-label", type=str, default=None,
                         help="Display name for the scoped team, overriding the tracker sheet name(s)")
    parser.add_argument("--office", type=str, default=None,
                         help="Office/Company value to scope the Production Report and lead CSVs to, "
                              "for sources shared across multiple client companies")
    args = parser.parse_args(argv)

    tracker_path = args.tracker or (args.input_dir / "YesUCan_Agent_Tracker.xlsx")
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else None
    tracker_sheets = {s.strip() for s in args.tracker_sheets.split(",")} if args.tracker_sheets else None

    try:
        result = assemble(args.input_dir, tracker_path, args.aliases, as_of=as_of,
                           tracker_sheets=tracker_sheets, team_label=args.team_label,
                           office_filter=args.office)
    except ReconciliationError as e:
        print(f"BUILD FAILED — reconciliation error\n{e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"BUILD FAILED — missing input\n{e}", file=sys.stderr)
        return 1

    if args.agent:
        print_agent(result, args.agent)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "agents.json").write_text(json.dumps(result["agents"], indent=2))
    (args.out_dir / "summary.json").write_text(json.dumps(result["summary"], indent=2))
    print(f"Wrote {args.out_dir / 'agents.json'} and {args.out_dir / 'summary.json'}")
    print(f"Reconciliation: PASSED (variance {result['summary']['reconciliation']['variance_summary']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
