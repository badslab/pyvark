"""Offline tests for the REST API 2.45.0 surface added in pyvark 0.10.0:
forest rows, paged top lists, module replication, the facet overview,
gene detection, per-donor values and plots, donor variability, gene set
ranks, the DE study summary and the removed ``apoe_carrier`` alias.
HTTP is mocked with the recorder from ``test_library_offline``.

Run with::

    uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_api245_offline.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vark  # noqa: E402
from vark import AnthiveClient  # noqa: E402
from test_library_offline import (  # noqa: E402,F401  (fixtures)
    BASE,
    client,
    http,
    make_response,
)


NEW_METHODS = {
    'get_facet_top_genes', 'get_facet_top_modules',
    'get_facet_effects_overview', 'get_geneset_facet_effects',
    'get_gene_detection', 'get_facet_donor_values', 'get_facet_donor_plot',
    'get_database_donor_variability', 'get_gene_donor_variability',
    'get_geneset_donor_variability', 'get_donor_variability_top',
    'get_geneset_rank', 'get_module_ranks', 'get_de_study_summary',
}


def test_version_and_api_target():
    assert tuple(int(part) for part in vark.__version__.split('.')) >= (0, 10, 0)
    assert AnthiveClient.API_TARGET == '2.46.0'


def test_new_methods_exist_and_are_documented():
    for name in NEW_METHODS:
        method = getattr(AnthiveClient, name)
        assert method.__doc__ and '2.45.0' in method.__doc__, name


def test_constants():
    assert AnthiveClient.FOREST_DETAIL == ('full', 'anchors', 'none')
    assert AnthiveClient.DONOR_PLOT_FORMATS == ('png', 'svg', 'pdf')
    assert AnthiveClient.DONOR_VARIABILITY_RUNGS == (
        'raw', 'D0', 'D1', 'D2', 'D3', 'D4', 'F')
    assert {'graft_sex', 'host_sex'} <= set(AnthiveClient.TESTED_FACETS)
    assert 'apoe_carrier' not in AnthiveClient.DEPRECATED_FACET_ALIASES
    assert AnthiveClient.REMOVED_FACET_ALIASES['apoe_carrier'] == 'apoe4_carrier'


@pytest.mark.parametrize('name', [
    'rescan_databases', 'rescan_genesets', 'rescan_module_variability',
    'rescan_catalogs', 'get_plot_cache_stats', 'clear_plot_cache',
    'admin_release', 'admin_restore'])
def test_admin_only_methods_say_so(name):
    doc = getattr(AnthiveClient, name).__doc__
    assert 'Admin only' in doc and '403' in doc
    assert f':meth:`{name}`' in AnthiveClient.__doc__


def test_get_version_documents_compatible_pyvark():
    assert 'compatible_pyvark' in AnthiveClient.get_version.__doc__


def test_docstrings_use_new_names():
    top_modules = AnthiveClient.get_facet_top_modules.__doc__
    assert 'effect_gate_rule' in top_modules
    assert 'rows have no ``strict``' in top_modules
    assert 'celltype_group' in AnthiveClient.get_donor_variability_top.__doc__
    assert '100000' in AnthiveClient.get_facet_recurring_genes.__doc__
    assert '1 to 500)' not in AnthiveClient.get_facet_recurring_genes.__doc__


# ── forest ──────────────────────────────────────────────────────────────


def test_forest_is_sent_only_when_given(http, client):
    client.get_facet_gene_effects('sex', 'XIST')
    assert 'forest' not in http.last['params']
    client.get_facet_gene_effects('sex', 'XIST', forest='none')
    assert http.last['params']['forest'] == 'none'
    client.get_gene_facet_effects('XIST', forest='full')
    assert http.last['url'] == f'{BASE}/genes/XIST/facet-effects'
    assert http.last['params'] == {'forest': 'full'}


def test_bad_forest_raises_before_the_request(http, client):
    with pytest.raises(ValueError):
        client.get_facet_gene_effects('sex', 'XIST', forest='some')
    assert http.calls == []


# ── top genes: paging and filters ───────────────────────────────────────


def test_top_genes_filters_sent_only_when_set(http, client):
    client.get_facet_recurring_genes('braak')
    assert http.last['params'] == {'n': 50}
    client.get_facet_top_genes('braak', n=2000, offset=100,
                               effect_gate=True, strict=True)
    assert http.last['url'] == f'{BASE}/facets/braak/effects/top'
    assert http.last['params'] == {'n': 2000, 'offset': 100,
                                   'effect_gate': 'true', 'strict': 'true'}


def test_top_genes_fetch_all_follows_has_more(http, client):
    http.queue(
        make_response(200, {'n_matching': 5, 'headline': {'n_strict': 1},
                            'rows': [{'gene': 'A'}, {'gene': 'B'}],
                            'n_returned': 2, 'has_more': True}),
        make_response(200, {'rows': [{'gene': 'C'}, {'gene': 'D'}],
                            'has_more': True}),
        make_response(200, {'rows': [{'gene': 'E'}], 'has_more': False}))
    result = client.get_facet_recurring_genes('sex', n=2, fetch_all=True)
    assert [row['gene'] for row in result['rows']] == list('ABCDE')
    assert result['n_returned'] == 5 and result['has_more'] is False
    assert result['headline'] == {'n_strict': 1}
    offsets = [(call['params'] or {}).get('offset', 0) for call in http.calls]
    assert offsets == [0, 2, 4]


def test_top_genes_dataframe_keeps_paging_attrs(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'n_matching': 48, 'has_more': True,
                                   'headline': {'n_replicated': 48},
                                   'rows': [{'gene': 'XIST'}]}))
    frame = client.get_facet_recurring_genes('sex', n=1, format='dataframe')
    assert frame.attrs == {'n_matching': 48, 'has_more': True,
                           'headline': {'n_replicated': 48}}


# ── modules, overview, gene set card ────────────────────────────────────


def test_top_modules_params_and_dataframe(http, client):
    pytest.importorskip('pandas')
    body = {'n_replicated': 3, 'effect_gate_rule': {'std_effect': 0.2},
            'rows': [{'geneset_id': 'S/E/m', 'r_value': 0.01}]}
    http.queue(make_response(200, body))
    frame = client.get_facet_top_modules(
        'sex', cell_type='microglia', n=10, offset=10, effect_gate=True,
        include_not_replicated=True, catalog='Sierksma2025/WGCNA',
        exclude_secondary=False, scope='human_postmortem',
        format='dataframe')
    assert http.last['url'] == f'{BASE}/facets/sex/modules/top'
    assert http.last['params'] == {
        'n': 10, 'cell_type': 'microglia', 'offset': 10,
        'effect_gate': 'true', 'include_not_replicated': 'true',
        'catalog': 'Sierksma2025/WGCNA', 'exclude_secondary': 'false',
        'scope': 'human_postmortem'}
    assert frame['geneset_id'].tolist() == ['S/E/m']
    assert frame.attrs['effect_gate_rule'] == {'std_effect': 0.2}


def test_effects_overview(http, client):
    http.queue(make_response(200, {'facet': 'sex', 'headline': {}}))
    result = client.get_facet_effects_overview('sex', n=3, scope='all',
                                               exclude_secondary=False)
    assert http.last['url'] == f'{BASE}/facets/sex/effects/overview'
    assert http.last['params'] == {'n': 3, 'scope': 'all',
                                   'exclude_secondary': 'false'}
    assert result['facet'] == 'sex'


def test_geneset_facet_effects(http, client):
    client.get_geneset_facet_effects('S', 'E', 'm')
    assert http.last['url'] == f'{BASE}/genesets/S/E/m/facet-effects'
    assert http.last['params'] is None
    client.get_geneset_facet_effects(
        'S', 'E', 'm', facet=['sex', 'braak'], scope='human_postmortem',
        cell_type='microglia', exclude_secondary=False, include_units=True,
        forest='full')
    assert http.last['params'] == {
        'facet': 'sex,braak', 'scope': 'human_postmortem',
        'cell_type': 'microglia', 'exclude_secondary': 'false',
        'include_units': 'true', 'forest': 'full'}


def test_gene_detection_dataframe(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'gene': 'TREM2', 'summary': [{'pct_median': 3}],
                                   'datasets': [{'db_id': 'A/B', 'pct': 2.5}]}))
    frame = client.get_gene_detection('TREM2', format='dataframe')
    assert http.last['url'] == f'{BASE}/genes/TREM2/detection'
    assert frame['pct'].tolist() == [2.5]
    assert frame.attrs['summary'] == [{'pct_median': 3}]


# ── donor values and plot ───────────────────────────────────────────────


def test_donor_values_gene(http, client):
    client.get_facet_donor_values('sex', 'microglia', gene='XIST',
                                  db_id='F24/MIC', adjusted=True)
    assert http.last['url'] == f'{BASE}/facets/sex/donor-values'
    assert http.last['params'] == {'cell_type': 'microglia', 'gene': 'XIST',
                                   'db_id': 'F24/MIC', 'adjusted': 'true'}


def test_donor_values_module_as_tuple(http, client):
    client.get_facet_donor_values(
        'braak', 'microglia', module=('S', 'E', 'm'), method='pseudobulk',
        source='gene_list', include_uncounted=True, exclude_secondary=False)
    assert http.last['params'] == {
        'cell_type': 'microglia', 'module': 'S/E/m', 'method': 'pseudobulk',
        'source': 'gene_list', 'include_uncounted': 'true',
        'exclude_secondary': 'false'}


@pytest.mark.parametrize('kwargs', [{}, {'gene': 'XIST', 'module': 'S/E/m'}])
def test_donor_values_needs_exactly_one_subject(http, client, kwargs):
    with pytest.raises(ValueError):
        client.get_facet_donor_values('sex', 'microglia', **kwargs)
    assert http.calls == []


def test_donor_values_dataframe_one_row_per_donor(http, client):
    pytest.importorskip('pandas')
    body = {'scale': 'log2 CPM', 'facet_kind': 'two_group',
            'units': [{'db_id': 'A/B', 'cohort': 'C1', 'cell_type': 'mg',
                       'counted': True,
                       'donors': [{'label': 'D01', 'value': 1.0},
                                  {'label': 'D02', 'value': 2.0}]},
                      {'db_id': 'X/Y', 'available': False, 'donors': None}]}
    http.queue(make_response(200, body))
    frame = client.get_facet_donor_values('sex', 'microglia', gene='XIST',
                                          format='dataframe')
    assert frame['label'].tolist() == ['D01', 'D02']
    assert frame['db_id'].tolist() == ['A/B', 'A/B']
    assert frame.attrs['scale'] == 'log2 CPM'


def test_donor_plot_returns_caption_and_writes(http, client, tmp_path):
    http.queue(make_response(200, content=b'\x89PNG fake', headers={
        'Content-Type': 'image/png', 'X-Plot-Caption': 'XIST, facet sex',
        'X-Plot-Format': 'png'}))
    target = tmp_path / 'plot.png'
    result = client.get_facet_donor_plot('sex', 'microglia', gene='XIST',
                                         width=3, dpi=200, dest=target)
    assert http.last['url'] == f'{BASE}/facets/sex/donor-plot.png'
    assert http.last['params'] == {'cell_type': 'microglia', 'gene': 'XIST',
                                   'width': 3, 'dpi': 200}
    assert result['caption'] == 'XIST, facet sex'
    assert result['bytes'] == b'\x89PNG fake'
    assert result['path'] == target and target.read_bytes() == b'\x89PNG fake'


def test_donor_plot_rejects_bad_format(http, client):
    with pytest.raises(ValueError):
        client.get_facet_donor_plot('sex', 'microglia', gene='XIST',
                                    fmt='jpg')
    assert http.calls == []


# ── donor variability ───────────────────────────────────────────────────


def test_database_donor_variability_summary_and_rows(http, client):
    pytest.importorskip('pandas')
    client.get_database_donor_variability('G24/MMG')
    assert http.last['url'] == f'{BASE}/databases/G24/MMG/donor-variability'
    assert http.last['params'] is None
    http.queue(make_response(200, {'rows': [{'gene': 'HSPA1A'}]}))
    frame = client.get_database_donor_variability(
        'G24/MMG', 'gene', 'microglia', sort='sd', rung='D2',
        min_reliability=0.3, limit=10, format='dataframe')
    assert http.last['params'] == {
        'feature_type': 'gene', 'cell_type': 'microglia', 'sort': 'sd',
        'rung': 'D2', 'min_reliability': 0.3, 'limit': 10}
    assert frame['gene'].tolist() == ['HSPA1A']
    http.queue(make_response(200, {'status': 'analysed',
                                   'units': [{'cell_type': 'mg'}]}))
    frame = client.get_database_donor_variability('G24/MMG',
                                                  format='dataframe')
    assert frame['cell_type'].tolist() == ['mg']


def test_gene_and_geneset_donor_variability(http, client):
    client.get_gene_donor_variability('HSPA1A', rung='raw',
                                      exclude_secondary=False)
    assert http.last['url'] == f'{BASE}/genes/HSPA1A/donor-variability'
    assert http.last['params'] == {'rung': 'raw', 'exclude_secondary': 'false'}
    client.get_geneset_donor_variability('S', 'E', 'm', method='cell_mean',
                                         source='ucell')
    assert http.last['url'] == f'{BASE}/genesets/S/E/m/donor-variability'
    assert http.last['params'] == {'method': 'cell_mean', 'source': 'ucell'}


def test_donor_variability_top(http, client):
    http.queue(make_response(200, {'celltype_group': 'microglia', 'rows': []}))
    result = client.get_donor_variability_top(feature_type='module',
                                              min_cohorts=3, limit=5)
    assert http.last['url'] == f'{BASE}/donor-variability/top'
    assert http.last['params'] == {'feature_type': 'module', 'limit': 5,
                                   'min_cohorts': 3}
    assert result['celltype_group'] == 'microglia'


# ── ranks and DE summary ────────────────────────────────────────────────


def test_geneset_rank(http, client):
    client.get_geneset_rank('S', 'E', 'm')
    assert http.last['url'] == f'{BASE}/genesets/S/E/m/rank'
    assert http.last['params'] is None
    client.get_geneset_rank('S', 'E', 'm', db_id='F24/MIC')
    assert http.last['params'] == {'db_id': 'F24/MIC'}


def test_module_ranks_kebab_path(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'modules': [{'geneset_id': 'S/E/m',
                                                'rank': 0.8}]}))
    frame = client.get_module_ranks('F24/MIC', format='dataframe')
    assert http.last['url'] == f'{BASE}/databases/F24/MIC/module-ranks'
    assert frame['rank'].tolist() == [0.8]


def test_de_study_summary(http, client):
    pytest.importorskip('pandas')
    client.get_de_study_summary('A/B', 'st1')
    assert http.last['url'] == f'{BASE}/databases/A/B/de/st1/summary'
    assert http.last['params'] is None
    http.queue(make_response(200, {'contrasts': [{'term': 't', 'n_sig': 4}]}))
    frame = client.get_de_study_summary('A/B', 'st1', padj_max=0.1,
                                        format='dataframe')
    assert http.last['params'] == {'padj_max': 0.1}
    assert frame['n_sig'].tolist() == [4]


def test_unknown_dataset_404_raises(http, client):
    http.queue(make_response(404, {'detail': "Database 'X/Y' not found"}))
    with pytest.raises(requests.HTTPError):
        client.get_module_ranks('X/Y')
