# EDFX / Tessera entity categorization & financials rules

Domain reference for classifying entities and interpreting the financials-process
columns. Captured from the business owner; verify against data before relying on it
for a new context (see the caution note).

## Entity lifecycle & the `entity` table

- When a user in a **tenant** adds entities to their profiles, they are inserted into
  the **`entity`** table, associated with that `tenant_id`.
- **One row per entity per tenant** — an entity appears **once per tenant**. The same
  external entity added under two tenants is two `entity` rows (one each).
- The **`entity.id`** (surrogate PK) is the reference used by other tables:
  `entity_custom_data`, `entity_portfolio_link`, `entity_scorecard`,
  `entity_parent_group_support`, etc. (join on `entity.id = <table>.entity_id`).

## `data_type`, `custom_id`, and `financials_type`

`entity.data_type` is `"Public"` or `"Private"`. Combined with `entity.custom_id` and
`entity_custom_data.financials_type` it determines the entity kind:

- **`custom_id IS NULL` + `financials_type = 'moodys'`** → flat **prescored / pure
  Private or Public** entity. These have **NULL** `entity_custom_data.financials_process_id`
  and **NULL** `financials_process_status` (no custom financials process ran).
- **`custom_id IS NULL` + `financials_type = 'custom'`** → **customized prescored**
  entity → it **has** a `financials_process_id` (a custom financials process ran).

**Implication for stuck-financials / refresh work:** a NULL `financials_process_status`
almost always means a standard `moodys`-financials entity with no custom process — NOT
a failed one. That's why the ~10M private NULL-status rows must be excluded from any
"stuck financials" retry (they were never candidates).

## Categorization summary (as stated by the owner)

| Kind | Rule |
|---|---|
| **Public** | `data_type = 'Public'` and `custom_id IS NULL` |
| **Private** | `data_type = 'Private'` and `custom_id IS NULL` |
| **Custom** | `data_type = 'Private'` and `custom_id IS NOT NULL` |
| **Public / Private Customized** | see the detection query below |

> ✅ **Matches the refresh scripts.** `Day2Day_Utillites/refresh_stale_non_public_entities.py`
> scopes its two modes the same way: `custom` = `data_type='Private' AND custom_id IS NOT NULL`,
> `private` = `data_type='Private' AND custom_id IS NULL`.

## "Public / Private Customized" detection query

An entity (with `custom_id IS NULL`, non-cap) is **customized** when it has any of:
an **active scorecard**, **custom financials**, a **custom profile**
(country/state/industry/target_cdt), a **custom peer group**, or **active parent
group support (PGS)**. The query below is for **Private**; for **Public** swap
`e.data_type = 'Public'`.

```sql
select
    distinct e.tenant_id,
    e.external_id,
    e.entity_data ->> 'isBank'                                          as is_bank,
    (es.entity_id IS not null and es.apply_pd = true)                   as has_active_score_card,
    (coalesce(ecd.financials_type, 'moodys') != 'moodys')               as has_custom_financials,
    (coalesce(ecd.country, ecd.state, ecd.industry, NULL) IS not null
        or ecd.target_cdt is not null)                                  as has_custom_profile,
    (ecd.peer_group_id is not null)                                     as has_custom_peer_group,
    (epgs.entity_id IS not null and epgs.apply_pd = true)               as has_active_pgs
from entity e
LEFT JOIN entity_custom_data ecd            on e.id = ecd.entity_id
LEFT JOIN entity_scorecard es               ON e.id = es.entity_id
LEFT JOIN entity_parent_group_support epgs  ON e.id = epgs.entity_id
where (e.data_type is null or e.data_type = 'Private')      -- Public: e.data_type = 'Public'
  and e.custom_id is null
  AND (  (es.entity_id IS not null and es.apply_pd = true)
      OR (ecd.financials_type is null or ecd.financials_type <> 'custom')
      OR (ecd.country is not null
          or ecd.state is not null
          or ecd.industry is not null
          or ecd.peer_group_id IS not null
          or ecd.target_cdt is not null)
      OR (epgs.entity_id IS not null and epgs.apply_pd = true)
      )
  AND e.is_cap_entity = false;
```

Notes:
- The overlay/PGS process ids and `apply_pd` flags live in **`entity_scorecard`** and
  **`entity_parent_group_support`** (NOT in `entity_custom_data`).
- `is_cap_entity = false` excludes CAP entities.
- Peer-driven entities (`peer_group_id` set, confidence `PN-P…`, `entity_data.isPeerDriven`)
  have a PD bounded by their peer group's latest metric month — relevant when validating
  `pd_last_known_date` (the client report's "Calculation Date").
