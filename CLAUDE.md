# Agent Performance Dashboard — Build Spec

Paste this whole file as your first message to Claude Code. Save it in the repo as
`CLAUDE.md` so it stays in context for every future session.

---

## What we're building

A dashboard where a call centre agent logs in and sees **their own** performance for the
current month, from data we already export daily. Managers see all agents; agents see only
themselves.

Seven metrics per agent, and nothing else:

| Metric | Meaning |
|---|---|
| Submissions | Leads the agent submitted through the new form |
| Successful | Submissions the vendor accepted |
| Failed | Submissions the vendor rejected |
| Contacted | Leads the vendor actually made contact on |
| Quoted | Leads that reached a quote |
| Closed | Policies written |
| Final Sale | Rand value of those policies |

**Explicitly out of scope: clawbacks, cancellations and reinstatements.** The vendor report
has tabs for these. Ignore them entirely. Do not net them off, do not display them, do not
add a toggle for them later without asking.

---

## Data sources

Three files are exported daily and dropped in an `input/` folder. None of them is a database;
all parsing is from file.

**1. Production Report** — `Production_Report_YYYY-MM-DD.xlsx`
- Sheet `Agent Activity`: one row per agent code, columns `Submissions`, `Successful`,
  `Failed`, `Quoted`, `Sold`, `Gross SPV (Ex VAT)`.
- Sheet `All Submissions`: one row per lead.
- Source of truth for **Submissions, Successful, Failed, Quoted**.

**2. Lead export** — `kp-leads-YYYY-MM-DD.csv`
- Columns include `Date/Time`, `Mobile`, `Submitted By`, `Reference`, `KP Success`, `Sent At`.
- `Reference` is the **bk_Ref** — the join key to the vendor report.
- `Submitted By` is the agent code as typed by the agent. It is messy. See below.

**3. Vendor Report (Detail)** — `Marketing_KPI_Vendor_Report_-_Detail.xlsx`
- Header row is row 3 (`header=2` in pandas). Row 4 is a `Total` row — drop rows where
  `Channel == 'Total'`.
- Tab `Contacts` → source of **Contacted**
- Tab `Gross Sales` → source of **Closed** and **Final Sale**
- Tabs `Cancellations`, `Reinstatements`, `Quotes` → **do not use**
- Every tab carries a `bk_Ref` column.

**4. Agent Tracker** — `YesUCan_Agent_Tracker.xlsx`
- One sheet per team. Columns `Name`, `Surname`, `Agent number`, `Vicidial User`.
- **Authoritative roster.** Agent code → real name → team comes from here and nowhere else.

---

## Attribution rules — get these wrong and the numbers are wrong

These were learned the hard way. Treat them as hard requirements, not suggestions.

**bk_Ref exact string match is the only permitted attribution method.**
Never match on phone number. Never match on customer name. Never fuzzy-match. If a bk_Ref
does not match, it stays unattributed and is reported as such.

**Never use the Production Report's `Reference` column as a join key.** It is stored as a
float and the last 2–3 digits are corrupted. Join from the CSV's `Reference` column only.

**bk_Refs may originate in a prior month's lead file.** A lead worked in July can become an
August policy. Build the bk_Ref → agent-code lookup across *all* lead CSVs present in
`input/`, most recent first, then fall back to older ones. Do not assume the current month's
file contains every ref.

**Agent codes must be normalised before lookup.** Real variants seen in production:

| Seen | Means | Pattern |
|---|---|---|
| `Mp120`, `MP12O` | `MP120` | case, letter-O for zero |
| `PCOO5` | `PC005` | letter-O for zero |
| `PCC014`, `PCC020` | `PC014`, `PC020` | doubled letter |
| `PC04` | `PC004` | dropped zero |
| `MLL108`, `ML10P8` | `ML108` | typo |
| `6038`, `5024` | `ANM101`, `IG021` | Vicidial ID used instead of code |
| `Gary October` | `MP130` | full name instead of code |
| `PC014 FUNERAL POLICY OR LIFE COVER` | `PC014` | code plus free text |

Implement as: uppercase → strip whitespace/tabs → check an explicit alias map → check the
name-to-code map → check the Vicidial-ID map → then exact tracker lookup. Keep the alias map
in a separate `aliases.json` so it can be extended without touching code.

**Codes that resolve to nothing go to an `Unassigned` bucket.** Never guess. Never silently
drop. Surface them in the manager view so the roster can be fixed.

**Exclude any policy with `Gross SPV (Ex VAT)` of R0.00** from Closed and Final Sale. These
occur (annotated "Spoken Client Request") and showing them creates a closed policy worth
nothing, which reads as a bug. Log them to a manager-only view, never the agent view.

---

## Reconciliation — non-negotiable

The dashboard must prove itself against source on every run:

- Sum of all agents' Submissions/Successful/Failed/Quoted **must equal** the Production
  Report `TOTAL` row.
- Sum of all agents' Final Sale **must equal** the Vendor Report Gross Sales total, less
  excluded zero-value policies.
- Successful + Failed must equal Submissions.

If any check fails, the build fails loudly with a diff. Do not round-trip silently. Show a
reconciliation banner in the manager view stating the variance, which should read R0.00.

---

## Suggested shape

Keep it boring and cheap to run. No database.

```
input/            # the daily exports get dropped here
build.py          # parses everything, writes data/agents.json + data/summary.json
data/             # generated, git-ignored
web/              # static frontend, reads the JSON
aliases.json      # agent code alias map
```

`build.py` is a single Python script (pandas + openpyxl). It ingests, normalises, reconciles,
and emits JSON. The frontend is static and reads that JSON — deployable to GitHub Pages or
Replit with no server.

Start with a CLI that prints one agent's numbers to the terminal. Get the pipeline provably
correct before writing any UI. The UI is the easy part.

---

## Agent view

- Agent identifies themselves (agent code is fine to start; add real auth later).
- Their seven numbers for the current month, large and readable.
- A conversion funnel: Submissions → Successful → Contacted → Quoted → Closed.
- Their own trend across the month.
- **Their own data only.** No other agent's figures, no team ranking, unless a manager
  explicitly enables it. Agents comparing commission-bearing numbers with each other is a
  problem you don't want to create by accident.

## Manager view

- All agents, sortable, filterable by team.
- The reconciliation banner.
- The Unassigned bucket and any excluded zero-value policies.

---

## Build order

1. Parse the Agent Tracker into a roster. Prove every team and agent loads.
2. Build the agent-code normaliser. Unit-test it against the variant table above.
3. Build the bk_Ref lookup across all lead CSVs.
4. Join the vendor tabs. Assert 100% of Gross Sales rows attribute to an agent.
5. Assemble per-agent metrics. Run the reconciliation checks.
6. Emit JSON.
7. Only now, build the UI.

## Acceptance tests

- A known agent's Final Sale matches the vendor report to the cent.
- A bk_Ref originating in a prior month's lead file still attributes correctly.
- `PCOO5`, `Mp120`, `6038` and `Gary October` all resolve to the right agent.
- A zero-value policy does not appear in any agent's Closed count.
- Cancellations and reinstatements appear nowhere in the output.
- Totals tie to both source reports; reconciliation reports R0.00 variance.
