# DocuProj Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A no-build, single-page dashboard (vanilla HTML/CSS/JS + SVG) served by FastAPI that shows the endpoint list → cross-repo swimlane flow → step popup with code refs — the MVP's headline "pick an endpoint, see its flow" in a browser.

**Architecture:** Static files in `DocuProj/dashboard/` mounted at `/app` via `StaticFiles`. `app.js` calls the existing JSON API (`/projects`, `/projects/{id}/endpoints`, `.../flow`, `.../flow-node`), groups flow nodes by repo into swimlanes, draws nodes as boxes and edges as SVG arrows (dashed for confidence < 1.0), and opens a modal with `codeRef` on node click. No bundler, no npm.

**Tech Stack:** FastAPI `StaticFiles`, uvicorn (to serve for real), vanilla HTML/CSS/JS, pytest (serving/structure tests via TestClient). Frontend rendering is validated by launching the server against the live EDFX model (a static page cannot be unit-tested in pytest).

---

## Roadmap context

**Plan 6 — the final Phase-1 MVP plan.** Consumes the Plan 5 API. Completes the vertical: ingest → parse → link → cache → API → **dashboard**. Deferred beyond MVP: Mermaid diagram / narrative / Word-PDF export (spec §5 reqs 9-11), Claude resolver wiring, Phase-2 MCP publishing.

## File Structure

```
DocuProj/
  requirements.txt          # + uvicorn (to run the server)
  engine/api.py             # mount StaticFiles at /app; redirect / -> /app/
  dashboard/
    index.html              # layout: sidebar endpoint list, flow canvas, modal
    styles.css              # swimlane + node + modal styling
    app.js                  # fetch API, render endpoint list / swimlanes / popup
  tests/
    test_dashboard.py       # TestClient: dashboard served, assets served, structure
```

---

### Task 1: Serve the dashboard from FastAPI

**Files:**
- Modify: `DocuProj/requirements.txt`
- Modify: `DocuProj/engine/api.py`
- Create: `DocuProj/dashboard/index.html` (full page — see Task 2 for assets)
- Test: `DocuProj/tests/test_dashboard.py`

Mount `dashboard/` at `/app` (with `html=True` so `/app/` serves `index.html`) and redirect `/` → `/app/`.

- [ ] **Step 1: Add dep** — append to `DocuProj/requirements.txt`

```text
uvicorn>=0.30
```

- [ ] **Step 2: Write the failing test** — `DocuProj/tests/test_dashboard.py`

```python
from fastapi.testclient import TestClient

from engine.api import create_app


def _client(tmp_path):
    return TestClient(create_app(projects_dir=tmp_path, workspace=tmp_path / "ws", store={}))


def test_root_redirects_to_dashboard(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/app/"


def test_dashboard_index_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/app/")
    assert resp.status_code == 200
    assert "DocuProj" in resp.text
    assert 'id="endpoint-list"' in resp.text
```

- [ ] **Step 3: Create a minimal `DocuProj/dashboard/index.html`** (expanded in Task 2)

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>DocuProj</title>
</head>
<body>
  <ul id="endpoint-list"></ul>
</body>
</html>
```

- [ ] **Step 4: Implement serving** — edit `DocuProj/engine/api.py`

Add imports near the top:

```python
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
```

Inside `create_app`, after the app is created and before `return app`, add:

```python
    @app.get("/")
    def _root():
        return RedirectResponse(url="/app/")

    dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
    app.mount("/app", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")
```

- [ ] **Step 5: Install + run tests**

Run (from `DocuProj/`): `.\.venv\Scripts\pip install -r requirements.txt` then `.\.venv\Scripts\pytest tests/test_dashboard.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add DocuProj/requirements.txt DocuProj/engine/api.py DocuProj/dashboard/index.html DocuProj/tests/test_dashboard.py
git commit -m "feat(dashboard): serve static dashboard from FastAPI"
```

---

### Task 2: Dashboard UI (endpoint list → swimlanes → step popup)

**Files:**
- Modify: `DocuProj/dashboard/index.html`
- Create: `DocuProj/dashboard/styles.css`
- Create: `DocuProj/dashboard/app.js`
- Modify: `DocuProj/tests/test_dashboard.py` (append)

The page: left sidebar lists endpoints; clicking one fetches its flow and draws repo swimlanes with node boxes + SVG edges; clicking a node opens a modal with its `codeRef`.

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_dashboard.py`

```python
def test_dashboard_assets_served(tmp_path):
    client = _client(tmp_path)
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/styles.css").status_code == 200


def test_index_wires_assets_and_mounts(tmp_path):
    client = _client(tmp_path)
    html = client.get("/app/").text
    assert "app.js" in html
    assert "styles.css" in html
    for marker in ('id="endpoint-list"', 'id="flow-canvas"', 'id="popup"'):
        assert marker in html
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_dashboard.py -v`
Expected: FAIL — `/app/app.js` is 404 and the new markers are missing.

- [ ] **Step 3: Replace `DocuProj/dashboard/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DocuProj — Cross-repo flows</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header>
    <h1>DocuProj</h1>
    <span id="project-name"></span>
  </header>
  <main>
    <aside>
      <input id="filter" placeholder="Filter endpoints…" />
      <ul id="endpoint-list"></ul>
    </aside>
    <section id="flow-panel">
      <div id="flow-title">Select an endpoint to see its cross-repo flow</div>
      <div id="flow-canvas"></div>
    </section>
  </main>
  <div id="popup" class="hidden">
    <div id="popup-card">
      <button id="popup-close">×</button>
      <h2 id="popup-title"></h2>
      <div id="popup-ref"></div>
      <pre id="popup-snippet"></pre>
    </div>
  </div>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create `DocuProj/dashboard/styles.css`**

```css
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.5 system-ui, sans-serif; color: #1c2330; }
header { display: flex; gap: 12px; align-items: baseline; padding: 12px 18px; background: #0f1b2d; color: #fff; }
header h1 { font-size: 18px; margin: 0; }
#project-name { color: #9db4d4; }
main { display: flex; height: calc(100vh - 53px); }
aside { width: 320px; border-right: 1px solid #dde3ec; display: flex; flex-direction: column; }
#filter { margin: 10px; padding: 7px 9px; border: 1px solid #cbd4e1; border-radius: 6px; }
#endpoint-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; }
#endpoint-list li { padding: 8px 12px; border-bottom: 1px solid #eef1f6; cursor: pointer; font-family: ui-monospace, monospace; font-size: 12.5px; }
#endpoint-list li:hover { background: #eef4ff; }
#endpoint-list li.active { background: #dce9ff; }
#flow-panel { flex: 1; overflow: auto; padding: 16px; }
#flow-title { font-weight: 600; margin-bottom: 14px; }
.lane { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px dashed #d6deea; }
.lane-label { width: 150px; font-weight: 600; color: #335; font-size: 12px; }
.lane-nodes { display: flex; gap: 28px; flex-wrap: wrap; }
.node { padding: 8px 12px; border: 1.5px solid #4577c4; border-radius: 8px; background: #fff; cursor: pointer; font-size: 12.5px; }
.node.kind-ui { border-color: #6b46c1; background: #f6f2ff; }
.node.kind-route { border-color: #2f855a; background: #f0fff6; }
.node:hover { box-shadow: 0 1px 6px rgba(0,0,0,.15); }
.edge-note { color: #7a869a; font-size: 11px; margin: 2px 0 0 160px; }
.hidden { display: none; }
#popup { position: fixed; inset: 0; background: rgba(10,18,30,.45); display: flex; align-items: center; justify-content: center; }
#popup-card { background: #fff; border-radius: 10px; padding: 18px 20px; max-width: 680px; width: 90%; position: relative; }
#popup-close { position: absolute; top: 8px; right: 12px; border: none; background: none; font-size: 22px; cursor: pointer; }
#popup-ref { font-family: ui-monospace, monospace; color: #2f855a; margin-bottom: 8px; }
#popup-snippet { background: #0f1b2d; color: #e6edf3; padding: 12px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }
```

- [ ] **Step 5: Create `DocuProj/dashboard/app.js`**

```javascript
let PID = null;

async function getJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${resp.status} ${url}`);
  return resp.json();
}

async function init() {
  const projects = await getJSON("/projects");
  if (!projects.length) {
    document.getElementById("flow-title").textContent =
      "No analyzed project. POST /projects/{id}/run first.";
    return;
  }
  PID = projects[0].id;
  document.getElementById("project-name").textContent = projects[0].name || PID;
  const endpoints = await getJSON(`/projects/${PID}/endpoints`);
  renderEndpoints(endpoints);
  wireFilter();
}

function renderEndpoints(endpoints) {
  const ul = document.getElementById("endpoint-list");
  ul.innerHTML = "";
  endpoints.forEach((ep) => {
    const li = document.createElement("li");
    li.textContent = `${ep.method} ${ep.path}`;
    li.dataset.id = ep.id;
    li.onclick = () => {
      document.querySelectorAll("#endpoint-list li").forEach((x) => x.classList.remove("active"));
      li.classList.add("active");
      loadFlow(ep);
    };
    ul.appendChild(li);
  });
}

function wireFilter() {
  document.getElementById("filter").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll("#endpoint-list li").forEach((li) => {
      li.style.display = li.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });
}

async function loadFlow(ep) {
  const title = document.getElementById("flow-title");
  const canvas = document.getElementById("flow-canvas");
  title.textContent = `${ep.method} ${ep.path}`;
  canvas.innerHTML = "";
  let flow;
  try {
    flow = await getJSON(`/projects/${PID}/flow?endpoint_id=${encodeURIComponent(ep.id)}`);
  } catch (e) {
    canvas.innerHTML = `<p>No cross-repo flow found for this endpoint.</p>`;
    return;
  }
  renderSwimlanes(flow);
}

function renderSwimlanes(flow) {
  const canvas = document.getElementById("flow-canvas");
  const lanes = {};
  flow.nodes.forEach((n) => {
    (lanes[n.repo] = lanes[n.repo] || []).push(n);
  });
  Object.keys(lanes).forEach((repo) => {
    const lane = document.createElement("div");
    lane.className = "lane";
    const label = document.createElement("div");
    label.className = "lane-label";
    label.textContent = repo;
    const nodes = document.createElement("div");
    nodes.className = "lane-nodes";
    lanes[repo].forEach((n) => {
      const box = document.createElement("div");
      box.className = `node kind-${n.kind}`;
      box.textContent = n.label;
      box.onclick = () => loadNode(n.id);
      nodes.appendChild(box);
    });
    lane.appendChild(label);
    lane.appendChild(nodes);
    canvas.appendChild(lane);
  });
  flow.edges.forEach((e) => {
    const note = document.createElement("div");
    note.className = "edge-note";
    const dashed = e.confidence < 1.0 ? " (inferred)" : "";
    note.textContent = `↳ ${e.kind} link · confidence ${e.confidence}${dashed}`;
    canvas.appendChild(note);
  });
}

async function loadNode(nodeId) {
  const node = await getJSON(`/projects/${PID}/flow-node?node_id=${encodeURIComponent(nodeId)}`);
  const ref = node.codeRef;
  document.getElementById("popup-title").textContent = `${node.label}  ·  ${node.kind}`;
  document.getElementById("popup-ref").textContent = `${ref.repo}/${ref.file}:${ref.line}`;
  document.getElementById("popup-snippet").textContent = ref.snippet;
  document.getElementById("popup").classList.remove("hidden");
}

document.getElementById("popup-close").onclick = () =>
  document.getElementById("popup").classList.add("hidden");
document.getElementById("popup").onclick = (e) => {
  if (e.target.id === "popup") e.target.classList.add("hidden");
};

init();
```

- [ ] **Step 6: Run tests**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_dashboard.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add DocuProj/dashboard/index.html DocuProj/dashboard/styles.css DocuProj/dashboard/app.js DocuProj/tests/test_dashboard.py
git commit -m "feat(dashboard): endpoint list, swimlane flow, and step popup"
```

---

### Task 3: Full-suite check + launch validation

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest -q`
Expected: PASS — Plan 1-5 (50) + Plan 6 (4) = 54 tests.

- [ ] **Step 2: Launch against the real EDFX model and smoke-check**

Seed the store with a parse→link of the cloned repos, start uvicorn, and confirm the dashboard page + data endpoints respond. Run (from `DocuProj/`):

```bash
.\.venv\Scripts\python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/app/').status)"
```

(Start the server first in another shell: `.\.venv\Scripts\python -m uvicorn serve_demo:app` where `serve_demo.py` builds the app with a seeded store — created ad hoc for validation, not committed.)

Expected: `/app/` returns 200; opening it in a browser shows the endpoint list, a swimlane flow on click, and a code-ref popup on node click.

- [ ] **Step 3: Commit** (if any validation-only helper is kept, otherwise skip)

---

## Self-Review

**Spec coverage (Dashboard, §3 / §9, reqs 6-8):**
- Endpoint list (req 6) — Task 2 sidebar ✓
- Cross-repo swimlane flow, one lane per repo (req 7, §2 swimlane decision) — Task 2 `renderSwimlanes` ✓
- Step popup with description + code lines (req 8) — Task 2 modal with `codeRef` ✓
- Confidence surfaced (deterministic vs inferred) — Task 2 edge note ✓
- Served locally, single-user (spec §11 scope) — Task 1 StaticFiles ✓
- Deferred (correctly): in-dashboard Mermaid render + on-request diagram/writeup/export buttons (reqs 9-11); precise SVG arrow geometry between lanes (MVP uses lane grouping + edge notes); React migration (chosen no-build for MVP).

**Placeholder scan:** No TBD/TODO in shipped files. Task 3 is verification-only and clearly labeled; any seed/serve helper is explicitly ad-hoc and uncommitted.

**Type consistency:** `app.js` reads the exact camelCase API contract (`codeRef`, `endpointId`, node `kind`/`label`/`repo`, edge `confidence`/`kind`) the API emits with `by_alias=True`. Element ids (`endpoint-list`, `flow-canvas`, `popup`, `popup-ref`, `popup-snippet`) match between `index.html`, `styles.css`, `app.js`, and the structure tests.
