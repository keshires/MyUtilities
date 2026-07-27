import refresh_stale_non_public_entities as rf


# --- mode resolution -------------------------------------------------------

def test_private_customized_mode():
    m = rf.resolve_entity_mode("private-customized")
    assert m.payload_type == "non-public-customized"
    assert m.data_type == "Private"
    assert m.signal_mode == "require"
    assert m.custom_id_clause == "custom_id IS NULL"


def test_public_customized_mode():
    m = rf.resolve_entity_mode("public-customized")
    assert m.payload_type == "public-customized"
    assert m.data_type == "Public"
    assert m.signal_mode == "require"


def test_customized_aliases():
    assert rf.resolve_entity_mode("private_customized").name == "private-customized"
    assert rf.resolve_entity_mode("public_customized").name == "public-customized"


def test_mode_payloads_and_signal_modes():
    assert rf.resolve_entity_mode("custom").payload_type == "non-public-customized"
    assert rf.resolve_entity_mode("custom").signal_mode == "none"
    assert rf.resolve_entity_mode("private").payload_type == "non-public"
    assert rf.resolve_entity_mode("private").signal_mode == "exclude"


# --- customized query shape ------------------------------------------------

def test_private_customized_query_shape():
    m = rf.resolve_entity_mode("private-customized")
    q = rf.stale_entities_query(m, stale_date_column="pd_last_known_date",
                                financial_max_age_years=0)
    assert "LEFT JOIN public.entity_custom_data ecd ON ecd.entity_id = e.id" in q
    assert "LEFT JOIN public.entity_scorecard es ON es.entity_id = e.id" in q
    assert "LEFT JOIN public.entity_parent_group_support epgs ON epgs.entity_id = e.id" in q
    assert "e.data_type = 'Private'" in q
    assert "e.custom_id IS NULL" in q
    assert "e.is_cap_entity = false" in q
    assert "ecd.peer_group_id IS NOT NULL" in q                   # signal present
    assert "e.pd_last_known_date" in q                            # staleness column
    assert "e.tenant_id <> ALL($2::text[])" in q                  # exclude form, $2
    assert "financialStmtDate" not in q                           # financial filter off (age=0)


def test_public_customized_query_uses_public_data_type():
    m = rf.resolve_entity_mode("public-customized")
    q = rf.stale_entities_query(m, stale_date_column="pd_last_known_date",
                                financial_max_age_years=0)
    assert "e.data_type = 'Public'" in q


def test_customized_count_query():
    m = rf.resolve_entity_mode("private-customized")
    q = rf.stale_entities_count_query(m, stale_date_column="pd_last_known_date",
                                      financial_max_age_years=0)
    assert q.lstrip().startswith("SELECT COUNT(DISTINCT e.external_id)")


def test_customized_tenant_scope_uses_include_form():
    m = rf.resolve_entity_mode("private-customized")
    q = rf.stale_entities_query(m, tenant_id="TENANT1",
                                stale_date_column="pd_last_known_date",
                                financial_max_age_years=0)
    assert "e.tenant_id = $2::text" in q


# --- regression: custom SQL stays flat/unchanged; private is refined ---------

def test_custom_mode_stays_flat_unchanged():
    q = rf.stale_entities_query(rf.resolve_entity_mode("custom"), stale_date_column="pd_last_known_date")
    assert "LEFT JOIN" not in q                 # no joins
    assert "is_cap_entity" not in q             # custom left byte-identical
    assert "FROM public.entity\n" in q          # flat, unaliased FROM
    assert "custom_id IS NOT NULL" in q


def test_private_mode_refined_excludes_customized():
    q = rf.stale_entities_query(rf.resolve_entity_mode("private"), stale_date_column="pd_last_known_date")
    assert "LEFT JOIN public.entity_custom_data" in q          # now joined
    assert "e.custom_id IS NULL" in q
    assert "e.is_cap_entity = false" in q
    assert "NOT COALESCE(" in q                                # excludes the customization signal
    assert "e.data_type = 'Private'" in q
