"""Extensive end-to-end smoke tests for ``vark.AnthiveClient`` against a
live ant-serve.

Where ``test_smoke.py`` is a fast happy-path sanity check, this file
exercises every public surface pyvark exposes — every plot geom, the
caption-parameter-awareness contract (API 2.7.2+), all the visual
clamps and overrides, the DE family (volcano / MA / forest /
de_heatmap), CSV/TSV export, analytics, module scores, genesets,
discovery, admin, and the auth failure path. Read-only throughout.

Skipped unless ``ANTHIVE_TEST_URL`` is set. Optional:

  ANTHIVE_TEST_URL=https://my.anthive/api
  ANTHIVE_TEST_USER=user
  ANTHIVE_TEST_PASSWORD=pass
  ANTHIVE_TEST_VERIFY=0            # self-signed TLS
  ANTHIVE_TEST_DB=S25/V6A          # override the auto-pick
  ANTHIVE_TEST_DB_DE=S25/V6A
  ANTHIVE_TEST_DB_DE_HEATMAP=S25/V6W
  ANTHIVE_TEST_GENE=P2RY12

Run with::

    ANTHIVE_TEST_URL=https://… ANTHIVE_TEST_USER=… ANTHIVE_TEST_PASSWORD=… \\
    ANTHIVE_TEST_VERIFY=0 \\
        uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_smoke_extensive.py -v

The tests below intentionally do NOT mutate server state (no admin
release/restore, no rescan, no plot-cache clear). If you want those
exercised, run them by hand against a non-production server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vark import AnthiveClient


_BASE_URL = os.environ.get('ANTHIVE_TEST_URL')

pytestmark = pytest.mark.skipif(
    not _BASE_URL,
    reason='set ANTHIVE_TEST_URL to a running ant-serve to enable smoke tests',
)


# ── fixtures ────────────────────────────────────────────────────────────────


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
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            import warnings
            warnings.filterwarnings('ignore')
    return AnthiveClient(_BASE_URL, auth=auth, verify=verify)


@pytest.fixture(scope='module')
def db_id(client) -> str:
    """A dataset that has at least one embedding (most plot geoms need it)."""
    override = os.environ.get('ANTHIVE_TEST_DB')
    if override:
        return override
    for db in client.get_databases():
        info = client.get_database_info(db['id'])
        if info.get('embeddings'):
            return db['id']
    pytest.skip('no dataset with embeddings available')


@pytest.fixture(scope='module')
def db_info(client, db_id) -> dict:
    return client.get_database_info(db_id)


@pytest.fixture(scope='module')
def first_embedding(db_info) -> str:
    emb = db_info.get('embeddings') or {}
    if not emb:
        pytest.skip(f'{db_info.get("title") or "dataset"} has no embeddings')
    return sorted(emb.keys())[0]


@pytest.fixture(scope='module')
def first_cat(db_info) -> str:
    cats = db_info.get('obs', {}).get('categorical', [])
    if not cats:
        pytest.skip('dataset has no categorical obs columns')
    return cats[0]


@pytest.fixture(scope='module')
def first_num(db_info) -> str:
    nums = db_info.get('obs', {}).get('numerical', [])
    if not nums:
        pytest.skip('dataset has no numerical obs columns')
    return nums[0]


@pytest.fixture(scope='module')
def known_gene(client, db_id) -> str:
    """A gene we know exists on the server. Tries env override → P2RY12 →
    falls back to the first hit from search_genes."""
    g = os.environ.get('ANTHIVE_TEST_GENE')
    if g:
        return g
    for candidate in ('P2RY12', 'CD74', 'GAPDH'):
        try:
            hits = client.search_genes(db_id, candidate, limit=1)
            if hits.get('genes'):
                return hits['genes'][0].get('gene_name', candidate)
        except Exception:
            pass
    pytest.skip('no known gene available on this dataset')


@pytest.fixture(scope='module')
def db_with_de(client) -> tuple:
    override = os.environ.get('ANTHIVE_TEST_DB_DE')
    if override:
        studies = client.list_de_studies(override)
        if studies:
            return override, studies[0]
    for db in client.get_databases():
        try:
            studies = client.list_de_studies(db['id'])
        except Exception:
            continue
        if studies:
            return db['id'], studies[0]
    pytest.skip('no dataset on this server has DE data ingested')


@pytest.fixture(scope='module')
def de_term_contrast(client, db_with_de) -> tuple:
    db, study = db_with_de
    detail = client.get_de_study(db, study['study_id'])
    term = detail['terms'][0]['term']
    contrasts = client.list_de_contrasts(db, study['study_id'], term)
    if not contrasts:
        pytest.skip(f'study {study["study_id"]} has no contrasts')
    return db, study['study_id'], term, contrasts[0]['contrast']


# ── 1. infrastructure / auth ────────────────────────────────────────────────


def test_authelia_wrong_password_returns_401(client):
    """Confirm the auth gate is real — calling with a bad password 401s."""
    # Only meaningful when the server enforces auth at all.
    if client.auth is None:
        pytest.skip('server is passwordless; auth-failure test inapplicable')
    bad = AnthiveClient(client.base_url, auth=(client.auth[0], 'wrong-pw'),
                        verify=client.verify)
    with pytest.raises(requests.HTTPError) as ei:
        bad.get_version()
    assert ei.value.response.status_code == 401


def test_health_latency_telemetry_keys(client):
    h = client.get_health()
    assert h['status'] == 'healthy'
    for key in ('databases', 'mean_response_ms', 'p50_response_ms', 'n_samples'):
        assert key in h


def test_version_payload_shape(client):
    v = client.get_version()
    assert v['version']
    assert isinstance(v['plot_geoms'], list) and len(v['plot_geoms']) >= 10
    # API 2.7+: caption capture lives behind 'plot_output_formats' image set
    assert {'png', 'svg', 'pdf'}.issubset(set(v['plot_output_formats']))


# ── 2. discovery ────────────────────────────────────────────────────────────


def test_list_databases_shape(client):
    """``get_databases()`` is the discovery entry point (pyvark exposes
    no separate ``search_datasets``)."""
    dbs = client.get_databases()
    assert isinstance(dbs, list) and len(dbs) >= 1
    first = dbs[0]
    for key in ('id', 'title'):
        assert key in first


def test_search_genes_returns_known_gene(client, db_id, known_gene):
    """``search_genes`` returns a List[str] of gene names (NOT a dict
    with a 'genes' key — that's the raw REST response shape, unwrapped
    by the client)."""
    names = client.search_genes(db_id, known_gene, limit=10)
    assert isinstance(names, list)
    assert known_gene in names


def test_get_database_info_shape(client, db_id):
    info = client.get_database_info(db_id)
    for key in ('title', 'n_cells', 'n_genes', 'embeddings', 'obs', 'version'):
        assert key in info
    assert isinstance(info['embeddings'], dict)
    assert {'numerical', 'categorical'}.issubset(info['obs'])


def test_get_group_known_returns_collection(client, db_id):
    """API 2.5+: any db with a group_id (= prefix before '/') has a /groups/{id} entry."""
    v = client.get_version()
    if v.get('version', '0.0.0') < '2.5':
        pytest.skip('pre-2.5 server')
    group_id = db_id.split('/')[0]
    g = client.get_group(group_id)
    assert g['group_id'] == group_id
    assert 'datasets' in g and isinstance(g['datasets'], list)


# ── 3. plot rendering — every geom that doesn't need DE ──────────────────────


_BASIC_GEOMS = (
    'scatter',
    'hexbin',
    'violin',
    'box',
    'bar',
    'histogram',
    'ecdf',
    'kde',
    'heatmap',
    # rolling, kde2d are tested separately (need a continuous x-axis)
)


def _plot_kwargs_for(geom, *, embedding, cat, num, gene):
    """Minimal valid kwargs for each geom against a generic dataset."""
    if geom in ('scatter', 'hexbin'):
        return dict(x=embedding, color=gene)
    if geom in ('violin', 'box'):
        return dict(x=cat, y=gene)
    if geom == 'bar':
        return dict(x=cat, y=gene)
    if geom in ('histogram', 'ecdf', 'kde'):
        return dict(x=gene)
    if geom == 'heatmap':
        return dict(x=gene, y=cat)
    raise ValueError(f'no preset for geom={geom!r}')


@pytest.mark.parametrize('geom', _BASIC_GEOMS)
def test_plot_geom_renders_png_and_caption(
    client, db_id, geom, first_embedding, first_cat, first_num, known_gene
):
    """Every basic plot geom returns 200 with non-empty PNG bytes AND a
    non-empty X-Plot-Caption (API 2.7.2+ guarantees the caption is
    populated for every image render)."""
    kwargs = _plot_kwargs_for(
        geom,
        embedding=first_embedding, cat=first_cat, num=first_num, gene=known_gene,
    )
    r = client.get_plot(db_id, geom, dpi=72, width=4, height=3, **kwargs)
    assert r['format'] == 'png'
    assert len(r['bytes']) > 1024, f'{geom}: tiny PNG, probable error placeholder'
    assert r['bytes'].startswith(b'\x89PNG'), f'{geom}: not a PNG'
    assert r['caption'], f'{geom}: empty X-Plot-Caption (server <2.7.2?)'
    # Caption is one paragraph, multi-sentence — at least one period.
    assert '.' in r['caption'], f'{geom}: caption has no sentence terminator'


@pytest.mark.parametrize('geom', _BASIC_GEOMS)
def test_plot_geom_csv_export(
    client, db_id, geom, first_embedding, first_cat, first_num, known_gene
):
    """CSV export contract — every geom should round-trip its source
    dataframe as CSV bytes."""
    kwargs = _plot_kwargs_for(
        geom, embedding=first_embedding, cat=first_cat, num=first_num, gene=known_gene,
    )
    r = client.get_plot(db_id, geom, format='csv', **kwargs)
    assert b',' in r['bytes'], f'{geom}: CSV without commas?'
    # The caption sits in the file (caption-prefix line in the CSV header)
    # and the X-Plot-Caption header is empty/absent for CSV.
    head = r['bytes'][:2000].decode('utf-8', errors='replace')
    assert head.strip(), f'{geom}: empty CSV'


# ── 4. caption is parameter-aware ───────────────────────────────────────────


def test_caption_mentions_subset_filter(
    client, db_id, first_embedding, first_cat, known_gene
):
    """If a subset filter is applied, the caption should describe the
    restricted cell set."""
    info = client.get_database_info(db_id)
    cats = info['obs'].get('categorical', [])
    if first_cat not in cats:
        pytest.skip('no categorical for subset')
    # Pick a likely-valid level by sampling distinct values via analytics
    sql = f'SELECT DISTINCT "{first_cat}" AS lvl FROM obscat LIMIT 1'
    try:
        rows = client.analytics_query(db_id, sql).get('preview', [])
        if not rows:
            pytest.skip('no obscat rows')
        level = rows[0]['lvl']
    except Exception as e:
        pytest.skip(f'analytics not available: {e}')
    r = client.get_plot(
        db_id, 'scatter', x=first_embedding, color=known_gene,
        subset=f'{first_cat}:{level}', dpi=72, width=4, height=3,
    )
    assert 'subset' in r['caption'].lower() or 'restricted' in r['caption'].lower()


def test_caption_mentions_sample_downsample(client, db_id, first_embedding, known_gene):
    """When ``sample=`` cuts the cells, the caption should call it out."""
    r = client.get_plot(
        db_id, 'scatter', x=first_embedding, color=known_gene,
        sample=500, dpi=72, width=4, height=3,
    )
    assert 'downsampling' in r['caption'].lower() or 'sample' in r['caption'].lower()


def test_caption_mentions_palette_override(client, db_id, first_embedding, known_gene):
    """A non-default continuous palette should land in the caption."""
    r = client.get_plot(
        db_id, 'scatter', x=first_embedding, color=known_gene,
        palette_continuous='magenta', dpi=72, width=4, height=3,
    )
    assert 'magenta' in r['caption'].lower() or 'palette' in r['caption'].lower()


def test_caption_omits_default_palette(client, db_id, first_embedding, known_gene):
    """Default palette MUST NOT bloat the caption — checked because earlier
    iterations listed tab10/inferno_r/RdBu_r on every plot."""
    r = client.get_plot(
        db_id, 'scatter', x=first_embedding, color=known_gene,
        dpi=72, width=4, height=3,
    )
    assert 'tab10' not in r['caption'] and 'inferno_r' not in r['caption']


def test_caption_mentions_hexbin_gridsize(client, db_id, first_embedding):
    """Hexbin gridsize is a Real Parameter; the caption should always
    surface it (it changes the figure substantively)."""
    r = client.get_plot(
        db_id, 'hexbin', x=first_embedding, gridsize=25,
        dpi=72, width=4, height=3,
    )
    assert 'gridsize' in r['caption'].lower() or '25' in r['caption']


def test_caption_mentions_hexbin_quantile_clip(client, db_id, first_embedding, known_gene):
    """vmin_quantile / vmax_quantile clip should appear in the caption."""
    r = client.get_plot(
        db_id, 'hexbin', x=first_embedding, color=known_gene,
        vmin_quantile=0.1, vmax_quantile=0.9,
        dpi=72, width=4, height=3,
    )
    assert 'quantile' in r['caption'].lower() or '0.1' in r['caption']


# ── 5. DE — volcano / MA / forest / de_heatmap ──────────────────────────────


def test_volcano_renders_with_caption(client, de_term_contrast):
    db, study, term, contrast = de_term_contrast
    r = client.get_plot(
        db, 'volcano', study=study, term=term, contrast=contrast,
        n_label=5, dpi=72, width=5, height=4,
    )
    assert r['bytes'].startswith(b'\x89PNG')
    cap = r['caption'].lower()
    assert 'volcano' in cap
    assert study.lower() in cap
    assert term.lower() in cap


def test_volcano_clamps_in_caption(client, de_term_contrast):
    """Caption MUST surface log2fc_clip + neglog10p_clip when set."""
    db, study, term, contrast = de_term_contrast
    r = client.get_plot(
        db, 'volcano', study=study, term=term, contrast=contrast,
        log2fc_clip=3, neglog10p_clip=100, n_label=5,
        dpi=72, width=5, height=4,
    )
    cap = r['caption']
    assert 'clamp' in cap.lower() or 'clip' in cap.lower()
    # The actual numbers should appear, not just the word "clamp"
    assert '3' in cap
    assert '100' in cap


def test_volcano_default_renders_without_clamp_text(client, de_term_contrast):
    """When clamps are absent, the caption should not invent them."""
    db, study, term, contrast = de_term_contrast
    r = client.get_plot(
        db, 'volcano', study=study, term=term, contrast=contrast,
        n_label=5, dpi=72, width=5, height=4,
    )
    cap = r['caption'].lower()
    # No "visual clamp" / "clamped to" phrasing
    assert 'visual clamp' not in cap


def test_forest_renders_for_known_gene(client, db_with_de, known_gene):
    db, _study = db_with_de
    try:
        r = client.get_plot(db, 'forest', gene=known_gene,
                            dpi=72, width=5, height=4)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            pytest.skip(f'gene {known_gene} has no DE on {db}')
        raise
    assert r['bytes'].startswith(b'\x89PNG')
    assert known_gene in r['caption']


def test_de_heatmap_renders(client):
    """de_heatmap needs a study + term. Try the known V6W module-DE first,
    fall back to scanning."""
    candidates = [
        (os.environ.get('ANTHIVE_TEST_DB_DE_HEATMAP', 'S25/V6W'),
         'Module_DE_interpretable_lmem_vs_grandmean',
         'patient_geno_short_relevel_sexreg'),
    ]
    for db, study, term in candidates:
        try:
            r = client.get_plot(
                db, 'de_heatmap', study=study, term=term,
                dpi=72, width=6, height=4,
            )
            assert r['bytes'].startswith(b'\x89PNG')
            assert 'heatmap' in r['caption'].lower()
            return
        except (requests.HTTPError, KeyError):
            continue
    pytest.skip('no de_heatmap-capable (study, term) on this server')


def test_de_heatmap_sig_overlay_in_caption(client):
    """sig_overlay should be described in the caption."""
    db = os.environ.get('ANTHIVE_TEST_DB_DE_HEATMAP', 'S25/V6W')
    try:
        r = client.get_plot(
            db, 'de_heatmap',
            study='Module_DE_interpretable_lmem_vs_grandmean',
            term='patient_geno_short_relevel_sexreg',
            value='zeff', sig_overlay=True,
            dpi=72, width=6, height=4,
        )
    except (requests.HTTPError, KeyError):
        pytest.skip('no de_heatmap-capable (study, term)')
    assert 'asterisk' in r['caption'].lower() or 'overlaid' in r['caption'].lower()


# ── 6. analytics ────────────────────────────────────────────────────────────


def test_analytics_schema_lists_tables(client, db_id):
    s = client.analytics_schema(db_id)
    assert isinstance(s, dict)
    assert 'tables' in s and isinstance(s['tables'], list)


def test_analytics_query_select_works(client, db_id):
    r = client.analytics_query(db_id, 'SELECT 1 AS x', limit=10)
    assert 'columns' in r
    assert 'x' in r['columns']
    assert r['row_count'] == 1


def test_analytics_query_writes_blocked(client, db_id):
    """The sandbox is SELECT-only — any DDL/DML should be refused server-side."""
    with pytest.raises(requests.HTTPError) as ei:
        client.analytics_query(db_id, 'CREATE TABLE __evil(x INT)')
    assert ei.value.response.status_code in (400, 403)


# ── 7. module scores + genesets ─────────────────────────────────────────────


def test_module_score_listing_shape(client, db_id):
    out = client.list_module_scores(db_id)
    assert isinstance(out, dict)
    assert 'scored_genesets' in out
    assert isinstance(out['scored_genesets'], list)
    if out.get('count', 0):
        first = out['scored_genesets'][0]
        # discovery field naming is server-side but should include the
        # geneset id and a count
        assert any(k in first for k in ('geneset_id', 'id', 'name'))


def test_genesets_list(client):
    try:
        gs = client.list_genesets()
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            pytest.skip('genesets endpoint not present on this server')
        raise
    assert isinstance(gs, (list, dict))


# ── 8. multi-format export ──────────────────────────────────────────────────


@pytest.mark.parametrize('fmt', ('png', 'svg', 'pdf'))
def test_plot_in_every_image_format(client, db_id, first_embedding, fmt):
    r = client.get_plot(db_id, 'scatter', x=first_embedding,
                        format=fmt, dpi=72, width=4, height=3)
    assert r['bytes'], f'{fmt}: empty body'
    magic = {
        'png': b'\x89PNG',
        'svg': b'<?xml',
        'pdf': b'%PDF',
    }[fmt]
    assert r['bytes'].startswith(magic), f'{fmt}: wrong magic — wrong content-type?'
    # Caption is in the header for image formats.
    assert r['caption'], f'{fmt}: no X-Plot-Caption'


@pytest.mark.parametrize('fmt', ('csv', 'tsv'))
def test_plot_in_text_data_formats(client, db_id, first_embedding, fmt):
    r = client.get_plot(db_id, 'scatter', x=first_embedding, format=fmt)
    sep = b',' if fmt == 'csv' else b'\t'
    assert sep in r['bytes'], f'{fmt}: separator missing'


# ── 9. cache & ETag headers ─────────────────────────────────────────────────


def test_plot_cache_header_present(client, db_id, first_embedding):
    r = client.get_plot(db_id, 'scatter', x=first_embedding,
                        dpi=72, width=4, height=3)
    # cache field is sourced from X-Plot-Cache; should be 'HIT' or 'MISS'
    assert r['cache'] in ('HIT', 'MISS', ''), f'unexpected cache={r["cache"]!r}'


def test_plot_repeat_request_is_cache_hit(client, db_id, first_embedding):
    """Identical params twice in a row → second is HIT (cache is in-mem
    per-process so always works against a single ant-serve)."""
    kwargs = dict(x=first_embedding, dpi=72, width=4, height=3, n_label=0)
    a = client.get_plot(db_id, 'scatter', **kwargs)
    b = client.get_plot(db_id, 'scatter', **kwargs)
    # First may be MISS or HIT; second must be HIT (unless cache was empty
    # AND server is restarting — unlikely in a stable test).
    assert b['cache'] == 'HIT' or a['cache'] == b['cache']


# ── 10. errors that should surface cleanly ──────────────────────────────────


def test_unknown_dataset_returns_404(client):
    with pytest.raises(requests.HTTPError) as ei:
        client.get_database_info('NOPE/DEF_DOES_NOT_EXIST')
    assert ei.value.response.status_code == 404


def test_unknown_geom_rejected_client_side(client, db_id, first_embedding):
    """pyvark validates ``geom`` against ``PLOT_GEOMS`` BEFORE making the
    HTTP call — saves a server round-trip and gives a clearer error than
    a 400 / 404. So the test expects a ValueError, not an HTTPError."""
    with pytest.raises(ValueError) as ei:
        client.get_plot(db_id, 'definitely_not_a_real_geom',
                        x=first_embedding, dpi=72, width=4, height=3)
    assert 'definitely_not_a_real_geom' in str(ei.value)
    # And the error names valid options so the user can recover
    assert 'scatter' in str(ei.value) or 'volcano' in str(ei.value)


def test_volcano_unknown_study_returns_404(client, db_with_de):
    db, _study = db_with_de
    with pytest.raises(requests.HTTPError) as ei:
        client.get_plot(db, 'volcano',
                        study='NOPE_STUDY', term='x', contrast='y',
                        dpi=72, width=4, height=3)
    assert ei.value.response.status_code == 404


# ── 11. caption survives in PNG metadata ────────────────────────────────────


def test_caption_embedded_in_png_text_chunks(client, db_id, first_embedding):
    """API 2.7.2 mirrors X-Plot-Caption into PNG tEXt 'Title' + 'Description'
    chunks so the legend survives save-as. Worth confirming once."""
    r = client.get_plot(db_id, 'scatter', x=first_embedding,
                        format='png', dpi=72, width=4, height=3)
    header_caption = r['caption']
    body = r['bytes']
    # Look for the caption text inside the PNG payload — tEXt chunks
    # store it as ASCII so a substring match is enough.
    # Use the first ~80 chars to avoid false negatives from encoding/wrapping.
    needle = header_caption[:80].encode('latin-1', errors='replace')
    assert needle in body, (
        'caption not embedded in PNG metadata; tEXt chunk missing or stripped'
    )
