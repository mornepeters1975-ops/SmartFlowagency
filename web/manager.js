// Manager view: all agents, reconciliation banner, unassigned bucket, excluded policies.

let DATA = null;
let sortKey = "final_sale";
let sortDir = "desc";

function renderBanner(recon) {
  const banner = document.getElementById("banner");
  const variance = recon.variance_summary;
  if (recon.passed) {
    banner.innerHTML = `
      <div class="banner ok">
        <div>
          <div class="btitle">Reconciliation passed</div>
          <div class="bmeta">Variance: ${formatRand(variance)}</div>
        </div>
        <div class="bmeta">${DATA.summary.production_report_used} · ${DATA.summary.vendor_report_used}</div>
      </div>`;
  } else {
    banner.innerHTML = `
      <div class="banner fail">
        <div>
          <div class="btitle">Reconciliation FAILED</div>
          <div class="bmeta">${recon.failures.join(" · ")}</div>
        </div>
      </div>`;
  }
}

function agentRow(a) {
  const nameStr = a.name ? `${a.name} ${a.surname}` : "—";
  return `
    <tr>
      <td class="code">${a.code}</td>
      <td>${nameStr}</td>
      <td>${a.team || "—"}</td>
      <td>${formatInt(a.submissions)}</td>
      <td>${formatInt(a.successful)}</td>
      <td>${formatInt(a.failed)}</td>
      <td>${formatInt(a.contacted)}</td>
      <td>${formatInt(a.quoted)}</td>
      <td>${formatInt(a.closed)}</td>
      <td>${formatRand(a.final_sale)}</td>
    </tr>`;
}

function currentRows() {
  const team = document.getElementById("team-filter").value;
  const search = document.getElementById("search").value.trim().toLowerCase();
  let rows = DATA.agents.filter((a) => {
    if (team && a.team !== team) return false;
    if (search) {
      const hay = `${a.code} ${a.name || ""} ${a.surname || ""}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });
  rows = rows.slice().sort((x, y) => {
    let vx = x[sortKey], vy = y[sortKey];
    if (typeof vx === "string" || typeof vy === "string") {
      vx = String(vx || ""); vy = String(vy || "");
      return sortDir === "asc" ? vx.localeCompare(vy) : vy.localeCompare(vx);
    }
    return sortDir === "asc" ? (vx || 0) - (vy || 0) : (vy || 0) - (vx || 0);
  });
  return rows;
}

function renderTable() {
  const tbody = document.getElementById("agents-tbody");
  tbody.innerHTML = currentRows().map(agentRow).join("");
  document.querySelectorAll("#agents-table th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.key === sortKey);
  });
}

function renderUnassigned(u) {
  const tiles = document.getElementById("unassigned-tiles");
  const fields = [
    ["Submissions", u.submissions, formatInt],
    ["Successful", u.successful, formatInt],
    ["Failed", u.failed, formatInt],
    ["Contacted", u.contacted, formatInt],
    ["Quoted", u.quoted, formatInt],
    ["Closed", u.closed, formatInt],
    ["Final Sale", u.final_sale, formatRand],
  ];
  tiles.innerHTML = fields.map(([label, val, fmt]) => `
    <div class="tile"><div class="label">${label}</div><div class="value" style="font-size:22px">${fmt(val)}</div></div>
  `).join("");

  document.getElementById("unresolved-codes").innerHTML =
    (u.unresolved_codes_seen.length ? u.unresolved_codes_seen : ["none"]).map((c) => `<li>${c}</li>`).join("");
  document.getElementById("unattributed-refs").innerHTML =
    (u.unattributed_bk_refs.length ? u.unattributed_bk_refs : ["none"]).map((c) => `<li>${c}</li>`).join("");
}

function renderExcluded(list) {
  const tbody = document.getElementById("excluded-tbody");
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="2" class="small-note">None this month.</td></tr>`;
    return;
  }
  tbody.innerHTML = list.map((row) => `<tr><td class="code">${row.bk_Ref}</td><td class="code">${row.agent_code}</td></tr>`).join("");
}

function populateTeamFilter(teams) {
  const select = document.getElementById("team-filter");
  teams.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    select.appendChild(opt);
  });
}

async function init() {
  const main = document.querySelector("main");
  try {
    DATA = await loadData();
  } catch (e) {
    main.innerHTML = `<h1>Data not available</h1><p>${e.message}</p>`;
    return;
  }

  document.getElementById("footer-date").textContent = DATA.summary.as_of;
  renderBanner(DATA.summary.reconciliation);
  populateTeamFilter(DATA.summary.teams);
  renderUnassigned(DATA.summary.unassigned);
  renderExcluded(DATA.summary.excluded_zero_value_policies);
  renderTable();

  document.getElementById("team-filter").addEventListener("change", renderTable);
  document.getElementById("search").addEventListener("input", renderTable);
  document.querySelectorAll("#agents-table th").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (sortKey === key) {
        sortDir = sortDir === "asc" ? "desc" : "asc";
      } else {
        sortKey = key;
        sortDir = "desc";
      }
      renderTable();
    });
  });
}

init();
