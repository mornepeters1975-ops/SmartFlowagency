"""Generates the synthetic input/ fixture files used by the pytest suite.

Run directly (`python tests/fixtures/make_fixtures.py`) to (re)write the
fixture files under tests/fixtures/input/. Mirrors the real file schemas
described in CLAUDE.md but with invented, non-sensitive data.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

FIXTURES_DIR = Path(__file__).parent
INPUT_DIR = FIXTURES_DIR / "input"


def write_tracker() -> None:
    team_a = pd.DataFrame([
        {"Name": "Michael", "Surname": "Peters", "Agent number": "MP120", "Vicidial User": ""},
        {"Name": "Priya", "Surname": "Chetty", "Agent number": "PC005", "Vicidial User": ""},
        {"Name": "Paul", "Surname": "Cele", "Agent number": "PC014", "Vicidial User": ""},
        {"Name": "Anna", "Surname": "Moyo", "Agent number": "ANM101", "Vicidial User": "6038"},
        {"Name": "Gary", "Surname": "October", "Agent number": "MP130", "Vicidial User": ""},
    ])
    team_b = pd.DataFrame([
        {"Name": "Prudence", "Surname": "Coetzee", "Agent number": "PC020", "Vicidial User": ""},
        {"Name": "Percy", "Surname": "Cele", "Agent number": "PC004", "Vicidial User": ""},
        {"Name": "Mandla", "Surname": "Luthuli", "Agent number": "ML108", "Vicidial User": ""},
        {"Name": "Ivan", "Surname": "George", "Agent number": "IG021", "Vicidial User": "5024"},
    ])
    path = INPUT_DIR / "YesUCan_Agent_Tracker.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        team_a.to_excel(writer, sheet_name="Team A", index=False)
        team_b.to_excel(writer, sheet_name="Team B", index=False)


# raw (messy) Agent column value -> (Submissions, Successful, Failed, Quoted, Sold, Gross SPV)
PRODUCTION_ROWS_LATEST = [
    ("MP120",         10, 8, 2, 5, 3, 0),
    ("PCOO5",          6, 5, 1, 4, 2, 0),   # letter-O-for-zero -> PC005
    ("PCC014",         8, 6, 2, 5, 2, 0),   # doubled letter -> PC014
    ("PCC020",         4, 3, 1, 2, 1, 0),   # doubled letter -> PC020
    ("PC04",           5, 4, 1, 3, 2, 0),   # dropped zero -> PC004
    ("MLL108",         7, 5, 2, 4, 2, 0),   # doubled letter typo -> ML108
    ("6038",           3, 3, 0, 2, 1, 0),   # Vicidial ID -> ANM101
    ("5024",           2, 2, 0, 1, 1, 0),   # Vicidial ID -> IG021
    ("Gary October",   4, 4, 0, 3, 2, 0),   # full name -> MP130
    ("ZZ999",          1, 1, 0, 0, 0, 0),   # unresolvable -> Unassigned
]

PRODUCTION_ROWS_PRIOR_DAY = [
    ("MP120", 4, 3, 1, 2, 1, 0),
    ("PC005", 2, 2, 0, 1, 1, 0),
    ("PC014", 3, 2, 1, 2, 1, 0),
]


def _write_production_report(path: Path, rows: list[tuple]) -> None:
    cols = ["Agent", "Submissions", "Successful", "Failed", "Quoted", "Sold", "Gross SPV (Ex VAT)"]
    df = pd.DataFrame(rows, columns=cols)
    total = {
        "Agent": "TOTAL",
        "Submissions": df["Submissions"].sum(),
        "Successful": df["Successful"].sum(),
        "Failed": df["Failed"].sum(),
        "Quoted": df["Quoted"].sum(),
        "Sold": df["Sold"].sum(),
        "Gross SPV (Ex VAT)": df["Gross SPV (Ex VAT)"].sum(),
    }
    agent_activity = pd.concat([df, pd.DataFrame([total])], ignore_index=True)

    all_submissions = pd.DataFrame({
        "Reference": [f"REF-{i}" for i in range(len(rows))],
        "Agent": [r[0] for r in rows],
    })

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        agent_activity.to_excel(writer, sheet_name="Agent Activity", index=False)
        all_submissions.to_excel(writer, sheet_name="All Submissions", index=False)


def write_production_reports() -> None:
    _write_production_report(INPUT_DIR / "Production_Report_2026-08-15.xlsx", PRODUCTION_ROWS_LATEST)
    _write_production_report(INPUT_DIR / "Production_Report_2026-08-14.xlsx", PRODUCTION_ROWS_PRIOR_DAY)


def write_lead_csvs() -> None:
    current = pd.DataFrame([
        {"Date/Time": "2026-08-15 09:00", "Mobile": "0821110001", "Submitted By": "MP120",
         "Reference": "REF-1001", "KP Success": "Y", "Sent At": "2026-08-15 09:05"},
        {"Date/Time": "2026-08-15 09:10", "Mobile": "0821110002", "Submitted By": "PCOO5",
         "Reference": "REF-1002", "KP Success": "Y", "Sent At": "2026-08-15 09:15"},
        {"Date/Time": "2026-08-15 09:20", "Mobile": "0821110003", "Submitted By": "PCC014",
         "Reference": "REF-1003", "KP Success": "Y", "Sent At": "2026-08-15 09:25"},
        {"Date/Time": "2026-08-15 09:30", "Mobile": "0821110004", "Submitted By": "6038",
         "Reference": "REF-1004", "KP Success": "Y", "Sent At": "2026-08-15 09:35"},
        {"Date/Time": "2026-08-15 09:40", "Mobile": "0821110005", "Submitted By": "Gary October",
         "Reference": "REF-1005", "KP Success": "Y", "Sent At": "2026-08-15 09:45"},
        {"Date/Time": "2026-08-15 09:50", "Mobile": "0821110006", "Submitted By": "UNKNOWNCODE",
         "Reference": "REF-9999", "KP Success": "Y", "Sent At": "2026-08-15 09:55"},
    ])
    current.to_csv(INPUT_DIR / "kp-leads-2026-08-15.csv", index=False)

    prior_month = pd.DataFrame([
        {"Date/Time": "2026-07-20 09:00", "Mobile": "0821110007", "Submitted By": "ML10P8",
         "Reference": "REF-2001", "KP Success": "Y", "Sent At": "2026-07-20 09:05"},
    ])
    prior_month.to_csv(INPUT_DIR / "kp-leads-2026-07-20.csv", index=False)


def write_vendor_report() -> None:
    path = INPUT_DIR / "Marketing_KPI_Vendor_Report_-_Detail.xlsx"

    contact_refs = ["REF-1001", "REF-1002", "REF-1003", "REF-1004", "REF-1005", "REF-2001", "REF-9999", "REF-0000"]
    contacts = pd.DataFrame({
        "Channel": ["Direct"] * len(contact_refs),
        "bk_Ref": contact_refs,
        "Contact Date": ["2026-08-15"] * len(contact_refs),
    })
    contacts_total = pd.DataFrame([{"Channel": "Total", "bk_Ref": None, "Contact Date": None}])
    contacts = pd.concat([contacts, contacts_total], ignore_index=True)

    sales_rows = [
        ("REF-1001", 15000.00),
        ("REF-1002", 12000.50),
        ("REF-1003", 0.00),      # zero-value "Spoken Client Request" -> excluded
        ("REF-1004", 8000.00),
        ("REF-1005", 20000.00),
        ("REF-2001", 9500.25),   # prior-month bk_Ref
        ("REF-9999", 5000.00),   # unresolved agent code -> Unassigned
        ("REF-0000", 3000.00),   # no matching lead CSV row -> unattributed -> Unassigned
    ]
    sales = pd.DataFrame({
        "Channel": ["Direct"] * len(sales_rows),
        "bk_Ref": [r[0] for r in sales_rows],
        "Gross SPV (Ex VAT)": [r[1] for r in sales_rows],
    })
    sales_total_value = sum(v for _, v in sales_rows)
    sales_total = pd.DataFrame([{"Channel": "Total", "bk_Ref": None, "Gross SPV (Ex VAT)": sales_total_value}])
    sales = pd.concat([sales, sales_total], ignore_index=True)

    # out-of-scope tabs — present in the real file, must never be read
    cancellations = pd.DataFrame({"Channel": ["Direct"], "bk_Ref": ["REF-1001"], "Cancel Reason": ["n/a"]})
    reinstatements = pd.DataFrame({"Channel": ["Direct"], "bk_Ref": ["REF-1001"], "Reinstate Date": ["n/a"]})
    quotes = pd.DataFrame({"Channel": ["Direct"], "bk_Ref": ["REF-1001"], "Quote Value": [1234]})

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # two blank/title rows above the header, to match header=2 (row 3) in the real file
        blank = pd.DataFrame()
        for sheet_name, df in [
            ("Contacts", contacts), ("Gross Sales", sales),
            ("Cancellations", cancellations), ("Reinstatements", reinstatements), ("Quotes", quotes),
        ]:
            blank.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
            df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=2)


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_tracker()
    write_production_reports()
    write_lead_csvs()
    write_vendor_report()
    print(f"Fixtures written to {INPUT_DIR}")


if __name__ == "__main__":
    main()
