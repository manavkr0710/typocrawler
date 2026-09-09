"use strict";

const START = 5;
const STEP = 10;
const state = { all: [], org: null, q: "", pending: false, bothOnly: false, limit: START };

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function highlight(context, token) {
  const i = context.toLowerCase().indexOf(token.toLowerCase());
  if (i === -1) return esc(context);
  return (
    esc(context.slice(0, i)) +
    "<mark>" +
    esc(context.slice(i, i + token.length)) +
    "</mark>" +
    esc(context.slice(i + token.length))
  );
}

function visible() {
  const q = state.q.trim().toLowerCase();
  return state.all.filter((f) => {
    if (!state.pending && f.verdict !== "confirmed") return false;
    if (state.bothOnly && f.source !== "both") return false;
    if (state.org && f.org !== state.org) return false;
    if (q) {
      const hay = (f.token + " " + f.repo + " " + f.fix + " " + f.context).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function rowHTML(f) {
  const badge =
    f.verdict === "confirmed" ? "" : `<span class="badge ${f.verdict}">${f.verdict}</span>`;
  const stars = f.stars ? `<span class="stars">★ ${f.stars.toLocaleString()}</span>` : "";
  return `<tr>
    <td class="c-repo">
      <a href="https://github.com/${esc(f.repo)}"><span class="org">${esc(f.org)}/</span>${esc(
    f.repo.split("/")[1]
  )}</a>${stars}
    </td>
    <td class="c-typo"><span class="wrong">${esc(f.token)}</span><span class="arrow">→</span><span class="right">${esc(
    f.fix
  )}</span>${badge}</td>
    <td class="c-ctx">${highlight(f.context, f.token)}</td>
    <td class="c-link"><a href="${esc(f.url)}" target="_blank" rel="noopener">line ${f.line} ↗</a></td>
  </tr>`;
}

function render() {
  const rows = visible();
  const shown = rows.slice(0, state.limit);
  const confirmed = rows.filter((r) => r.verdict === "confirmed").length;

  $("count").textContent =
    rows.length === 0
      ? ""
      : `showing ${shown.length} of ${rows.length}` +
        (state.pending && confirmed !== rows.length ? ` · ${confirmed} confirmed` : "");
  $("empty").hidden = rows.length !== 0;
  $("rows").innerHTML = shown.map(rowHTML).join("");

  const remaining = rows.length - shown.length;
  const btn = $("showMore");
  btn.hidden = remaining <= 0;
  btn.textContent = `Show ${Math.min(STEP, remaining)} more`;
}

function refilter() {
  state.limit = START;
  render();
}

function buildChips() {
  const conf = {};
  const tot = {};
  for (const f of state.all) {
    tot[f.org] = (tot[f.org] || 0) + 1;
    if (f.verdict === "confirmed") conf[f.org] = (conf[f.org] || 0) + 1;
  }
  const orgs = Object.keys(tot).sort(
    (a, b) => (conf[b] || 0) - (conf[a] || 0) || tot[b] - tot[a]
  );
  $("orgChips").innerHTML = orgs
    .map(
      (o) =>
        `<button class="chip" data-org="${esc(o)}" aria-pressed="false">${esc(o)} <span class="n">${
          conf[o] || 0
        }</span></button>`
    )
    .join("");
  $("orgChips").addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    state.org = state.org === btn.dataset.org ? null : btn.dataset.org;
    for (const c of $("orgChips").children)
      c.setAttribute("aria-pressed", String(c.dataset.org === state.org));
    refilter();
  });
}

function countUp(el, target) {
  const dur = 900;
  const t0 = performance.now();
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / dur);
    el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))).toLocaleString();
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function fillMeta(m) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const set = (id, v) => (reduce ? ($(id).textContent = v.toLocaleString()) : countUp($(id), v));
  set("s-confirmed", m.confirmed);
  set("s-repos", m.repos);
  set("s-orgs", m.orgs);
  set("s-scanned", m.readmes_scanned);

  $("generated").textContent = new Date(m.generated_at).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  $("topTypos").innerHTML = m.top_typos
    .map(([w, n]) => `<li><b>${esc(w)}</b> <span class="n">×${n}</span></li>`)
    .join("");

  const max = Math.max(1, ...Object.values(m.by_org));
  $("byOrg").innerHTML = Object.entries(m.by_org)
    .map(
      ([o, n]) =>
        `<li><span>${esc(o)}</span><span class="track" style="width:${(n / max) * 100}%"></span><span class="val">${n}</span></li>`
    )
    .join("");

  if (m.unverified > 0) {
    $("pendingLabel").textContent = `include ${m.unverified.toLocaleString()} unverified`;
  }
}

async function main() {
  const [findings, meta] = await Promise.all([
    fetch("data/findings.json").then((r) => r.json()),
    fetch("data/meta.json").then((r) => r.json()),
  ]);
  state.all = findings;
  fillMeta(meta);
  buildChips();
  render();

  $("q").addEventListener("input", (e) => {
    state.q = e.target.value;
    refilter();
  });
  $("showPending").addEventListener("change", (e) => {
    state.pending = e.target.checked;
    refilter();
  });
  $("bothOnly").addEventListener("change", (e) => {
    state.bothOnly = e.target.checked;
    refilter();
  });
  $("showMore").addEventListener("click", () => {
    state.limit += STEP;
    render();
  });
}

main().catch((err) => {
  $("count").textContent = "Could not load findings data.";
  console.error(err);
});

/* ---------- background: drifting graph paper with proofreader marks ---------- */
(function background() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const canvas = document.getElementById("bg");
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let w, h, dpr, marks;
  const GRID = 46;
  const ink = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  function resize() {
    dpr = Math.min(2, devicePixelRatio || 1);
    w = canvas.width = innerWidth * dpr;
    h = canvas.height = innerHeight * dpr;
    canvas.style.width = innerWidth + "px";
    canvas.style.height = innerHeight + "px";
    const count = Math.round((innerWidth * innerHeight) / (GRID * GRID * 26));
    marks = Array.from({ length: count }, () => ({
      x: Math.random() * innerWidth,
      y: Math.random() * innerHeight,
      kind: Math.random() < 0.5 ? "caret" : "strike",
      phase: Math.random() * Math.PI * 2,
      speed: 0.15 + Math.random() * 0.25,
    }));
  }

  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.scale(dpr, dpr);

    const drift = Math.sin(t / 9000) * 6;
    ctx.strokeStyle = ink("--line");
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = (drift % GRID) - GRID; x < innerWidth + GRID; x += GRID) {
      ctx.moveTo(x, 0);
      ctx.lineTo(x, innerHeight);
    }
    for (let y = (-drift % GRID) - GRID; y < innerHeight + GRID; y += GRID) {
      ctx.moveTo(0, y);
      ctx.lineTo(innerWidth, y);
    }
    ctx.stroke();

    ctx.strokeStyle = ink("--accent");
    ctx.lineWidth = 1.6;
    ctx.lineCap = "round";
    for (const m of marks) {
      const a = (Math.sin((t / 1000) * m.speed + m.phase) + 1) / 2;
      ctx.globalAlpha = 0.05 + a * 0.16;
      ctx.beginPath();
      if (m.kind === "caret") {
        ctx.moveTo(m.x - 6, m.y + 4);
        ctx.lineTo(m.x, m.y - 5);
        ctx.lineTo(m.x + 6, m.y + 4);
      } else {
        ctx.moveTo(m.x - 8, m.y + 3);
        ctx.lineTo(m.x + 8, m.y - 3);
      }
      ctx.stroke();
    }
    ctx.restore();
    requestAnimationFrame(draw);
  }

  addEventListener("resize", resize, { passive: true });
  resize();
  requestAnimationFrame(draw);
})();
