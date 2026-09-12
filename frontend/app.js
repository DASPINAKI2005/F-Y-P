/* GitHub Repo Analyzer — front end
 * Backend contract (do not change without updating the server):
 *  POST /api/analyze            { url }                 -> { analysis_id }
 *  GET  /api/analyze/{id}                                -> { status, result?, error?, provider? }
 *  GET  /api/analyses                                    -> [{ id, owner, name, created_at, score }]
 *  GET  /api/settings/status                             -> { providers, github_token, priority }
 *  POST /api/settings/priority  { priority: [...] }
 */

const qs = (selector, scope = document) => scope.querySelector(selector);

const pages = { "/": "Home", "/index.html": "Home", "/analyzer.html": "Analyzer", "/history.html": "History", "/docs.html": "Documentation", "/about.html": "About", "/settings.html": "Settings" };

const labels = {
  queued: "Queued",
  validating: "Validating repository",
  downloading: "Downloading repository",
  extracting: "Extracting files",
  scanning: "Scanning file tree",
  building_context: "Building analysis context",
  analyzing: "Running AI analysis",
  validating_result: "Validating AI response",
  completed: "Completed",
  failed: "Failed",
};
const PIPELINE_KEYS = Object.keys(labels).slice(0, 8);
const terminalStates = new Set(["completed", "failed"]);

const reduceMotion = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- tiny DOM helper ---------- */
function h(tag, opts = {}, ...children) {
  const node = document.createElement(tag);
  if (opts.class) node.className = opts.class;
  if (opts.id) node.id = opts.id;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.attrs) for (const [key, value] of Object.entries(opts.attrs)) node.setAttribute(key, value);
  for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child);
  return node;
}

/* ---------- shared chrome ---------- */
function brandMark() {
  const wrap = h("span", { class: "brand-mark", attrs: { "aria-hidden": "true" } });
  wrap.innerHTML =
    '<svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<rect x="1" y="1" width="18" height="18" rx="4" stroke="currentColor" stroke-width="1.4"/>' +
    '<path d="M6 7l3 3-3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M11 13h3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
  return wrap;
}

function nav() {
  const header = h("header", { class: "nav" });
  const inner = h("div", { class: "nav-inner" });
  const brand = h("a", { class: "brand", attrs: { href: "/" } }, brandMark(), h("span", { class: "brand-name", text: "Repo Analyzer" }));

  const links = h("nav", { class: "links", attrs: { "aria-label": "Primary" } });
  const current = pages[location.pathname] || "Home";
  ["Home", "Analyzer", "History", "Documentation", "About", "Settings"].forEach((name) => {
    const href = name === "Home" ? "/" : `/${name.toLowerCase().replace("documentation", "docs")}.html`;
    const link = h("a", { text: name, attrs: { href } });
    if (current === name) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
    links.append(link);
  });

  const toggle = h("button", { class: "nav-toggle", attrs: { type: "button", "aria-label": "Toggle navigation", "aria-expanded": "false" } });
  toggle.append(h("span", { class: "nav-toggle-bar" }), h("span", { class: "nav-toggle-bar" }), h("span", { class: "nav-toggle-bar" }));
  toggle.addEventListener("click", () => {
    const open = links.classList.toggle("open");
    toggle.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
  links.querySelectorAll("a").forEach((a) =>
    a.addEventListener("click", () => {
      links.classList.remove("open");
      toggle.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    })
  );

  inner.append(brand, links, toggle);
  header.append(inner);
  return header;
}

function frame(main) {
  main.classList.add("page-enter");
  main.id = "main";
  main.setAttribute("tabindex", "-1");
  const footer = h(
    "footer",
    { class: "footer" },
    h("p", { text: "Local-first repository intelligence." }),
    h("p", { class: "muted", text: "Static analysis only — your repository workspace stays on this machine." })
  );
  const shell = h("div", { class: "shell" }, nav(), main, footer);
  const skip = h("a", { class: "skip-link", text: "Skip to content", attrs: { href: "#main" } });
  document.body.replaceChildren(skip, shell);
  requestAnimationFrame(() => main.classList.add("page-enter-active"));
}

function pageHeader(title, description) {
  const main = h("main", { class: "page" });
  main.append(h("h1", { text: title }));
  if (description) main.append(h("p", { class: "lede muted", text: description }));
  return main;
}

/* ---------- status message helper ---------- */
function setMessage(node, state, text) {
  if (!node) return;
  node.textContent = text;
  node.dataset.state = state;
}

/* ---------- repo analysis entry point ---------- */
function analyzeForm() {
  const row = h("div", { class: "command" });
  const glyph = h("span", { class: "command-glyph", attrs: { "aria-hidden": "true" }, text: "\u203A" });
  const input = h("input", { id: "repo", attrs: { type: "text", placeholder: "github.com/owner/repository", autocomplete: "off", spellcheck: "false", "aria-label": "Repository URL" } });
  const button = h("button", { class: "button", id: "analyze", text: "Analyze" });
  row.append(glyph, input, button);
  return row;
}

function wireAnalyzeForm() {
  const input = qs("#repo");
  const button = qs("#analyze");
  if (!input || !button) return;
  const trigger = () => start(input.value);
  button.onclick = trigger;
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") trigger();
  });
}

async function jsonFetch(url, options) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(response.ok ? "The server returned malformed data." : `Request failed (${response.status}).`);
  }
  if (!response.ok) throw new Error(data?.detail || data?.error || `Request failed (${response.status}).`);
  return data;
}

async function start(rawUrl) {
  const message = qs("#message");
  const button = qs("#analyze");
  const url = (rawUrl || "").trim();
  if (!url) {
    setMessage(message, "error", "Enter a repository URL first.");
    return;
  }
  setMessage(message, "pending", "Validating repository\u2026");
  if (button) button.disabled = true;
  try {
    const data = await jsonFetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    if (!data.analysis_id) throw new Error("The server did not return an analysis ID.");
    location.href = `/analyzer.html?id=${encodeURIComponent(data.analysis_id)}`;
  } catch (error) {
    setMessage(message, "error", error.message);
    if (button) button.disabled = false;
  }
}

/* ---------- home ---------- */
function featureCard(title, body) {
  return h("article", { class: "feature-card" }, h("h3", { text: title }), h("p", { class: "muted", text: body }));
}

function home() {
  const main = h("main", { class: "hero" });
  main.append(
    h("h1", { text: "See what's actually in the repository." }),
    h("p", { class: "lede", text: "Paste a public GitHub URL. A staged scanner reads the file tree, an AI model interprets what it finds, and you get a plain report on architecture, risk, and what to fix first." }),
    analyzeForm(),
    h("div", { class: "status", id: "message", attrs: { role: "status", "aria-live": "polite" } })
  );

  const features = h("section", { class: "feature-grid" });
  [
    ["Evidence before opinion", "The scanner maps files, dependencies, and structure before any model reads a line of code."],
    ["Automatic fallback", "Gemini, Groq, OpenRouter, and Hugging Face sit behind one interface. If one is unavailable, the next takes over."],
    ["No code execution", "Nothing in the repository is ever run. Archives are bounded and paths are checked before anything is opened."],
    ["Kept on this machine", "Analyses are written to a local database. Nothing about your history leaves your computer."],
  ].forEach(([title, body]) => features.append(featureCard(title, body)));
  main.append(features);

  frame(main);
  wireAnalyzeForm();
}

/* ---------- analyzer (live) ---------- */
let timerHandle = null;
function startTimer() {
  const startedAt = Date.now();
  const tick = () => {
    const node = qs("#timer");
    if (!node) {
      stopTimer();
      return;
    }
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
    const secs = String(seconds % 60).padStart(2, "0");
    node.textContent = `Elapsed ${minutes}:${secs}`;
  };
  tick();
  timerHandle = setInterval(tick, 1000);
}
function stopTimer() {
  if (timerHandle) clearInterval(timerHandle);
  timerHandle = null;
}

function renderSteps(status) {
  const container = qs("#steps");
  if (!container) return;
  const fullOrder = Object.keys(labels);
  const statusIndex = fullOrder.indexOf(status);
  const halted = status === "failed";
  container.replaceChildren(
    ...PIPELINE_KEYS.map((key, index) => {
      let state = "pending";
      if (halted) state = "halted";
      else if (status === "completed") state = "done";
      else if (index < statusIndex) state = "done";
      else if (index === statusIndex) state = "active";
      const li = h("li", { class: `pipeline-step is-${state}` });
      li.append(h("span", { class: "pipeline-index", attrs: { "aria-hidden": "true" }, text: String(index + 1) }), h("span", { class: "pipeline-label", text: labels[key] }));
      return li;
    })
  );
}

function analyzerEmpty() {
  const main = pageHeader("Analyze a repository", "Paste a public GitHub URL to begin.");
  main.append(analyzeForm(), h("div", { class: "status", id: "message", attrs: { role: "status", "aria-live": "polite" } }));
  frame(main);
  wireAnalyzeForm();
}

function analyzer() {
  const id = new URLSearchParams(location.search).get("id");
  if (!id) {
    analyzerEmpty();
    return;
  }
  const main = h("main", { class: "page analyzer-live" });
  main.append(
    h("p", { class: "kicker", id: "analyzer-kicker", text: "Live analysis" }),
    h("h1", { id: "analyzer-title", text: "Reading the repository" }),
    h("p", { class: "status", id: "status", attrs: { role: "status", "aria-live": "polite" }, text: "Connecting\u2026" }),
    h("p", { class: "timer mono muted", id: "timer" }),
    h("ol", { class: "pipeline", id: "steps", attrs: { "aria-label": "Analysis pipeline" } }),
    h("div", { id: "result" })
  );
  frame(main);
  startTimer();
  poll(id);
}

async function poll(id) {
  try {
    const data = await jsonFetch(`/api/analyze/${encodeURIComponent(id)}`);
    const statusNode = qs("#status");
    if (statusNode) statusNode.textContent = labels[data.status] || "Unknown analysis state";
    renderSteps(data.status);

    if (data.status === "completed" && data.result) {
      stopTimer();
      const kicker = qs("#analyzer-kicker");
      if (kicker) kicker.textContent = "Complete";
      const title = qs("#analyzer-title");
      if (title) title.textContent = data.result.repository?.name ? `${data.result.repository.name} \u2014 analysis complete` : "Analysis complete";
      showReport(data.result, data.provider);
    } else if (data.status === "failed") {
      stopTimer();
      const kicker = qs("#analyzer-kicker");
      if (kicker) kicker.textContent = "Failed";
      showFailure(data.error);
    } else if (!terminalStates.has(data.status)) {
      setTimeout(() => poll(id), 1200);
    }
  } catch (error) {
    const statusNode = qs("#status");
    if (statusNode) statusNode.textContent = error.message;
    const resultNode = qs("#result");
    if (resultNode) resultNode.replaceChildren();
  }
}

function showFailure(message) {
  const resultNode = qs("#result");
  if (!resultNode) return;
  resultNode.replaceChildren(
    h("div", { class: "panel panel-failed" }, h("h2", { text: "The analysis did not finish" }), h("p", { class: "muted", text: message || "None of the configured providers were available. Check Settings and try again." }))
  );
}

/* ---------- analysis result ---------- */
function scoreBand(score) {
  if (score >= 80) return "Strong";
  if (score >= 50) return "Moderate";
  return "Needs attention";
}

function buildScoreCard(score) {
  const has = typeof score === "number" && !Number.isNaN(score);
  const value = has ? Math.max(0, Math.min(100, score)) : null;
  const card = h(
    "div",
    { class: "panel score-card" },
    h("p", { class: "score-label", text: "Overall score" }),
    h("p", { class: "score-value mono", text: has ? String(score) : "\u2014" })
  );
  const meter = h("div", { class: "score-meter", attrs: { role: "img", "aria-label": has ? `Score ${score} out of 100` : "Score unavailable" } });
  const fill = h("div", { class: "score-meter-fill" });
  meter.append(fill);
  card.append(meter);
  if (has) card.append(h("p", { class: "score-band muted", text: scoreBand(value) }));
  requestAnimationFrame(() => {
    fill.style.width = has ? `${value}%` : "0%";
  });
  return card;
}

function makeCollapsible(listEl, total, threshold = 6) {
  if (!listEl || total <= threshold) return;
  [...listEl.children].slice(threshold).forEach((li) => li.classList.add("is-hidden"));
  const more = h("button", { class: "show-more", attrs: { type: "button" }, text: `Show ${total - threshold} more` });
  more.addEventListener("click", () => {
    listEl.querySelectorAll(".is-hidden").forEach((li) => li.classList.remove("is-hidden"));
    more.remove();
  });
  listEl.after(more);
}

function buildDiffPanel(strengths, weaknesses) {
  const wrap = h("div", { class: "panel diff-panel" });
  wrap.append(h("h2", { text: "Strengths and weaknesses" }));
  const grid = h("div", { class: "diff-grid" });

  const goodItems = Array.isArray(strengths) ? strengths : [];
  const badItems = Array.isArray(weaknesses) ? weaknesses : [];

  const goodCol = h("div", { class: "diff-column" });
  goodCol.append(h("h3", { text: "Strengths" }));
  const goodList = h("ul", { class: "diff-list diff-good" });
  goodItems.forEach((item) => goodList.append(h("li", {}, h("span", { class: "diff-mark mono", attrs: { "aria-hidden": "true" }, text: "+" }), h("span", { text: String(item) }))));
  goodCol.append(goodList);

  const badCol = h("div", { class: "diff-column" });
  badCol.append(h("h3", { text: "Weaknesses" }));
  const badList = h("ul", { class: "diff-list diff-bad" });
  badItems.forEach((item) => badList.append(h("li", {}, h("span", { class: "diff-mark mono", attrs: { "aria-hidden": "true" }, text: "\u2212" }), h("span", { text: String(item) }))));
  badCol.append(badList);

  grid.append(goodCol, badCol);
  wrap.append(grid);
  makeCollapsible(goodList, goodItems.length);
  makeCollapsible(badList, badItems.length);
  return wrap;
}

function buildListPanel(title, items, modifierClass, glyph) {
  const wrap = h("div", { class: `panel ${modifierClass}` });
  wrap.append(h("div", { class: "panel-head" }, h("h2", { text: title }), h("span", { class: "count mono", text: String(items.length) })));
  const list = h("ul", { class: "flag-list" });
  items.forEach((item) => list.append(h("li", {}, h("span", { class: "flag-mark", attrs: { "aria-hidden": "true" }, text: glyph }), h("span", { text: String(item) }))));
  wrap.append(list);
  makeCollapsible(list, items.length);
  return wrap;
}

function buildRecommendationsPanel(items) {
  const wrap = h("div", { class: "panel accent-neutral" });
  wrap.append(h("h2", { text: "Recommendations" }));
  const list = h("ol", { class: "recommend-list" });
  items.forEach((item) => list.append(h("li", {}, h("span", { text: String(item) }))));
  wrap.append(list);
  makeCollapsible(list, items.length);
  return wrap;
}

function showReport(report, provider) {
  const resultNode = qs("#result");
  if (!resultNode) return;
  const repository = report.repository || {};

  const brief = h("article", { class: "panel brief" });
  brief.append(h("p", { class: "identity mono" }, h("span", { text: repository.owner || "unknown" }), h("span", { class: "muted", text: " / " }), h("span", { text: repository.name || "repository" })));
  if (report.executive_summary) brief.append(h("p", { class: "summary", text: String(report.executive_summary) }));
  if (report.project_purpose) brief.append(h("p", { class: "muted", text: String(report.project_purpose) }));
  brief.append(h("p", { class: "engine mono muted", text: `Engine: ${provider || "automatic"}` }));

  const top = h("div", { class: "report-top" }, brief, buildScoreCard(report.overall_score));

  const sections = h("div", { class: "report-sections" });

  const architecture = report.architecture || {};
  if (architecture.description || architecture.type) {
    const archHead = h("div", { class: "panel-head" }, h("h2", { text: "Architecture" }));
    if (architecture.type) archHead.append(h("span", { class: "tag mono", text: String(architecture.type) }));
    const arch = h("div", { class: "panel accent-neutral" }, archHead);
    if (architecture.description) arch.append(h("p", { class: "muted", text: String(architecture.description) }));
    sections.append(arch);
  }

  if (Array.isArray(report.technology_stack) && report.technology_stack.length) {
    const tagRow = h("div", { class: "tag-row" });
    report.technology_stack.forEach((item) => tagRow.append(h("span", { class: "tag", text: String(item) })));
    sections.append(h("div", { class: "panel accent-neutral" }, h("h2", { text: "Technology stack" }), tagRow));
  }

  if ((Array.isArray(report.strengths) && report.strengths.length) || (Array.isArray(report.weaknesses) && report.weaknesses.length)) {
    sections.append(buildDiffPanel(report.strengths, report.weaknesses));
  }

  if (Array.isArray(report.security_findings) && report.security_findings.length) {
    sections.append(buildListPanel("Security findings", report.security_findings, "accent-bad", "\u25B2"));
  }

  if (Array.isArray(report.recommendations) && report.recommendations.length) {
    sections.append(buildRecommendationsPanel(report.recommendations));
  }

  resultNode.replaceChildren(top, sections);
}

/* ---------- history ---------- */
function scoreBandClass(score) {
  if (score >= 80) return "score-good";
  if (score >= 50) return "score-mid";
  return "score-low";
}

function historyRow(row, rows, onDeleted) {
  const hasScore = typeof row.score === "number" && !Number.isNaN(row.score);
  const view = h("a", { class: "history-view", attrs: { href: `/analyzer.html?id=${encodeURIComponent(row.id)}` }, text: "View" });
  const deleteButton = h("button", { class: "history-delete", attrs: { type: "button", "aria-label": "Delete this analysis" }, text: "Delete" });
  const deleteError = h("span", { class: "history-delete-error", attrs: { role: "alert" } });
  const actions = h("span", { class: "history-actions" }, view, deleteButton, deleteError);
  const item = h("div", { class: "history-row" });
  item.append(
    h("span", { class: "history-repo mono", text: `${row.owner || ""}/${row.name || ""}` }),
    h("span", { class: "history-date muted", text: row.created_at ? new Date(row.created_at).toLocaleString() : "\u2014" }),
    h("span", { class: `history-score ${hasScore ? scoreBandClass(row.score) : "score-unknown"}` }, h("span", { class: "mono", text: hasScore ? String(row.score) : "\u2014" })),
    actions
  );
  deleteButton.addEventListener("click", async () => {
    if (!window.confirm("Delete this analysis?")) return;
    deleteButton.disabled = true;
    deleteError.textContent = "";
    try {
      await jsonFetch(`/api/analyses/${encodeURIComponent(row.id)}`, { method: "DELETE" });
      const index = rows.indexOf(row);
      if (index !== -1) rows.splice(index, 1);
      item.remove();
      onDeleted();
    } catch (error) {
      deleteError.textContent = error.message;
      deleteButton.disabled = false;
    }
  });
  return item;
}

async function history() {
  const main = pageHeader("Past analyses");
  const controls = h("div", { class: "history-controls" });
  const search = h("input", { class: "history-search", attrs: { type: "search", placeholder: "Filter by repository", "aria-label": "Filter history by repository name" } });
  controls.append(search);
  const historyPanel = h("div", { class: "panel", id: "history", text: "Loading\u2026" });
  main.append(controls, historyPanel);
  frame(main);

  let rows;
  try {
    rows = await jsonFetch("/api/analyses");
  } catch (error) {
    controls.style.display = "none";
    historyPanel.replaceChildren(h("p", { class: "status", text: error.message }));
    return;
  }
  if (!Array.isArray(rows) || !rows.length) {
    controls.style.display = "none";
    historyPanel.replaceChildren(h("p", { class: "muted", text: "No analyses yet. Run one from the home page." }));
    return;
  }

  const render = (list) => {
    if (!list.length) {
      historyPanel.replaceChildren(h("p", { class: "muted", text: rows.length ? "No repositories match that filter." : "No analyses yet. Run one from the home page." }));
      return;
    }
    historyPanel.replaceChildren(...list.map((row) => historyRow(row, rows, () => {
      if (!rows.length) controls.style.display = "none";
      const query = search.value.trim().toLowerCase();
      render(!query ? rows : rows.filter((entry) => `${entry.owner || ""}/${entry.name || ""}`.toLowerCase().includes(query)));
    })));
  };
  render(rows);
  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    render(!query ? rows : rows.filter((row) => `${row.owner || ""}/${row.name || ""}`.toLowerCase().includes(query)));
  });
}

/* ---------- settings ---------- */
function providerRow(name, configured, optionalLabel) {
  return h(
    "div",
    { class: "provider-row" },
    h("span", { class: `provider-dot ${configured ? "is-on" : "is-off"}`, attrs: { "aria-hidden": "true" } }),
    h("span", { class: "provider-name", text: name }),
    h("span", { class: `pill ${configured ? "pill-on" : "pill-off"}`, text: configured ? "Configured" : optionalLabel || "Not configured" })
  );
}

function priorityPill(name, index, total, handlers) {
  const li = h("li", { class: "priority-pill", attrs: { draggable: "true" } });
  li.dataset.provider = name;
  const up = h("button", { class: "priority-btn", attrs: { type: "button", "aria-label": `Move ${name} up` }, text: "\u2191" });
  const down = h("button", { class: "priority-btn", attrs: { type: "button", "aria-label": `Move ${name} down` }, text: "\u2193" });
  up.disabled = index === 0;
  down.disabled = index === total - 1;
  up.addEventListener("click", handlers.onMoveUp);
  down.addEventListener("click", handlers.onMoveDown);

  li.append(h("span", { class: "priority-rank mono", text: String(index + 1) }), h("span", { class: "priority-name", text: name }), h("span", { class: "priority-controls" }, up, down));

  li.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("text/plain", String(index));
    event.dataTransfer.effectAllowed = "move";
    li.classList.add("dragging");
  });
  li.addEventListener("dragend", () => li.classList.remove("dragging"));
  li.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    li.classList.add("drop-target");
  });
  li.addEventListener("dragleave", () => li.classList.remove("drop-target"));
  li.addEventListener("drop", (event) => {
    event.preventDefault();
    li.classList.remove("drop-target");
    const fromIndex = Number(event.dataTransfer.getData("text/plain"));
    if (!Number.isNaN(fromIndex) && fromIndex !== index) handlers.onDrop(fromIndex);
  });
  return li;
}

async function settings() {
  const main = pageHeader("Analysis engine");
  const settingsPanel = h("div", { class: "panel", id: "settings", text: "Loading\u2026" });
  main.append(settingsPanel);
  frame(main);

  let data;
  try {
    data = await jsonFetch("/api/settings/status");
  } catch (error) {
    settingsPanel.replaceChildren(h("p", { class: "status", text: error.message }));
    return;
  }
  settingsPanel.replaceChildren();

  const providers = data.providers || {};
  const providerSection = h("section", { class: "settings-block" });
  providerSection.append(h("h2", { text: "Providers" }));
  const providerList = h("div", { class: "provider-list" });
  Object.entries(providers).forEach(([name, configured]) => providerList.append(providerRow(name, !!configured)));
  providerSection.append(providerList, providerRow("GitHub token", !!data.github_token, "Optional"));
  settingsPanel.append(providerSection);

  const prioritySection = h("section", { class: "settings-block" });
  prioritySection.append(h("h2", { text: "Fallback order" }), h("p", { class: "muted", text: "Providers are tried left to right. Drag to reorder, or use the arrows." }));

  const initialOrder = Array.isArray(data.priority) && data.priority.length ? data.priority.slice() : Object.keys(providers);
  const hiddenInput = h("input", { id: "priority", attrs: { type: "hidden" } });
  const pillList = h("ul", { class: "priority-list", attrs: { "aria-label": "Fallback order, editable" } });

  function syncHidden() {
    hiddenInput.value = [...pillList.children].map((li) => li.dataset.provider).join(", ");
  }
  function renderPills(order) {
    pillList.replaceChildren(
      ...order.map((name, index) =>
        priorityPill(name, index, order.length, {
          onMoveUp: () => {
            if (index === 0) return;
            [order[index - 1], order[index]] = [order[index], order[index - 1]];
            renderPills(order);
            syncHidden();
          },
          onMoveDown: () => {
            if (index === order.length - 1) return;
            [order[index + 1], order[index]] = [order[index], order[index + 1]];
            renderPills(order);
            syncHidden();
          },
          onDrop: (fromIndex) => {
            const [moved] = order.splice(fromIndex, 1);
            order.splice(index, 0, moved);
            renderPills(order);
            syncHidden();
          },
        })
      )
    );
  }
  renderPills(initialOrder);
  syncHidden();

  const priorityEditor = h("div", { class: "priority-editor" }, pillList, hiddenInput);
  if (!initialOrder.length) prioritySection.append(h("p", { class: "muted", text: "No providers configured yet." }));
  const saveButton = h("button", { class: "button", id: "save-priority", text: "Save order" });
  const saveMessage = h("div", { class: "status", id: "settings-message", attrs: { role: "status", "aria-live": "polite" } });
  prioritySection.append(priorityEditor, h("div", { class: "save-row" }, saveButton, saveMessage));
  settingsPanel.append(prioritySection);

  saveButton.onclick = async () => {
    const priority = hiddenInput.value.split(",").map((value) => value.trim()).filter(Boolean);
    saveButton.disabled = true;
    try {
      await jsonFetch("/api/settings/priority", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ priority }) });
      setMessage(saveMessage, "success", "Fallback order saved.");
    } catch (error) {
      setMessage(saveMessage, "error", error.message);
    } finally {
      saveButton.disabled = false;
    }
  };
}

/* ---------- docs & about ---------- */
function docs() {
  const main = pageHeader("How it works", "Three stages: get the code, read the code, explain the code.");

  main.append(
    h("section", { class: "doc-block" }, h("h2", { text: "Install" }), h("p", { class: "muted", text: "Create a Python environment and install the requirements. Copy .env.example to .env and add at least one AI provider key. Then run python run.py." }))
  );

  const stages = [
    "Validate the URL and confirm the repository is reachable",
    "Download the repository archive",
    "Extract it inside a bounded workspace",
    "Scan the file tree and detect technologies",
    "Select the file context that matters most",
    "Send that context to an AI provider for analysis",
    "Validate the AI response against the expected schema",
    "Save the result to the local archive",
  ];
  const pipelineBlock = h("section", { class: "doc-block" }, h("h2", { text: "Pipeline" }));
  const ol = h("ol", { class: "doc-steps" });
  stages.forEach((stage) => ol.append(h("li", { text: stage })));
  pipelineBlock.append(ol);
  main.append(pipelineBlock);

  main.append(
    h("section", { class: "doc-block" }, h("h2", { text: "Privacy" }), h("p", { class: "muted", text: "Only the selected text context is sent to your configured AI provider. History and settings are stored in a local database that stays on this machine." }))
  );

  frame(main);
}

function about() {
  const main = pageHeader("About", "A calm, local-first way to read a repository before you rely on it.");
  main.append(h("p", { class: "muted", text: "GitHub Repo Analyzer never runs repository code, package scripts, workflows, or containers. It uses the GitHub API to acquire a repository and a separate AI provider to interpret what the scanner finds." }));

  const facts = h("dl", { class: "fact-list" });
  [
    ["Execution", "None \u2014 nothing in a repository is ever run."],
    ["Acquisition", "GitHub API"],
    ["Interpretation", "Your configured AI provider"],
    ["Storage", "Local database on this machine"],
  ].forEach(([term, desc]) => facts.append(h("dt", { text: term }), h("dd", { class: "muted", text: desc })));
  main.append(facts);

  frame(main);
}

/* ---------- routing ---------- */
const path = location.pathname;
if (path === "/" || path === "/index.html") home();
else if (path === "/analyzer.html") analyzer();
else if (path === "/history.html") history();
else if (path === "/settings.html") settings();
else if (path === "/docs.html") docs();
else about();