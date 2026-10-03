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
