"""Offline tests for ``vark.AnthiveClient`` — no network required.

Covers the pure-Python contract: version string, PLOT_GEOMS membership,
URL construction, local validation paths. Round-trip tests live in
``test_smoke.py`` and need a live anthive REST server.

Run with::

    uv run --with pytest --with requests --no-project \
        python -m pytest tests/test_offline.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Importable from the repo without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vark
from vark import AnthiveClient


def test_version_string():
    parts = vark.__version__.split('.')
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts[:3]), vark.__version__


def test_api_target_set():
    """``AnthiveClient.API_TARGET`` advertises which REST API version this
    release was last verified against — guards against silent drift."""
    target = AnthiveClient.API_TARGET
    parts = target.split('.')
    assert len(parts) == 3 and all(p.isdigit() for p in parts), target


def test_plot_geoms_set():
    """PLOT_GEOMS includes every geom the server ships at API 2.7.2."""
    assert isinstance(AnthiveClient.PLOT_GEOMS, frozenset)
    expected = {
        'scatter', 'hexbin', 'kde2d',
        'violin', 'box', 'bar',
        'histogram', 'ecdf', 'kde',
        'heatmap', 'rolling',
        'volcano', 'ma', 'forest',
        'de_heatmap',
    }
    missing = expected - AnthiveClient.PLOT_GEOMS
    assert not missing, f"PLOT_GEOMS is missing: {missing}"


def test_plot_output_formats():
    assert 'png' in AnthiveClient.PLOT_OUTPUT_FORMATS
    assert 'csv' in AnthiveClient.PLOT_OUTPUT_FORMATS   # API 2.6 export
    assert 'tsv' in AnthiveClient.PLOT_OUTPUT_FORMATS


def test_base_url_normalisation():
    c1 = AnthiveClient('http://x.test/api')
    c2 = AnthiveClient('http://x.test/api/')
    assert c1.base_url == c2.base_url == 'http://x.test/api'


def test_default_base_url():
    """No base_url and no env var → falls back to localhost:8080."""
    import os
    saved = os.environ.pop('ANTHIVE_API_URL', None)
    try:
        c = AnthiveClient(None)
        assert c.base_url == 'http://localhost:8080'
    finally:
        if saved is not None:
            os.environ['ANTHIVE_API_URL'] = saved


def test_auth_constructor_passes_through():
    c = AnthiveClient('http://x', auth=('user', 'pw'))
    assert c.auth == ('user', 'pw')


def test_verify_constructor_passes_through():
    """``verify=False`` is stored for downstream ``requests`` calls
    (needed for self-signed certs like the lab dev server)."""
    c = AnthiveClient('http://x', verify=False)
    assert c.verify is False


def test_get_plot_rejects_unknown_geom():
    """Local validation before any HTTP — saves a round-trip."""
    c = AnthiveClient('http://x')
    with pytest.raises(ValueError, match="Unknown geom 'bogus_geom'"):
        c.get_plot('some_db', 'bogus_geom')


def test_get_plot_rejects_unknown_format():
    c = AnthiveClient('http://x')
    with pytest.raises(ValueError, match="Unknown format"):
        c.get_plot('some_db', 'scatter', format='bogus')


def test_get_plot_accepts_known_geom_without_network(monkeypatch):
    """A known geom routes to ``/plot/{geom}`` — verify URL by mocking."""
    captured = {}

    class FakeResponse:
        content = b''
        headers = {
            'X-Plot-Format': 'png',
            'X-Plot-Caption': '',
            'X-Source-URL': '',
            'X-Plot-Cache': 'MISS',
            'Content-Type': 'image/png',
            'ETag': '',
        }

    c = AnthiveClient('http://x')

    def fake_get_raw(path, params=None):
        captured['path'] = path
        captured['params'] = params
        return FakeResponse()

    monkeypatch.setattr(c, '_get_raw', fake_get_raw)
    result = c.get_plot('grp/file', 'volcano',
                        study='STUDY1', term='term1', contrast='c1')
    assert captured['path'] == '/databases/grp/file/plot/volcano'
    assert captured['params'].get('study') == 'STUDY1'
    assert captured['params'].get('term') == 'term1'
    assert captured['params'].get('contrast') == 'c1'
    assert result['format'] == 'png'


def test_get_plot_captures_x_plot_caption_header(monkeypatch):
    """API 2.7.2 contract: when the server emits an X-Plot-Caption
    response header, get_plot() surfaces it as result['caption']. This
    is the ONLY place the multi-sentence figure legend exists."""
    want_caption = "UMAP of 12,345 cells coloured by cell_type."

    class FakeResponse:
        content = b'\x89PNG...'
        headers = {
            'X-Plot-Format': 'png',
            'X-Plot-Caption': want_caption,
            'X-Source-URL': 'http://server/plot/scatter?color=cell_type',
            'X-Plot-Cache': 'MISS',
            'Content-Type': 'image/png',
            'ETag': '"abc"',
        }

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: FakeResponse())
    result = c.get_plot('grp/file', 'scatter', color='cell_type')
    assert result['caption'] == want_caption
    assert result['cache'] == 'MISS'
    assert result['etag'] == '"abc"'


def test_get_plot_empty_caption_on_pre_2_7_server(monkeypatch):
    """Servers without X-Plot-Caption (pre-API-2.7.2) return ''; the
    client doesn't crash, just surfaces an empty string."""
    class FakeResponse:
        content = b''
        headers = {
            'X-Plot-Format': 'png',
            'Content-Type': 'image/png',
        }

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: FakeResponse())
    result = c.get_plot('grp/file', 'scatter')
    assert result['caption'] == ''


def test_get_plot_forwards_clamps_and_color_scale(monkeypatch):
    """log2fc_clip, neglog10p_clip, logmean_clip, color_scale ride
    through as query params unchanged (API 2.7+ features)."""
    captured = {}

    class FakeResponse:
        content = b''
        headers = {'X-Plot-Format': 'png', 'Content-Type': 'image/png'}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: (
                            captured.update({'path': path, 'params': params})
                            or FakeResponse()))

    c.get_plot(
        'grp/file', 'volcano',
        study='S', term='T', contrast='C',
        log2fc_clip=5.0,
        neglog10p_clip=10.0,
        color_scale='divergent',
    )
    assert captured['params'].get('log2fc_clip') == 5.0
    assert captured['params'].get('neglog10p_clip') == 10.0
    assert captured['params'].get('color_scale') == 'divergent'

    c.get_plot(
        'grp/file', 'ma',
        study='S', term='T', contrast='C',
        log2fc_clip=4.0,
        logmean_clip=6.0,
    )
    assert captured['params'].get('logmean_clip') == 6.0


def test_get_plot_forwards_de_heatmap_params(monkeypatch):
    captured = {}

    class FakeResponse:
        content = b''
        headers = {'X-Plot-Format': 'png', 'Content-Type': 'image/png'}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: (
                            captured.update({'path': path, 'params': params})
                            or FakeResponse()))

    c.get_plot(
        'grp/file', 'de_heatmap',
        study='S', term='T',
        contrasts='c1,c2,c3', genes='APOE,TREM2',
        value='log2fc', sig_overlay=True, padj_threshold=0.01,
    )
    assert captured['path'] == '/databases/grp/file/plot/de_heatmap'
    params = captured['params']
    assert params.get('study') == 'S'
    assert params.get('term') == 'T'
    assert params.get('contrasts') == 'c1,c2,c3'
    assert params.get('genes') == 'APOE,TREM2'
    assert params.get('value') == 'log2fc'
    assert params.get('sig_overlay') is True
    assert params.get('padj_threshold') == 0.01


def test_get_plot_csv_format_passes(monkeypatch):
    """API 2.6 plot-data export via format='csv' / 'tsv'."""
    captured = {}

    class FakeResponse:
        content = b'a,b\n1,2\n'
        headers = {
            'X-Plot-Format': 'csv',
            'X-Plot-Caption': 'data behind /plot/bar for grp/file: 1 rows x 2 cols',
            'Content-Type': 'text/csv; charset=utf-8',
        }

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: (
                            captured.update({'params': params})
                            or FakeResponse()))
    result = c.get_plot('grp/file', 'bar', x='cell_type', format='csv')
    assert captured['params']['format'] == 'csv'
    assert result['bytes'] == b'a,b\n1,2\n'
    assert 'rows x' in result['caption']


def test_de_methods_exist():
    expected = {
        'list_de_studies', 'get_de_study', 'list_de_contrasts',
        'get_de_rows', 'get_de_by_gene',
    }
    missing = expected - set(dir(AnthiveClient))
    assert not missing, f"missing DE methods: {missing}"


def test_version_method_exists():
    assert hasattr(AnthiveClient, 'get_version')
    assert hasattr(AnthiveClient, 'get_changelog')


def test_groups_method_exists():
    """``get_group`` covers the API 2.5 /groups/{group_id} endpoint."""
    assert hasattr(AnthiveClient, 'get_group')


def test_analytics_methods_exist():
    expected = {'analytics_schema', 'analytics_query', 'analytics_viz'}
    missing = expected - set(dir(AnthiveClient))
    assert not missing, f"missing analytics methods: {missing}"


def test_module_score_methods_exist():
    expected = {'module_score', 'list_module_scores'}
    missing = expected - set(dir(AnthiveClient))
    assert not missing, f"missing module-score methods: {missing}"


def test_pick_fastest_signature():
    """API 2.5+ /health latency telemetry helper."""
    assert hasattr(AnthiveClient, 'pick_fastest')
    # Should not crash with no candidates and not contact any network.
    assert AnthiveClient.pick_fastest([]) is None


def test_helpers_importable():
    from vark.helpers import find_database, find_metadata  # noqa: F401


def test_antclient_alias():
    """Back-compat alias from the antclient era."""
    from vark import AntClient
    assert AntClient is AnthiveClient
