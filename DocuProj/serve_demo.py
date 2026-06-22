"""Demo server: analyze the cloned EDFX repos (4) and serve the dashboard."""

from engine import Project, RepoRef, create_app, link, parse

WS = ".workspace/edfx-flow"
SPECS = [
    ("edfx-app-ui", "angular", "main"),
    ("edfx-api", "python", "master"),
    ("edfx_entity_api", "python", "main"),
    ("edfx-client-financials-api", "python", "main"),
]
facts = []
for folder, lang, _ in SPECS:
    print(f"Parsing {folder} ({lang})…")
    facts.append(parse(f"{WS}/{folder}", lang, repo=folder))
project = Project(
    id="edfx-flow",
    name="EDFX Flow",
    repos=[RepoRef(url="x", folder=f, branch=b, sha=f) for f, _, b in SPECS],
)
model = link(facts, project)
print(f"Analyzed: {len(model.endpoints)} endpoints, {len(model.flows)} flows. Dashboard at /app/")
app = create_app(projects_dir="projects", workspace=".workspace", store={"edfx-flow": model})
