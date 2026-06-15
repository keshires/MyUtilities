# July 2026 File Processing Forecast
## Leadership Report — Early-Month Inflow Model (Days 1–10)

**Prepared from:** Data team queue snapshots, June 1–8, 2026  
**Report date:** June 8, 2026  
**Processing rate window:** **Jun 5, 4:00 PM → Jun 8** (latest snapshot)  
**Scope:** Files arrive during **days 1–10 of each month**; processing continues through the full month.

---

## Executive Summary

| Item | Value |
|------|------:|
| **June carryover backlog** (as of Jun 8, latest snapshot) | **82,246 files** |
| **Projected July 1–10 new intake** | ~1.8M – 2.0M files |
| **Total July workload (carryover + Jul 1–10 intake)** | **~2.05M files** |
| **Demonstrated processing rate** (Jun 5 4 PM – Jun 8) | **~466K files/day** |
| **Peak queue during July (base case)** | **~1.03M on Jul 3** |
| **Expected time to clear July 1–10 workload** | **By Jul 10** at base rate |
| **July processing capacity (31 days at base rate)** | ~14.4M files (well above expected intake) |

**Bottom line for leadership:** Using the **actual processing rate measured from Jun 5 4 PM through Jun 8** (~466K files/day), the pipeline clears all July 1–10 intake plus the **82K June carryover by Jul 10**. The critical day is **Jul 3** when concurrent queue peaks at **~1.03M**. June backlog is **95% cleared** (down from 1.21M at Jun 5 4 PM to 82K on Jun 8).

---

## How We Measured This

### Data source
Point-in-time **queue snapshots** from the data team, grouped by:
- **Data date** — the business date on the file (e.g., `2026-06-02`)
- **Source** — `cca` (primary) or `open_search_ingestion` (secondary)

### Key metrics

| Metric | Definition |
|--------|------------|
| **Inflow** | Queue count **increases** for the same data date between snapshots (files landing) |
| **Reduction / processed** | Queue count **decreases** or a data date **drops off** the queue (pipeline consumed files) |
| **Processing rate** | Total reduction ÷ elapsed hours across the measurement window |
| **Peak backlog** | Highest pending count for a data date — proxy for that day's total intake |

### Rate calculation window
**Jun 5, 4:00 PM → Jun 8** — the period when the pipeline was actively draining with minimal backlog build-up. This replaces the earlier Jun 5–7 estimate and includes the latest Jun 8 snapshot.

| Metric | Jun 5 4 PM – Jun 8 |
|--------|-------------------:|
| Duration | ~64 hours (through Jun 8 ~8 AM) |
| Files processed | **1,242,422** |
| New inflow during window | 112,908 |
| Net queue reduction | 1,211,760 → 82,246 (**−93%**) |
| **Processing rate** | **465,908 files/day** |

> If the Jun 8 snapshot was taken later in the day, the rate is slightly lower (~414K–439K/day). All July scenarios below remain cleared by Jul 10.

---

## June Status — As of Jun 8 (Latest Snapshot)

| Data date | Source | Count | Status |
|-----------|--------|------:|--------|
| 2026-06-08 | CCA | 3,738 | Just arrived |
| 2026-06-07 | CCA | 76,687 | In progress (was 109,170 on Jun 7 PM) |
| 2026-06-04 | CCA | 51 | Nearly cleared |
| 2026-06-04 | open_search_ingestion | 1,770 | Nearly cleared |
| **Total queue** | | **82,246** | |

### What was processed Jun 7 PM → Jun 8

| Data date | Source | Before | After | Processed |
|-----------|--------|-------:|------:|----------:|
| 2026-06-03 | CCA | 59,233 | cleared | ~59,233 |
| 2026-06-07 | CCA | 109,170 | 76,687 | 32,483 |
| 2026-06-04 | CCA | 694 | 51 | 643 |
| 2026-06-04 | open_search_ingestion | 2,528 | 1,770 | 758 |
| 2026-06-08 | CCA | — | 3,738 | +3,738 inflow |

### Processing throughput — Jun 5 4 PM through Jun 8

| Period | Duration | Files processed | Rate |
|--------|----------|----------------:|-----:|
| Jun 5 4 PM → Jun 5 11 PM | 7 hrs | 205,453 | 29K/hr |
| Jun 5 11 PM → Jun 6 8 AM | 9 hrs | 395,616 | **44K/hr** |
| Jun 6 8 AM → Jun 6 7:30 PM | 11.5 hrs | 357,687 | 31K/hr |
| Jun 6 7:30 PM → Jun 7 10:30 PM | 27 hrs | 190,549 | 7K/hr |
| Jun 7 10:30 PM → Jun 8 | ~9.5 hrs | 93,117 | 10K/hr |
| **Full window total** | **~64 hrs** | **1,242,422** | **~466K/day** |

| Rate basis | Files/day |
|------------|----------:|
| **Base (Jun 5 4 PM – Jun 8)** | **465,908** |
| Conservative (later Jun 8 snapshot) | 414,141 – 438,502 |
| Stress test (70% of base) | 326,135 |

---

## July 2026 Forecast — Days 1–10 Inflow Model

### Projected intake by data date

Using June days 1–8 as the direct analog. Unobserved days use a **50K/day placeholder**.

| Data date (Jul) | Day | Basis (Jun analog) | Projected intake |
|-----------------|----:|--------------------|----------------:|
| 2026-07-01 | 1 | Jun 1 peak | 96,000 |
| 2026-07-02 | 2 | Jun 2 peak | 814,000 |
| 2026-07-03 | 3 | Jun 3 peak | 686,000 |
| 2026-07-04 | 4 | Jun 4 peak | 8,000 |
| 2026-07-05 | 5 | No Jun data — estimate | 50,000 |
| 2026-07-06 | 6 | No Jun data — estimate | 50,000 |
| 2026-07-07 | 7 | Jun 7 peak | 109,000 |
| 2026-07-08 | 8 | Jun 8 first seen (~3.7K; plan 50K) | 50,000 |
| 2026-07-09 | 9 | No Jun data — estimate | 50,000 |
| 2026-07-10 | 10 | No Jun data — estimate | 50,000 |
| | | **Jul 1–10 subtotal** | **1,963,000** |
| Carryover from June | | Jun 8 remaining queue | **82,246** |
| | | **Total July workload** | **~2,045,000** |

---

## July Processing Timeline

Assumes inflow Jul 1–10 and processing at the **Jun 5 4 PM – Jun 8 measured rate** (466K/day), running in parallel.

### Day-by-day queue simulation — base case (466K files/day)

| Date | Daily inflow | End-of-day queue |
|------|-------------:|-----------------:|
| Start | — | **82,246** (Jun 8 carryover) |
| Jul 1 | +96,000 | **0** |
| Jul 2 | +814,000 | 348,092 |
| **Jul 3** | **+686,000** | **568,184** (intraday peak **~1,034,092**) |
| Jul 4 | +8,000 | 110,276 |
| Jul 5 – Jul 9 | +50,000/day | draining |
| **Jul 10** | +50,000 | **0 — fully cleared** |

### Scenario comparison

| Processing rate | Basis | Peak queue | Peak day | Cleared by |
|-----------------|-------|-----------:|----------|------------|
| Stress (70%) | 326K/day | 1,173,865 | Jul 3 | **Jul 10** |
| Low | 414K/day (Jun 8 ~4 PM) | 1,085,859 | Jul 3 | **Jul 10** |
| Conservative | 439K/day (Jun 8 ~12 PM) | 1,061,498 | Jul 3 | **Jul 10** |
| **Base** | **466K/day (Jun 5 4PM–Jun 8)** | **1,034,092** | **Jul 3** | **Jul 10** |

> **Critical window:** Jul 2–4 when heavy batches (814K + 686K) overlap. Monitor queue daily during this period.

---

## July 2026 — Leadership KPI Summary

| KPI | Target / forecast |
|-----|-------------------|
| **Inflow window** | Jul 1 – Jul 10 |
| **Expected new files (Jul 1–10)** | **~1.8M – 2.0M** |
| **June backlog at start of July** | **82K** (clears Jul 1 at base rate) |
| **Peak queue during July** | **~1.03M on Jul 3** |
| **Processing rate (measured)** | **466K files/day** (Jun 5 4 PM – Jun 8) |
| **Processing completion** | **By Jul 10** |
| **Pipeline utilization (Jul 1–10)** | ~44% (2.05M workload ÷ 4.66M capacity in 10 days) |
| **Headroom Jul 11–31** | ~9.8M files of unused capacity |

### Recommended planning numbers

| Use case | Number |
|----------|-------:|
| **Budget / capacity planning** | **~2.0M files** in Jul 1–10 window |
| **Peak concurrent queue** | **~1.0M on Jul 3** — monitor Jul 2–4 |
| **Stakeholder commitment** | Jul 1–10 data cleared by **Jul 10** |
| **Conservative commitment (buffer)** | Cleared by **Jul 11–12** if rate drops to ~326K/day |
| **Required avg rate over full July** | ~205K/day vs **466K proven** |

---

## Methodology Notes (for Q&A)

1. **Why Jun 5 4 PM – Jun 8 for the rate?** This is the longest continuous drain window with the latest data. It captures peak overnight throughput (Jun 5–6) and recent sustained processing through Jun 8.

2. **Why is the rate slightly lower than the earlier Jun 5–7 estimate (506K)?** Including Jun 7 PM – Jun 8 adds a slower overnight interval (~10K/hr) while Jun 7 and Jun 8 batches were still arriving. The updated rate is more conservative and better reflects current conditions.

3. **Jun 8 carryover is 82K, not 172K.** Jun 3 data cleared entirely; Jun 4 nearly done; Jun 7 partially processed (77K remaining).

4. **Days 1–10 inflow assumption unchanged.** All monthly batches arrive calendar days 1–10 per business rule.

5. **Jun 8 snapshot time:** Rate calculated assuming snapshot ~Jun 8 8 AM (~64 hrs from Jun 5 4 PM). If snapshot was later, rate is 414K–439K/day — July forecast still clears by Jul 10.

---

*Source data: queue snapshots from data team, June 1–8, 2026. Latest snapshot: Jun 8.*
