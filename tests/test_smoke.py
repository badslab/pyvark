"""Smoke tests for ``vark.AnthiveClient`` — round-trip against a live
ant-serve.

Skipped unless ``ANTHIVE_TEST_URL`` is set, so they don't break offline
or CI runs without a server. Optionally use ``ANTHIVE_TEST_USER`` /
``ANTHIVE_TEST_PASSWORD`` for HTTP Basic, and set
``ANTHIVE_TEST_VERIFY=0`` for self-signed TLS endpoints.

Run with::

    ANTHIVE_TEST_URL=https://my.anthive/api \\
    ANTHIVE_TEST_USER=user ANTHIVE_TEST_PASSWORD=pass \\
    ANTHIVE_TEST_VERIFY=0 \\
        uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_smoke.py -v

The tests are read-only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vark
from vark import AnthiveClient


_BASE_URL = os.environ.get('ANTHIVE_TEST_URL')

pytestmark = pytest.mark.skipif(
    not _BASE_URL,
    reason='set ANTHIVE_TEST_URL to a running ant-serve to enable smoke tests',
)


@pytest.fixture(scope='module')
def client():
    auth = None
    user = os.environ.get('ANTHIVE_TEST_USER')
    password = os.environ.get('ANTHIVE_TEST_PASSWORD')
    if user and password:
        auth = (user, password)
    verify = True
    if os.environ.get('ANTHIVE_TEST_VERIFY', '1') in ('0', 'false', 'no'):
        verify = False
        import warnings
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            warnings.filterwarnings('ignore')
    return AnthiveClient(_BASE_URL, auth=auth, verify=verify)


@pytest.fixture(scope='module')
def db_with_de(client):
    for db in client.get_databases():
        try:
            studies = client.list_de_studies(db['id'])
        except Exception:
            continue
        if studies:
            return db['id'], studies[0]
    pytest.skip('no dataset on this server has DE data ingested')


# ── core surfaces ────────────────────────────────────────────────────────────


def test_health_with_latency_telemetry(client):
    h = client.get_health()
    assert h.get('status') == 'healthy'
    assert h.get('databases', 0) >= 0
    # API 2.5+ latency telemetry — n_samples is None until traffic warms.
    assert 'mean_response_ms' in h
    assert 'p50_response_ms' in h
    assert 'n_samples' in h


def test_version(client):
    v = client.get_version()
    assert v.get('version')
    for key in ('plot_geoms', 'plot_output_formats', 'deprecated_endpoints'):
        assert key in v


def test_changelog_on_2_3(client):
    v = client.get_version()
    if v.get('changelog_url') is None:
        pytest.skip('pre-2.3 server — no /changelog endpoint')
    md = client.get_changelog()
    assert 'Anthive' in md or 'Changelog' in md.lower()


def test_databases_listed(client):
    dbs = client.get_databases()
    assert isinstance(dbs, list)


def test_get_group_404(client):
    """API 2.5+: unknown group_id should 404 cleanly, not 500."""
    import requests
    v = client.get_version()
    if tuple(int(part) for part in v.get('version', '0.0.0').split('.')[:2]) < (2, 5):
        pytest.skip('pre-2.5 server — /groups/{id} not present')
    with pytest.raises(requests.HTTPError) as ei:
        client.get_group('ZZZ_DOES_NOT_EXIST')
    assert ei.value.response.status_code == 404


# ── DE data flow ────────────────────────────────────────────────────────────


def test_list_de_studies(client, db_with_de):
    db_id, _study = db_with_de
    studies = client.list_de_studies(db_id)
    assert isinstance(studies, list) and len(studies) >= 1
    for key in ('study_id', 'method', 'n_rows', 'n_terms', 'n_contrasts'):
        assert key in studies[0]


def test_get_de_rows(client, db_with_de):
    db_id, study = db_with_de
    detail = client.get_de_study(db_id, study['study_id'])
    term = detail['terms'][0]['term']
    contrasts = client.list_de_contrasts(db_id, study['study_id'], term)
    contrast = contrasts[0]['contrast']
    rows = client.get_de_rows(db_id, study['study_id'], term, contrast,
                              limit=5)
    assert isinstance(rows, list)
    if rows:
        for key in ('gene_name', 'pvalue', 'padj'):
            assert key in rows[0]


def test_get_de_by_gene_unknown(client, db_with_de):
    db_id, _ = db_with_de
    out = client.get_de_by_gene(db_id, 'NOPE_THIS_GENE_DOES_NOT_EXIST')
    assert out == []


# ── plot endpoint smoke ─────────────────────────────────────────────────────


def test_get_plot_captures_caption_from_live_server(client):
    """End-to-end check that the X-Plot-Caption header is captured and
    surfaced. With API 2.7.2 every image-format /plot response carries
    one — empty caption => server downgrade or new geom."""
    for db in client.get_databases():
        info = client.get_database_info(db['id'])
        if info.get('embeddings'):
            result = client.get_plot(
                db['id'], 'scatter', dpi=72, width=4, height=3,
            )
            assert result['format'] == 'png'
            assert result['bytes']
            # API 2.7.2 server should emit a caption.
            assert isinstance(result['caption'], str)
            return
    pytest.skip('no dataset with embeddings on this server')


def test_get_plot_csv_export(client):
    """API 2.6 plot-data export — /plot/<geom>?format=csv returns the
    underlying dataframe."""
    for db in client.get_databases():
        info = client.get_database_info(db['id'])
        if info.get('embeddings'):
            result = client.get_plot(
                db['id'], 'scatter', format='csv',
                width=4, height=3, dpi=72,
            )
            # Pre-2.6 servers may 400 — accept missing format silently
            # only when the API_VERSION clearly predates 2.6.
            assert b',' in result['bytes'] or b'\n' in result['bytes']
            return
    pytest.skip('no dataset with embeddings on this server')


def test_module_score_listing(client):
    """list_module_scores returns a discovery dict with a
    ``scored_genesets`` list (possibly empty)."""
    for db in client.get_databases()[:3]:
        items = client.list_module_scores(db['id'])
        assert isinstance(items, dict)
        assert 'scored_genesets' in items
        assert isinstance(items['scored_genesets'], list)
        return
    pytest.skip('no databases available')


# ── API 2.44.0: facet scopes and replication tiers (read-only) ──────────────


def _needs_2_44(client):
    version = client._get('/').get('version', '0')
    if tuple(int(part) for part in version.split('.')[:2]) < (2, 44):
        pytest.skip(f'server {version} predates API 2.44.0')


def test_api_target_matches_server_major_minor(client):
    _needs_2_44(client)
    server = client._get('/')['version'].split('.')[:2]
    assert AnthiveClient.API_TARGET.split('.')[:2] == server


def test_dataset_rows_carry_facet_scope(client):
    _needs_2_44(client)
    rows = client.get_databases()
    scopes = {row.get('facet_scope') for row in rows}
    assert scopes <= set(AnthiveClient.FACET_SCOPES) | {None}
    for field in ('replicate_unit', 'disease_basis', 'control_basis'):
        assert field in rows[0]


def test_facet_gene_effects_by_scope(client):
    _needs_2_44(client)
    card = client.get_facet_gene_effects('braak', 'TREM2',
                                         cell_type='microglia')
    assert card['scope'] == 'human_postmortem'
    entry = card['replication'][0]
    for field in ('r_value', 'replicated', 'effect_gate_passed', 'r_treat',
                  'replicated_effect', 'n_small', 'k_treat'):
        assert field in entry
    assert entry['replicated'] == (entry['r_value'] < 0.05)
    xenograft = client.get_facet_gene_effects(
        'app_nlgf', 'TREM2', scope='xenograft_human_in_mouse')
    assert xenograft['scope'] == 'xenograft_human_in_mouse'


def test_gene_facet_effects_has_by_scope_and_all_tested_facets(client):
    _needs_2_44(client)
    original_timeout = client.timeout
    client.timeout = 600  # cold server: reads every facet result file
    try:
        result = client.get_gene_facet_effects('TREM2')
    finally:
        client.timeout = original_timeout
    assert set(result['facets']) == set(AnthiveClient.TESTED_FACETS)
    assert set(result['by_scope']) <= set(AnthiveClient.FACET_SCOPES)
    assert 'strongest_facet' in result


def test_recurring_genes_counts_and_gate(client):
    _needs_2_44(client)
    result = client.get_facet_recurring_genes('braak', n=5,
                                              effect_gate=True)
    assert result['n_replicated'] >= result['n_effect_gate'] >= 0
    for row in result['rows']:
        assert row['replicated'] and row['effect_gate_passed']


def test_retired_scope_is_a_400(client):
    import requests
    _needs_2_44(client)
    with pytest.raises(requests.HTTPError) as excinfo:
        client.get_facet_gene_effects('braak', 'TREM2',
                                      scope='mouse_in_vivo')
    assert excinfo.value.response.status_code == 400


def test_facet_detail_and_tests_with_scope(client):
    _needs_2_44(client)
    detail = client.get_facet('ant_age', scope='human_postmortem')
    assert detail['scope'] == 'human_postmortem'
    tests = client.get_facet_tests_across_datasets(
        'age', top_genes=0, scope='all')
    assert tests['rows']
    assert {row['facet_scope'] for row in tests['rows']} <= set(
        AnthiveClient.FACET_SCOPES)


def test_module_variability_scope(client):
    _needs_2_44(client)
    result = client.get_module_variability(
        scope='xenograft_human_in_mouse', limit=5)
    assert result['rows'] is not None


# ── help API (REST API 2.44.0) ──────────────────────────────────────────────


def test_help_roundtrip(client):
    _needs_2_44(client)
    index = client.get_help()
    assert index['topics'] and index['glossary']
    topic = client.get_help_topic(index['topics'][0]['id'])
    assert topic['body'] and topic['title']
    term = client.get_glossary_term(index['glossary'][0]['slug'])
    assert term['definition']
    assert client.get_glossary()['terms']
    assert client.search_help('replicate unit')['matches']


def test_explain_live(client):
    _needs_2_44(client)
    assert client.explain('replicate unit').startswith('# ')
    assert '# Anthive help topics' in client.explain('')


def test_facet_tests_carry_help_topics(client):
    _needs_2_44(client)
    result = client.get_facet_recurring_genes('braak', n=1)
    assert 'facet-effects' in result['help_topics']
    for topic_id in result['help_topics']:
        assert client.get_help_topic(topic_id)['body']


# ── late 2.44.0: card trimming, strong tier, exclusion fields ───────────────


def test_gene_cards_trimmed_live(client):
    _needs_2_44(client)
    original_timeout = client.timeout
    client.timeout = 600
    try:
        result = client.get_gene_facet_effects(
            'TREM2', facet=['braak', 'age'], include_units=False)
    finally:
        client.timeout = original_timeout
    assert set(result['facets']) == {'braak', 'age'}
    for card in result['facets'].values():
        assert card['units'] == []
        assert 'n_units' in card and 'replication' in card


def test_age_top_rows_and_strong_tier_live(client):
    _needs_2_44(client)
    result = client.get_facet_recurring_genes('age', n=3)
    assert 'n_replicated_strong' in result
    for row in result['rows']:
        assert 'r_strong' in row and 'replicated_strong' in row
        assert 'persists_after_pathology_adjustment' in row


def test_facet_exclude_live(client):
    _needs_2_44(client)
    rows = client.get_databases()
    assert all('facet_exclude' in row for row in rows)
    excluded = [row for row in rows if row['facet_exclude']]
    assert all(row['facet_exclude_reason'] for row in excluded)
    if excluded:
        summary = client.get_facet_tests(excluded[0]['id'])
        assert summary['status'] == 'not_tested'
        assert summary['facet_exclude'] is True


# ── API 2.45.0: forest, paging, modules, donors, ranks (read-only) ─────────


def _needs_2_45(client):
    version = client._get('/').get('version', '0')
    if tuple(int(part) for part in version.split('.')[:2]) < (2, 45):
        pytest.skip(f'server {version} predates API 2.45.0')


def test_version_advertises_compatible_pyvark(client):
    _needs_2_45(client)
    assert 'compatible_pyvark' in client.get_version()


def test_forest_rows_live(client):
    _needs_2_45(client)
    card = client.get_facet_gene_effects('sex', 'XIST',
                                         cell_type='microglia',
                                         forest='anchors')
    entry = card['replication'][0]
    for field in ('call', 'nt_label', 'k_over_m', 'cohorts_label', 'forest',
                  'links'):
        assert field in entry
    assert entry['forest'] and 'anchor' in entry['forest'][0]


def test_top_genes_paging_live(client):
    _needs_2_45(client)
    first = client.get_facet_top_genes('sex', n=2)
    assert first['n_returned'] == len(first['rows']) <= 2
    assert 'headline' in first and 'n_matching' in first
    every = client.get_facet_top_genes('sex', n=20, fetch_all=True)
    assert len(every['rows']) == first['n_matching']
    assert every['has_more'] is False
    genes = [row['gene'] for row in every['rows']]
    assert genes[:2] == [row['gene'] for row in first['rows']]
    assert len(set(genes)) == len(genes)


def test_top_modules_and_overview_live(client):
    _needs_2_45(client)
    modules = client.get_facet_top_modules('sex', n=2)
    assert 'effect_gate_rule' in modules and 'effect_gate' not in modules
    for row in modules['rows']:
        for key in ('strict', 'r_strong', 'replicated_strong', 'r_treat',
                    'replicated_effect'):
            assert row.get(key) is None  # absent on 2.45.0 as released
    overview = client.get_facet_effects_overview('sex', n=2)
    assert 'headline' in overview and 'cell_types' in overview
    if modules['rows']:
        study, experiment, name = modules['rows'][0]['geneset_id'].split('/', 2)
        card = client.get_geneset_facet_effects(study, experiment, name,
                                                facet='sex')
        assert 'sex' in card['facets']
        assert 'effect_gate_rule' in card


def test_gene_detection_live(client):
    _needs_2_45(client)
    result = client.get_gene_detection('TREM2')
    assert result['gene'] == 'TREM2' and 'summary' in result


def test_donor_values_and_plot_live(client):
    _needs_2_45(client)
    values = client.get_facet_donor_values('sex', 'microglia', gene='XIST')
    assert values['units']
    unit = next(unit for unit in values['units'] if unit['available'])
    assert unit['donors'][0]['label'].startswith('D')
    single = client.get_facet_donor_values('sex', 'microglia', gene='XIST',
                                           db_id=unit['db_id'])
    assert {each['db_id'] for each in single['units']} == {unit['db_id']}
    plot = client.get_facet_donor_plot('sex', 'microglia', gene='XIST',
                                       fmt='svg')
    assert plot['mime'].startswith('image/svg')
    assert plot['caption']


def test_donor_variability_live(client):
    _needs_2_45(client)
    top = client.get_donor_variability_top(limit=3)
    assert 'celltype_group' in top and 'cell_type_group' not in top
    if top['rows']:
        gene = top['rows'][0]['gene']
        card = client.get_gene_donor_variability(gene)
        assert card['feature'] == gene and card['units']
    if top['cohorts']:
        db_id = top['cohorts'][0]['db_id']
        summary = client.get_database_donor_variability(db_id)
        assert summary['status'] == 'analysed'
        rows = client.get_database_donor_variability(
            db_id, 'gene', 'microglia', limit=3)
        assert len(rows['rows']) <= 3


def test_module_ranks_live(client):
    _needs_2_45(client)
    for db in client.get_databases():
        ranks = client.get_module_ranks(db['id'])
        if ranks['available'] and ranks['modules']:
            break
    else:
        pytest.skip('no dataset with per-cell module scores')
    module = ranks['modules'][0]
    rank = client.get_geneset_rank(module['study'], module['experiment'],
                                   module['name'], db_id=db['id'])
    assert rank['datasets'][0]['db_id'] == db['id']


def test_de_study_summary_live(client, db_with_de):
    _needs_2_45(client)
    db_id, study = db_with_de
    study_id = study.get('study_id') or study.get('id')
    summary = client.get_de_study_summary(db_id, study_id)
    assert 'contrasts' in summary and summary['padj_max'] == 0.05


def test_unknown_dataset_is_one_404_live(client):
    import requests
    _needs_2_45(client)
    with pytest.raises(requests.HTTPError) as excinfo:
        client.get_module_ranks('NO/SUCH')
    assert excinfo.value.response.status_code == 404
    assert excinfo.value.response.json()['detail'] == (
        "Database 'NO/SUCH' not found")


def test_apoe_carrier_alias_is_gone_live(client):
    import requests
    _needs_2_45(client)
    with pytest.raises(requests.HTTPError) as excinfo:
        client.get_facet_recurring_genes('apoe_carrier', n=1)
    assert excinfo.value.response.status_code in (400, 404)


# ── API 2.46.0: read-only dataset deposits ──────────────────────────────────


def test_deposit_routes_live(client):
    from vark import DatasetDepositError
    version = client._get('/').get('version', '0')
    if tuple(int(part) for part in version.split('.')[:2]) < (2, 46):
        pytest.skip(f'server {version} predates API 2.46.0')
    try:
        vocab = client.get_deposit_vocab()
    except DatasetDepositError as error:
        # Not a member of datasets_upload_groups, or deposits switched off.
        assert error.status in ('forbidden', 'disabled')
        with pytest.raises(DatasetDepositError):
            client.list_deposits()
        return
    assert 'caller' in vocab and 'limits' in vocab
    listing = client.list_deposits()
    assert 'deposits' in listing
    for deposit in listing['deposits'][:1]:
        status = client.get_deposit(deposit['deposit_id'])
        assert status['deposit_id'] == deposit['deposit_id']


def test_sidecar_module_score_is_queryable_live(client):
    _needs_2_45(client)
    for db in client.get_databases():
        listing = client.list_module_scores(db['id'])
        rows = [row for row in listing.get('scored_genesets', [])
                if row.get('storage') == 'scores_sidecar']
        if rows:
            break
    else:
        pytest.skip('no dataset with sidecar module scores')
    schema = client.analytics_schema(db['id'])
    assert schema['score_sidecar']['available'] is True
    result = client.analytics_query(db['id'], rows[0]['query_sql'], limit=5)
    assert result['columns'][0] == 'cell_name'
    assert result['row_count'] == rows[0]['stats']['n']
