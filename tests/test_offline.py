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
    """PLOT_GEOMS includes every geom the server ships at API 2.36.0."""
    assert isinstance(AnthiveClient.PLOT_GEOMS, frozenset)
    expected = {
        'scatter', 'hexbin', 'kde2d',
        'violin', 'box', 'bar',
        'histogram', 'ecdf', 'kde',
        'heatmap', 'rolling',
        'volcano', 'ma', 'forest',
        'de_heatmap',
        # REST API 2.12+
        'de_quadrant',
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


# ── /catalogs family (REST API 2.30+) ─────────────────────────────────────


def test_catalog_methods_exist():
    """Full 2.30 catalog surface is bound on the client."""
    expected = {
        'list_catalogs',
        'get_catalog',
        'get_catalog_module',
        'get_catalog_score',
        'rescan_catalogs',
    }
    missing = expected - set(dir(AnthiveClient))
    assert not missing, f"missing catalog methods: {missing}"


def test_api_target_at_least_2_30():
    """The API_TARGET docstring should reflect the 2.30 update."""
    parts = [int(p) for p in AnthiveClient.API_TARGET.split('.')]
    assert (parts[0], parts[1]) >= (2, 30), (
        f"API_TARGET={AnthiveClient.API_TARGET!r} — expected >= 2.30.0"
    )


def test_api_target_at_least_2_36():
    """API_TARGET should reflect the 2.36 bin_color update."""
    parts = [int(p) for p in AnthiveClient.API_TARGET.split('.')]
    assert (parts[0], parts[1]) >= (2, 36), (
        f"API_TARGET={AnthiveClient.API_TARGET!r} — expected >= 2.36.0"
    )


def test_get_plot_forwards_bin_color(monkeypatch):
    """bin_color + bin_color_method ride through as query params
    (REST API 2.34+ scatter/hexbin, 2.35 kde2d, 2.36 histogram/ecdf/kde)."""
    captured = {}

    class FakeResponse:
        content = b''
        headers = {'X-Plot-Format': 'png', 'Content-Type': 'image/png'}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: (
                            captured.update({'path': path, 'params': params})
                            or FakeResponse()))

    # scatter — bin_color optional, method omitted → server default
    c.get_plot('grp/file', 'scatter', color='Age', bin_color=3)
    assert captured['params'].get('bin_color') == 3
    assert 'bin_color_method' not in captured['params']

    # kde2d — bin_color required when color is continuous
    c.get_plot('grp/file', 'kde2d',
               x='avg_Braak', y='med_Braak',
               color='avg_Braak_SEAAD',
               bin_color=3, bin_color_method='width')
    assert captured['params'].get('bin_color') == 3
    assert captured['params'].get('bin_color_method') == 'width'

    # rolling — passthrough
    c.get_plot('grp/file', 'rolling',
               x='avg_Braak', y='med_Braak',
               color='avg_Braak_SEAAD',
               bin_color=3, window=30)
    assert captured['params'].get('bin_color') == 3
    assert captured['params'].get('window') == 30


def test_get_plot_bin_color_default_omits_param(monkeypatch):
    """When bin_color/bin_color_method are None the client MUST NOT
    send them — otherwise older servers 400 on unknown params."""
    captured = {}

    class FakeResponse:
        content = b''
        headers = {'X-Plot-Format': 'png', 'Content-Type': 'image/png'}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: (
                            captured.update({'params': params})
                            or FakeResponse()))
    c.get_plot('grp/file', 'scatter', color='cell_type')
    assert 'bin_color' not in captured['params']
    assert 'bin_color_method' not in captured['params']


def test_get_plot_de_quadrant_geom(monkeypatch):
    """de_quadrant (REST API 2.12+) is a valid geom; the client should
    not reject it on local validation."""
    captured = {}

    class FakeResponse:
        content = b''
        headers = {'X-Plot-Format': 'png', 'Content-Type': 'image/png'}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get_raw',
                        lambda path, params=None: (
                            captured.update({'path': path})
                            or FakeResponse()))
    c.get_plot('grp/file', 'de_quadrant',
               study='S', term='T', contrast='C')
    assert captured['path'] == '/databases/grp/file/plot/de_quadrant'


def test_list_catalogs_no_source(monkeypatch):
    """``list_catalogs()`` hits ``/catalogs`` with no query params."""
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        captured['params'] = params
        return {"count": 3, "catalogs": [
            {"source": "starcat", "catalog_id": "MICROGLIA_V1_0"},
            {"source": "geneset", "catalog_id": "Sierksma2025/WGCNA"},
            {"source": "geneset", "catalog_id": "Rangaraju2018/WGCNA"},
        ]}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    result = c.list_catalogs()
    assert captured['path'] == '/catalogs'
    assert captured['params'] is None
    assert result['count'] == 3


def test_list_catalogs_with_source_filter(monkeypatch):
    """``list_catalogs(source='starcat')`` forwards the source
    query param."""
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        captured['params'] = params
        return {"count": 1, "catalogs": [
            {"source": "starcat", "catalog_id": "MICROGLIA_V1_0"},
        ]}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    c.list_catalogs(source='starcat')
    assert captured['params'] == {'source': 'starcat'}


def test_get_catalog_starcat_one_segment_id(monkeypatch):
    """starcat catalog_id is a single segment (``MICROGLIA_V1_0``)."""
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        return {"source": "starcat", "catalog_id": "MICROGLIA_V1_0",
                "modules": [], "scores": []}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    c.get_catalog('starcat', 'MICROGLIA_V1_0')
    assert captured['path'] == '/catalogs/starcat/MICROGLIA_V1_0'


def test_get_catalog_geneset_two_segment_id(monkeypatch):
    """geneset catalog_id is two segments (``Sierksma2025/WGCNA``);
    the '/' is passed through unchanged so FastAPI's `{catalog_id:path}`
    match handles it."""
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        return {"source": "geneset", "catalog_id": "Sierksma2025/WGCNA",
                "modules": [], "scores": []}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    c.get_catalog('geneset', 'Sierksma2025/WGCNA')
    assert captured['path'] == '/catalogs/geneset/Sierksma2025/WGCNA'


def test_get_catalog_module_top_kwarg(monkeypatch):
    """``top=N`` becomes a ``top`` query param; omitted when None."""
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        captured['params'] = params
        return {
            "name": "Microglia_Border_CAM",
            "top_genes": [
                {"gene": "CD163", "weight": 0.42, "rank": 1},
                {"gene": "LYVE1", "weight": 0.31, "rank": 2},
            ],
        }

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)

    # No top: no params
    c.get_catalog_module('starcat', 'MICROGLIA_V1_0',
                         'Microglia_Border_CAM')
    assert captured['path'] == (
        '/catalogs/starcat/MICROGLIA_V1_0/modules/Microglia_Border_CAM'
    )
    assert captured['params'] is None

    # With top: forwarded verbatim
    c.get_catalog_module('starcat', 'MICROGLIA_V1_0',
                         'Microglia_Border_CAM', top=10)
    assert captured['params'] == {'top': 10}


def test_get_catalog_module_two_segment_catalog_id(monkeypatch):
    """Two-segment catalog IDs still route to /modules/{name} — the
    FastAPI helper handler picks them up server-side."""
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        return {"name": "Brown_Lysosome", "top_genes": []}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    c.get_catalog_module('geneset', 'Sierksma2025/WGCNA', 'Brown_Lysosome')
    assert captured['path'] == (
        '/catalogs/geneset/Sierksma2025/WGCNA/modules/Brown_Lysosome'
    )


def test_get_catalog_score_returns_recipe(monkeypatch):
    """``get_catalog_score`` returns the recipe dict verbatim — the
    client is a passthrough, no reshaping."""
    recipe = {
        "name": "Border_CAM_pos",
        "kind": "discrete",
        "columns": ["Microglia_Border_CAM"],
        "threshold": 0.0448,
        "normalization": "normalized",
    }
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        return recipe

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    result = c.get_catalog_score('starcat', 'MICROGLIA_V1_0',
                                 'Border_CAM_pos')
    assert captured['path'] == (
        '/catalogs/starcat/MICROGLIA_V1_0/scores/Border_CAM_pos'
    )
    assert result == recipe
    assert result['threshold'] == 0.0448


def test_rescan_catalogs_posts(monkeypatch):
    """``rescan_catalogs()`` POSTs (not GETs) to /catalogs/rescan."""
    called = {}

    def fake_post(path, json=None):
        called['path'] = path
        called['json'] = json
        return {"count": 4, "catalogs": []}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_post', fake_post)
    result = c.rescan_catalogs()
    assert called['path'] == '/catalogs/rescan'
    assert called['json'] is None
    assert result['count'] == 4


# ── is_secondary flag (REST API 2.37+) ────────────────────────────────────


def _fake_databases_list():
    """Two primary rows and one secondary row, in fixed order."""
    return [
        {'id': 'A01/PRI', 'title': 'Primary A', 'is_secondary': False},
        {'id': 'B02/SEC', 'title': 'Re-aggregated B', 'is_secondary': True},
        {'id': 'C03/PRI', 'title': 'Primary C', 'is_secondary': False},
    ]


def test_get_databases_surfaces_is_secondary(monkeypatch):
    """The client passes ``is_secondary`` through unchanged, both truthy
    and falsy, so downstream code can read it off the dict."""
    def fake_get(path, params=None):
        return {'databases': _fake_databases_list()}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    dbs = c.get_databases()
    assert len(dbs) == 3
    by_id = {db['id']: db for db in dbs}
    assert by_id['A01/PRI']['is_secondary'] is False
    assert by_id['B02/SEC']['is_secondary'] is True
    assert by_id['C03/PRI']['is_secondary'] is False


def test_get_database_info_surfaces_is_secondary(monkeypatch):
    """``get_database_info`` returns the payload verbatim, so both
    ``is_secondary=True`` and ``is_secondary=False`` come through."""
    payload_secondary = {'id': 'B02/SEC', 'title': 'Re-agg',
                         'is_secondary': True}
    payload_primary = {'id': 'A01/PRI', 'title': 'Primary',
                       'is_secondary': False}

    holder = {'body': payload_primary}

    def fake_get(path, params=None):
        return holder['body']

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)

    info = c.get_database_info('A01/PRI')
    assert info['is_secondary'] is False

    holder['body'] = payload_secondary
    info = c.get_database_info('B02/SEC')
    assert info['is_secondary'] is True


def test_get_databases_primary_only_drops_secondary(monkeypatch):
    """``primary_only=True`` filters out ``is_secondary=True`` rows."""
    def fake_get(path, params=None):
        return {'databases': _fake_databases_list()}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)

    all_dbs = c.get_databases()
    assert len(all_dbs) == 3

    primary = c.get_databases(primary_only=True)
    assert len(primary) == 2
    ids = {db['id'] for db in primary}
    assert ids == {'A01/PRI', 'C03/PRI'}
    assert all(not db.get('is_secondary', False) for db in primary)


def test_get_databases_default_returns_everything(monkeypatch):
    """Without ``primary_only`` the client returns every row, including
    ``is_secondary=True`` ones. Default behaviour is unchanged from 0.4."""
    def fake_get(path, params=None):
        return {'databases': _fake_databases_list()}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)

    dbs = c.get_databases()
    assert any(db['is_secondary'] for db in dbs)


def test_get_databases_missing_is_secondary_treated_as_primary(monkeypatch):
    """Older servers omit ``is_secondary`` entirely. Rows without the key
    deserialize as primary, so ``primary_only=True`` keeps them."""
    legacy_rows = [
        {'id': 'A01/OLD', 'title': 'legacy row, no field'},
        {'id': 'B02/OLD', 'title': 'also legacy'},
    ]

    def fake_get(path, params=None):
        return {'databases': legacy_rows}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)

    dbs = c.get_databases()
    assert len(dbs) == 2
    for db in dbs:
        assert 'is_secondary' not in db

    kept = c.get_databases(primary_only=True)
    assert len(kept) == 2
    assert {db['id'] for db in kept} == {'A01/OLD', 'B02/OLD'}


def test_get_database_info_missing_field_backcompat(monkeypatch):
    """The info endpoint on a pre-2.37 server returns no ``is_secondary``.
    The client does not synthesize one, so ``.get('is_secondary', False)``
    is the caller idiom."""
    def fake_get(path, params=None):
        return {'id': 'A01/OLD', 'title': 'legacy dataset'}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    info = c.get_database_info('A01/OLD')
    assert 'is_secondary' not in info
    assert info.get('is_secondary', False) is False


def test_api_target_at_least_2_37():
    """The API_TARGET string should reflect the 2.37 is_secondary update."""
    parts = [int(p) for p in AnthiveClient.API_TARGET.split('.')]
    assert (parts[0], parts[1]) >= (2, 37), (
        f"API_TARGET={AnthiveClient.API_TARGET!r} — expected >= 2.37.0"
    )


# ── Facets family (0.6.0) ─────────────────────────────────────────────────


def test_facet_methods_exist():
    """0.6.0 exposes the facets surface on the client."""
    expected = {
        'list_facets',
        'get_facet',
        'get_gene_variance_by_facet',
    }
    missing = expected - set(dir(AnthiveClient))
    assert not missing, f"missing facet methods: {missing}"


def test_list_facets_unwraps_envelope(monkeypatch):
    """``list_facets()`` returns the ``facets`` list from the response
    envelope, not the whole dict."""
    captured = {}

    def fake_get(path, params=None):
        captured['path'] = path
        captured['params'] = params
        return {
            'n_facets': 2,
            'facets': [
                {'facet': 'ant_disease', 'type': 'categorical',
                 'type_mixed': False, 'n_datasets': 24,
                 'signal_strength': 0.42},
                {'facet': 'ant_age', 'type': 'numerical',
                 'type_mixed': False, 'n_datasets': 12,
                 'signal_strength': 0.11},
            ],
        }

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    facets = c.list_facets()
    assert captured['path'] == '/facets'
    assert captured['params'] is None
    assert isinstance(facets, list)
    assert len(facets) == 2
    assert facets[0]['facet'] == 'ant_disease'
    assert facets[0]['signal_strength'] == 0.42


def test_get_facet_forwards_top_modules(monkeypatch):
    """``get_facet(name, top_modules=N)`` sends ``top_modules`` as a
    query param and returns the payload verbatim."""
    captured = {}
    payload = {
        'facet': 'ant_disease',
        'type': 'categorical',
        'type_mixed': False,
        'n_datasets': 3,
        'total_n_cells': 12345,
        'datasets': [
            {'db_id': 'A01/PRI', 'title': 'X', 'group': 'g',
             'group_id': 'g01', 'file_id': 'PRI', 'n_cells': 5000,
             'kind_on_this_dataset': 'categorical'},
        ],
        'value_distribution': {
            'kind': 'categorical',
            'values': [{'value': 'AD', 'n_cells': 7000, 'n_datasets': 2}],
            'total_cells': 12345,
        },
        'modules': {'rows': [], 'n_total': 0, 'truncated': False},
    }

    def fake_get(path, params=None):
        captured['path'] = path
        captured['params'] = params
        return payload

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    result = c.get_facet('ant_disease', top_modules=50)
    assert captured['path'] == '/facets/ant_disease'
    assert captured['params'] == {'top_modules': 50}
    assert result is payload
    assert result['n_datasets'] == 3
    assert result['value_distribution']['values'][0]['value'] == 'AD'


def test_get_facet_default_top_modules(monkeypatch):
    """Default ``top_modules`` is 200 and always rides through."""
    captured = {}

    def fake_get(path, params=None):
        captured['params'] = params
        return {'facet': 'ant_age', 'type': 'numerical',
                'type_mixed': False, 'n_datasets': 1,
                'total_n_cells': 100, 'datasets': [],
                'value_distribution': {'kind': 'numerical',
                                       'fleet_min': 0.0, 'fleet_max': 90.0,
                                       'per_dataset': [], 'total_cells': 100},
                'modules': {'rows': [], 'n_total': 0, 'truncated': False}}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    c.get_facet('ant_age')
    assert captured['params'] == {'top_modules': 200}


def test_get_gene_variance_by_facet_forwards_params(monkeypatch):
    """``facet`` and ``top`` ride through as query params on the
    ``/databases/{db_id}/gene-variance-by-facet`` route."""
    captured = {}
    payload = {
        'db_id': 'Blackburn2026/main',
        'facet': 'ant_disease',
        'facet_type': 'categorical',
        'layer': 'X',
        'n_groups': 2,
        'groups': ['AD', 'control'],
        'n_cells_per_group': {'AD': 8000, 'control': 4000},
        'n_genes_returned': 20,
        'genes': [
            {'gene': 'APOE', 'signal': 0.83,
             'group_means': {'AD': 3.1, 'control': 1.2}},
            {'gene': 'TREM2', 'signal': 0.62,
             'group_means': {'AD': 2.4, 'control': 1.0}},
        ],
    }

    def fake_get(path, params=None):
        captured['path'] = path
        captured['params'] = params
        return payload

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    result = c.get_gene_variance_by_facet(
        'Blackburn2026/main', 'ant_disease', top=20,
    )
    assert captured['path'] == (
        '/databases/Blackburn2026/main/gene-variance-by-facet'
    )
    assert captured['params'] == {'facet': 'ant_disease', 'top': 20}
    assert result['n_groups'] == 2
    assert result['genes'][0]['gene'] == 'APOE'


def test_get_gene_variance_by_facet_default_top(monkeypatch):
    """Default ``top`` is 50."""
    captured = {}

    def fake_get(path, params=None):
        captured['params'] = params
        return {'db_id': 'g/f', 'facet': 'ant_x', 'facet_type': 'categorical',
                'layer': 'X', 'n_groups': 0, 'groups': [],
                'n_cells_per_group': {}, 'n_genes_returned': 0, 'genes': []}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    c.get_gene_variance_by_facet('g/f', 'ant_x')
    assert captured['params'] == {'facet': 'ant_x', 'top': 50}


# ── only_facet filter on get_databases (0.6.0) ────────────────────────────


def _fake_databases_with_collections():
    """Fixed dataset list with mixed ``collection`` blocks."""
    return [
        {'id': 'A01/PRI', 'title': 'AD cohort A',
         'collection': {'ant_disease': 'AD', 'ant_tissue': 'brain'}},
        {'id': 'B02/PRI', 'title': 'Control cohort B',
         'collection': {'ant_disease': 'control', 'ant_tissue': 'brain'}},
        {'id': 'C03/PRI', 'title': 'PD cohort C',
         'collection': {'ant_disease': 'PD', 'ant_tissue': 'brain'}},
        {'id': 'D04/OLD', 'title': 'legacy row, no collection'},
        {'id': 'E05/PRI', 'title': 'AD cohort with collection missing key',
         'collection': {'ant_tissue': 'brain'}},
    ]


def test_get_databases_only_facet_keeps_matches(monkeypatch):
    """``only_facet={'ant_disease': ['AD', 'control']}`` keeps only
    the rows whose ``collection.ant_disease`` is in that list."""
    def fake_get(path, params=None):
        return {'databases': _fake_databases_with_collections()}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    kept = c.get_databases(only_facet={'ant_disease': ['AD', 'control']})
    ids = {db['id'] for db in kept}
    assert ids == {'A01/PRI', 'B02/PRI'}


def test_get_databases_only_facet_drops_missing_collection(monkeypatch):
    """Rows without a ``collection`` block are excluded, not kept."""
    def fake_get(path, params=None):
        return {'databases': _fake_databases_with_collections()}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    kept = c.get_databases(only_facet={'ant_disease': ['AD']})
    ids = {db['id'] for db in kept}
    assert ids == {'A01/PRI'}
    assert 'D04/OLD' not in ids
    assert 'E05/PRI' not in ids


def test_get_databases_only_facet_composes_with_primary_only(monkeypatch):
    """``primary_only`` and ``only_facet`` compose."""
    rows = [
        {'id': 'A/1', 'is_secondary': False,
         'collection': {'ant_disease': 'AD'}},
        {'id': 'B/1', 'is_secondary': True,
         'collection': {'ant_disease': 'AD'}},
        {'id': 'C/1', 'is_secondary': False,
         'collection': {'ant_disease': 'control'}},
    ]

    def fake_get(path, params=None):
        return {'databases': rows}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    kept = c.get_databases(primary_only=True,
                           only_facet={'ant_disease': ['AD']})
    assert [db['id'] for db in kept] == ['A/1']


def test_get_databases_only_facet_default_is_noop(monkeypatch):
    """No ``only_facet`` kwarg leaves the row list untouched."""
    def fake_get(path, params=None):
        return {'databases': _fake_databases_with_collections()}

    c = AnthiveClient('http://x')
    monkeypatch.setattr(c, '_get', fake_get)
    dbs = c.get_databases()
    assert len(dbs) == 5
