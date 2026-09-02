# DocuProj Swimlane UI Redesign Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the row-and-text-note flow view with the **locked design** (brainstorm `flow-layout.html` Option A): left→right **lanes per repo**, color-coded node cards (ui/outbound/route), lane headers, and **SVG connector arrows** that cross lanes (dashed when confidence < 1.0). Popup step-detail stays.

**Architecture:** Frontend-only (`dashboard/app.js` + `styles.css`). `renderSwimlanes()` groups flow nodes by repo into ordered lane columns (sources left, route right), renders node cards, then draws an absolutely-positioned SVG overlay connecting each edge's from→to node using measured `getBoundingClientRect`. Data-driven, so deeper flows (Plan 7) render more lanes automatically.

**Tech Stack:** vanilla JS/CSS/SVG; pytest only confirms assets are served (rendering verified by launching).

## File Structure
```
DocuProj/dashboard/app.js      # renderSwimlanes() -> columns + SVG arrows
DocuProj/dashboard/styles.css  # lane columns, node colors by kind, headers, svg overlay
DocuProj/tests/test_dashboard.py  # (unchanged structural checks still pass)
```

---

### Task 1: Column swimlanes + colored nodes + lane headers

**Files:** Modify `dashboard/app.js`, `dashboard/styles.css`.

- [ ] **Step 1:** Rewrite `renderSwimlanes(flow)` in `app.js` to build ordered lane **columns** (one per repo; repos with a `ui`/`outbound` node first, the `route` repo last), each with a header (repo name) and stacked node cards (`node kind-<kind>` with `data-node-id`), clicking a card → `loadNode`.
- [ ] **Step 2:** Replace the `.lane`/`.edge-note` CSS with column-layout styles: `#flow-canvas` relative + horizontal scroll; `.lane` = column with `.lane-head`; `.node` cards colored by kind (ui=blue, outbound=orange, route=green); an `<svg class="edges">` overlay absolutely positioned over the canvas.
- [ ] **Step 3:** Verify assets still served — `.\.venv\Scripts\pytest tests/test_dashboard.py -q` (4 passing).
- [ ] **Step 4:** Commit — `feat(dashboard): cross-repo swimlane columns with color-coded nodes`.

### Task 2: SVG connector arrows

**Files:** Modify `dashboard/app.js`, `dashboard/styles.css`.

- [ ] **Step 1:** After laying out lanes, draw the edges: for each `flow.edges` entry, measure the from-node and to-node via `getBoundingClientRect` (relative to canvas), draw an SVG `path` (right-edge → left-edge) with an arrowhead marker; **dashed** stroke when `confidence < 1.0`. Redraw on window resize.
- [ ] **Step 2:** Add arrow/marker CSS; ensure the SVG overlay doesn't capture clicks (`pointer-events:none`).
- [ ] **Step 3:** Full suite — `.\.venv\Scripts\pytest -q` (all pass).
- [ ] **Step 4:** Commit — `feat(dashboard): SVG cross-lane connector arrows (dashed = inferred)`.

### Task 3: Relaunch demo + validate

- [ ] Restart the demo server, load `/app/`, click a financials endpoint, confirm: lanes per repo, colored nodes, connecting arrow(s), popup on click. (Visual check — pytest can't assert rendering.)

## Self-Review
- Locked design coverage: left→right lanes ✓ (Task 1), color-coded nodes ✓, lane headers ✓, cross-lane arrows ✓ (Task 2), popup retained ✓.
- Data-driven: renders whatever depth the model has (UI→gateway, UI→financials, and more as linking improves).
- No placeholders; frontend rendering validated by launch (Task 3), structural serving by pytest.
