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
