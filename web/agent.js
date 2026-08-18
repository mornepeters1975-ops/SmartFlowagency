// Agent view: identify by code, then render *only that agent's* numbers.

const identifyEl = document.getElementById("identify");
const dashboardEl = document.getElementById("dashboard");
const form = document.getElementById("identify-form");
const input = document.getElementById("code-input");
const errEl = document.getElementById("identify-err");

const STORAGE_KEY = "sfa_agent_code";

let DATA = null;

function funnelRow(name, value, max) {
  const pct = max > 0 ? Math.max((value / max) * 100, value > 0 ? 2 : 0) : 0;
  return `
    <div class="funnel-row">
      <div class="fname">${name}</div>
      <div class="fbar-track"><div class="fbar" style="width:${pct}%"></div></div>
      <div class="fval mono">${formatInt(value)}</div>
    </div>`;
}

function renderTrend(trend) {
  if (!trend || trend.length === 0) {
    return `<p class="small-note">No trend data yet for this month.</p>`;
  }
  const series = [
    { key: "submissions", label: "Submissions", color: "#2FB39A" },
    { key: "successful", label: "Successful", color: "#0C2925" },
    { key: "quoted", label: "Quoted", color: "#F5B301" },
  ];
  const w = 900, h = 200, padL = 36, padB = 24, padT = 10, padR = 10;
  const maxVal = Math.max(1, ...trend.flatMap((p) => series.map((s) => p[s.key] || 0)));
  const stepX = trend.length > 1 ? (w - padL - padR) / (trend.length - 1) : 0;
  const x = (i) => padL + i * stepX;
  const y = (v) => h - padB - (v / maxVal) * (h - padT - padB);

  const lines = series.map((s) => {
    const pts = trend.map((p, i) => `${x(i)},${y(p[s.key] || 0)}`).join(" ");
    const dots = trend.map((p, i) => `<circle cx="${x(i)}" cy="${y(p[s.key] || 0)}" r="3" fill="${s.color}"/>`).join("");
    return `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2"/>${dots}`;
  }).join("");

  const xLabels = trend.map((p, i) => {
    if (trend.length > 8 && i % Math.ceil(trend.length / 8) !== 0 && i !== trend.length - 1) return "";
    const d = p.date.slice(5); // MM-DD
    const anchor = i === 0 ? "start" : i === trend.length - 1 ? "end" : "middle";
    return `<text x="${x(i)}" y="${h - 6}" font-size="10" fill="#5C6B66" text-anchor="${anchor}" font-family="IBM Plex Mono, monospace">${d}</text>`;
  }).join("");

  const legend = series.map((s) => `<span><i style="background:${s.color}"></i>${s.label}</span>`).join("");

  return `
    <div class="trend-legend">${legend}</div>
    <svg class="trend" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="#EAEEEC" stroke-width="1"/>
      ${lines}
      ${xLabels}
    </svg>`;
}

function renderDashboard(agent) {
  const funnelMax = agent.submissions || 1;
  dashboardEl.innerHTML = `
    <div class="agent-head">
      <div>
        <p class="eyebrow">${agent.team || "Unassigned team"}</p>
        <h1>${agent.name ? agent.name + " " + agent.surname : agent.code} <span class="mono" style="font-size:16px;color:var(--muted)">(${agent.code})</span></h1>
      </div>
      <button class="logout" id="logout-btn">switch agent</button>
    </div>

    <div class="tiles">
      <div class="tile"><div class="label">Submissions</div><div class="value">${formatInt(agent.submissions)}</div></div>
      <div class="tile"><div class="label">Successful</div><div class="value">${formatInt(agent.successful)}</div></div>
      <div class="tile"><div class="label">Failed</div><div class="value">${formatInt(agent.failed)}</div></div>
      <div class="tile"><div class="label">Contacted</div><div class="value">${formatInt(agent.contacted)}</div></div>
      <div class="tile"><div class="label">Quoted</div><div class="value">${formatInt(agent.quoted)}</div></div>
      <div class="tile"><div class="label">Closed</div><div class="value">${formatInt(agent.closed)}</div></div>
      <div class="tile accent"><div class="label">Final Sale</div><div class="value">${formatRand(agent.final_sale)}</div></div>
    </div>

    <section class="panel">
      <h2>Conversion funnel</h2>
      <div class="funnel">
        ${funnelRow("Submissions", agent.submissions, funnelMax)}
        ${funnelRow("Successful", agent.successful, funnelMax)}
        ${funnelRow("Contacted", agent.contacted, funnelMax)}
        ${funnelRow("Quoted", agent.quoted, funnelMax)}
        ${funnelRow("Closed", agent.closed, funnelMax)}
      </div>
    </section>

    <section class="panel">
      <h2>Trend this month</h2>
      ${renderTrend(agent.trend)}
    </section>
  `;
  document.getElementById("logout-btn").addEventListener("click", () => {
    sessionStorage.removeItem(STORAGE_KEY);
    dashboardEl.style.display = "none";
    identifyEl.style.display = "block";
    input.value = "";
    input.focus();
  });
}

function showAgent(code) {
  const agent = findAgent(DATA.agents, code);
  if (!agent) {
    errEl.textContent = `No agent found for code "${cleanCode(code)}". Check with your manager if this looks wrong.`;
    return false;
  }
  errEl.textContent = "";
  sessionStorage.setItem(STORAGE_KEY, agent.code);
  identifyEl.style.display = "none";
  dashboardEl.style.display = "block";
  renderDashboard(agent);
  return true;
}

async function init() {
  try {
    DATA = await loadData();
  } catch (e) {
    identifyEl.innerHTML = `<h1>Data not available</h1><p>${e.message}</p>`;
    return;
  }
  document.getElementById("footer-date").textContent = DATA.summary.as_of;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    showAgent(input.value);
  });

  const remembered = sessionStorage.getItem(STORAGE_KEY);
  if (remembered) showAgent(remembered);
}

init();
