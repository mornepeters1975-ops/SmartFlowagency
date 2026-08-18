// Shared helpers for the Agent Performance Dashboard.
// Static frontend: reads data/agents.json + data/summary.json, no backend.

const DATA_BASE = "../data/"; // web/*.html -> repo-root/data/

async function loadData() {
  const [agentsRes, summaryRes] = await Promise.all([
    fetch(DATA_BASE + "agents.json", { cache: "no-store" }),
    fetch(DATA_BASE + "summary.json", { cache: "no-store" }),
  ]);
  if (!agentsRes.ok || !summaryRes.ok) {
    throw new Error("Could not load data/agents.json and data/summary.json. Run build.py first.");
  }
  return { agents: await agentsRes.json(), summary: await summaryRes.json() };
}

function formatRand(value) {
  return "R" + Number(value || 0).toLocaleString("en-ZA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatInt(value) {
  return Number(value || 0).toLocaleString("en-ZA");
}

// Minimal, dependency-free normalisation for the login box: uppercase + trim only.
// Full alias/name/vicidial resolution happens once, server-side, in build.py —
// by the time an agent's own data exists in agents.json its code is already canonical.
function cleanCode(raw) {
  return String(raw || "").toUpperCase().trim();
}

function findAgent(agents, code) {
  const clean = cleanCode(code);
  return agents.find((a) => a.code === clean) || null;
}
