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
    assert client._get('/')['version'].startswith('2.44')
    assert AnthiveClient.API_TARGET.startswith('2.44')


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
    result = client.get_facet_recurring_genes('braak', n=5)
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
