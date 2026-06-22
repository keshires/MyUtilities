let PID = null;
let CURRENT_FLOW = null;

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
  document.getElementById("flow-title").textContent = `${ep.method} ${ep.path}`;
  const canvas = document.getElementById("flow-canvas");
  canvas.innerHTML = "";
  try {
    CURRENT_FLOW = await getJSON(
      `/projects/${PID}/flow?endpoint_id=${encodeURIComponent(ep.id)}`
    );
  } catch (e) {
    CURRENT_FLOW = null;
    canvas.innerHTML = "<p class='empty'>No cross-repo flow found for this endpoint.</p>";
    return;
  }
  renderSwimlanes(CURRENT_FLOW);
}

const KIND_RANK = { ui: 0, outbound: 1, fn: 2, route: 3 };

function renderSwimlanes(flow) {
  const canvas = document.getElementById("flow-canvas");
  canvas.innerHTML = "";

  // Group nodes by repo, then order lanes: source repos (ui/outbound) left, route repo right.
  const byRepo = new Map();
  flow.nodes.forEach((n) => {
    if (!byRepo.has(n.repo)) byRepo.set(n.repo, []);
    byRepo.get(n.repo).push(n);
  });
  const laneRank = (nodes) => Math.min(...nodes.map((n) => KIND_RANK[n.kind] ?? 9));
  const repos = [...byRepo.keys()].sort((a, b) => laneRank(byRepo.get(a)) - laneRank(byRepo.get(b)));

  const lanes = document.createElement("div");
  lanes.className = "lanes";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "edges");
  svg.innerHTML =
    '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">' +
    '<path d="M0,0 L7,3 L0,6 Z" fill="#dd6b20"/></marker>' +
    '<marker id="arrow-dim" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">' +
    '<path d="M0,0 L7,3 L0,6 Z" fill="#a0aec0"/></marker></defs>';

  const nodeEls = new Map();
  repos.forEach((repo) => {
    const lane = document.createElement("div");
    lane.className = "lane";
    const head = document.createElement("div");
    head.className = "lane-head";
    head.textContent = repo;
    lane.appendChild(head);
    byRepo.get(repo).forEach((n) => {
      const card = document.createElement("div");
      card.className = `node kind-${n.kind}`;
      card.textContent = n.label;
      card.title = `${n.kind} · ${n.repo}`;
      card.onclick = () => loadNode(n.id);
      lane.appendChild(card);
      nodeEls.set(n.id, card);
    });
    lanes.appendChild(lane);
  });

  lanes.appendChild(svg);
  canvas.appendChild(lanes);
  drawEdges(flow, lanes, svg, nodeEls);
}

function drawEdges(flow, container, svg, nodeEls) {
  // remove any previously drawn paths (keep <defs>)
  svg.querySelectorAll("path.edge").forEach((p) => p.remove());
  const base = container.getBoundingClientRect();
  svg.setAttribute("width", container.scrollWidth);
  svg.setAttribute("height", container.scrollHeight);
  flow.edges.forEach((e) => {
    const from = nodeEls.get(e.from);
    const to = nodeEls.get(e.to);
    if (!from || !to) return;
    const a = from.getBoundingClientRect();
    const b = to.getBoundingClientRect();
    const x1 = a.right - base.left;
    const y1 = a.top - base.top + a.height / 2;
    const x2 = b.left - base.left;
    const y2 = b.top - base.top + b.height / 2;
    const mx = (x1 + x2) / 2;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`);
    const inferred = e.confidence < 1.0;
    path.setAttribute("class", inferred ? "edge inferred" : "edge");
    path.setAttribute("marker-end", inferred ? "url(#arrow-dim)" : "url(#arrow)");
    svg.appendChild(path);
  });
}

window.addEventListener("resize", () => {
  if (!CURRENT_FLOW) return;
  const lanes = document.querySelector("#flow-canvas .lanes");
  const svg = lanes && lanes.querySelector("svg.edges");
  if (!lanes || !svg) return;
  const nodeEls = new Map();
  CURRENT_FLOW.nodes.forEach((n) => {
    const card = [...lanes.querySelectorAll(".node")].find((c) => c.textContent === n.label && c.classList.contains(`kind-${n.kind}`));
    if (card) nodeEls.set(n.id, card);
  });
  drawEdges(CURRENT_FLOW, lanes, svg, nodeEls);
});

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
