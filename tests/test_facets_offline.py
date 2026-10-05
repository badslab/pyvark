"""Offline tests for the facet, facet-test, donor-group and
``exclude_secondary`` surface added in pyvark 0.8.0. HTTP is mocked with
the recorder from ``test_library_offline``: every request is captured and
answered with an in-memory ``requests.Response``.

Run with::

    uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_facets_offline.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vark import AnthiveClient  # noqa: E402
from test_library_offline import (  # noqa: E402,F401  (fixtures)
    BASE,
    client,
    http,
    make_response,
)


# ── surface ─────────────────────────────────────────────────────────────


def test_new_methods_exist():
    expected = {
        'get_donor_groups', 'get_database_facets', 'get_facet_tests',
        'get_facet_test_genes', 'get_facet_test_modules',
        'get_facet_test_volcano', 'get_facet_tests_across_datasets',
        'get_facet_gene_effects', 'get_facet_recurring_genes',
        'get_gene_facet_effects', 'get_facet_cohorts',
    }
    assert not expected - set(dir(AnthiveClient))


def test_tested_facets_and_caveats():
    assert AnthiveClient.TESTED_FACETS == ('sex', 'disease', 'apoe_carrier', 'braak')
    caveats = AnthiveClient.FACET_TESTS_CAVEATS.lower()
    for phrase in ('exploratory', 'donor', 'provisional', 'descriptive_only',
                   'not_counted_reason', 'k of m independent cohorts'):
        assert phrase in caveats


@pytest.mark.parametrize('name', [
    'get_facet_tests', 'get_facet_test_genes', 'get_facet_test_modules',
    'get_facet_tests_across_datasets', 'get_facet_gene_effects',
    'get_facet_recurring_genes', 'get_gene_facet_effects',
])
def test_facet_test_docstrings_state_caveats(name):
    doc = getattr(AnthiveClient, name).__doc__.lower()
    assert 'exploratory' in doc
    assert 'donor' in doc
    assert 'provisional' in doc


# ── donor groups and lineage ────────────────────────────────────────────


DONOR_GROUPS = {
    'n_groups': 1, 'n_ungrouped': 5,
    'groups': [{
        'donor_group': 'rosmap', 'n_datasets': 2, 'n_primary': 1,
        'n_reanalysis': 1, 'n_unresolved': 0, 'n_cells': 1000,
        'has_donor_uid': False, 'n_donors_distinct': 40,
        'datasets': [
            {'db_id': 'M23/MIC', 'title': 'a', 'group': 'Mathys2023',
             'designation': 'primary', 'is_secondary': False,
             'reanalysis_of': [], 'has_donor_uid': False, 'n_cells': 1000},
            {'db_id': 'GF4/MIC', 'title': 'b', 'group': 'Green2024',
             'designation': 'reanalysis', 'is_secondary': True,
             'reanalysis_of': ['M23/MIC'], 'has_donor_uid': False,
             'n_cells': 800},
        ]}],
}


def test_get_donor_groups(http, client):
    http.queue(make_response(200, DONOR_GROUPS))
    result = client.get_donor_groups()
    assert http.last['url'] == f'{BASE}/donor-groups'
    assert http.last['params'] is None
    assert result['groups'][0]['n_donors_distinct'] == 40   # passed through


def test_get_donor_groups_one_group(http, client):
    http.queue(make_response(200, DONOR_GROUPS))
    client.get_donor_groups('rosmap')
    assert http.last['params'] == {'donor_group': 'rosmap'}


def test_get_donor_groups_unknown_raises(http, client):
    http.queue(make_response(404, {'detail': 'No dataset has donor_group'}))
    with pytest.raises(requests.HTTPError):
        client.get_donor_groups('nope')


def test_get_donor_groups_dataframe(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, DONOR_GROUPS))
    frame = client.get_donor_groups(format='dataframe')
    assert len(frame) == 2
    assert set(frame['donor_group']) == {'rosmap'}
    assert list(frame['designation']) == ['primary', 'reanalysis']
    assert frame['group_n_cells'].tolist() == [1000, 1000]
    assert frame['group_n_donors_distinct'].tolist() == [40, 40]
    assert frame['n_cells'].tolist() == [1000, 800]


def test_get_databases_passes_lineage_fields(http, client):
    rows = [{'id': 'M23/MIC', 'designation': 'primary', 'reanalysis_of': [],
             'donor_group': 'rosmap', 'has_donor_uid': False,
             'is_secondary': False},
            {'id': 'GF4/MIC', 'designation': 'reanalysis',
             'reanalysis_of': ['M23/MIC'], 'donor_group': 'rosmap',
             'has_donor_uid': False, 'is_secondary': True}]
    http.queue(make_response(200, {'databases': rows, 'total': 2}))
    result = client.get_databases(primary_only=True)
    assert [row['id'] for row in result] == ['M23/MIC']
    assert result[0]['donor_group'] == 'rosmap'


# ── exclude_secondary ───────────────────────────────────────────────────


def test_gene_stats_all_exclude_secondary_default_not_sent(http, client):
    http.queue(make_response(200, {'results': []}))
    client.get_gene_stats_all('APOE')
    assert 'exclude_secondary' not in http.last['params']


def test_gene_stats_all_include_secondary(http, client):
    http.queue(make_response(200, {'results': []}))
    client.get_gene_stats_all('APOE', exclude_secondary=False)
    assert http.last['params']['exclude_secondary'] == 'false'


def test_gene_stats_all_dataframe_has_is_secondary(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'results': [
        {'db_id': 'A/B', 'title': 't', 'n_cells': 5, 'layer': 'X',
         'is_secondary': True, 'stats': [{'gene': 'APOE', 'mean': 1.0}]},
        {'db_id': 'C/D', 'title': 'u', 'n_cells': 6, 'layer': 'X',
         'stats': [{'gene': 'APOE', 'mean': 2.0}]}]}))
    frame = client.get_gene_stats_all('APOE', format='dataframe')
    assert frame['is_secondary'].tolist() == [True, False]


def test_module_variability_exclude_secondary(http, client):
    http.queue(make_response(200, {'rows': []}))
    client.get_module_variability(exclude_secondary=False)
    assert http.last['params']['exclude_secondary'] == 'false'
    http.queue(make_response(200, {'rows': []}))
    client.get_module_variability()
    assert 'exclude_secondary' not in http.last['params']


# ── facets ──────────────────────────────────────────────────────────────


FACETS = {'n_facets': 1, 'facets_visible': ['ant_sex'],
          'definitions_status': {'state': 'under_audit', 'note': 'n'},
          'facets': [{'facet': 'ant_sex', 'type': 'categorical',
                      'hidden_by_config': False, 'label': 'Sex',
                      'summary': 's', 'defined': True}]}


def test_list_facets_default_is_list(http, client):
    http.queue(make_response(200, FACETS))
    assert client.list_facets() == FACETS['facets']


def test_list_facets_full(http, client):
    http.queue(make_response(200, FACETS))
    result = client.list_facets(full=True)
    assert result['facets_visible'] == ['ant_sex']
    assert result['definitions_status']['state'] == 'under_audit'


def test_get_facet_mapping_and_secondary_params(http, client):
    http.queue(make_response(200, {'facet': 'ant_sex'}))
    client.get_facet('ant_sex')
    assert http.last['params'] == {'top_modules': 200}
    http.queue(make_response(200, {'facet': 'ant_sex'}))
    client.get_facet('ant_sex', mapping=False, exclude_secondary=False)
    assert http.last['params'] == {'top_modules': 200, 'mapping': 'false',
                                   'exclude_secondary': 'false'}


def test_get_database_facets(http, client):
    http.queue(make_response(200, {'db_id': 'G24/MMG', 'facets': []}))
    client.get_database_facets('G24/MMG')
    assert http.last['url'] == f'{BASE}/databases/G24/MMG/facets'
    assert http.last['params'] is None
    http.queue(make_response(200, {'db_id': 'G24/MMG', 'facets': []}))
    client.get_database_facets('G24/MMG', counts=False)
    assert http.last['params'] == {'counts': 'false'}


# ── facet tests, one dataset ────────────────────────────────────────────


def test_get_facet_tests(http, client):
    summary = {'db_id': 'G24/MMG', 'status': 'tested', 'units': [
        {'facet': 'sex', 'cell_type': 'microglial cell', 'tested': True,
         'flags': {'descriptive_only': False}, 'model': {'genes': {
             'formula': 'expression ~ sex + age_z + pmi_z'}}}]}
    http.queue(make_response(200, summary))
    result = client.get_facet_tests('G24/MMG')
    assert http.last['url'] == f'{BASE}/databases/G24/MMG/facet-tests'
    assert result['units'][0]['model']['genes']['formula'].startswith('expression ~')


def test_get_facet_test_genes_params(http, client):
    http.queue(make_response(200, {'n_matching': 1, 'n_returned': 1,
                                   'rows': [{'gene': 'XIST', 'logFC': -5.0}]}))
    result = client.get_facet_test_genes('G24/MMG', facet='sex',
                                         cell_type='microglial cell', q=1,
                                         sort='effect', limit=10)
    assert http.last['url'] == f'{BASE}/databases/G24/MMG/facet-tests/genes'
    assert http.last['params'] == {'facet': 'sex', 'cell_type': 'microglial cell',
                                   'q': 1, 'sort': 'effect', 'limit': 10}
    assert result['rows'][0]['gene'] == 'XIST'


def test_get_facet_test_genes_csv(http, client):
    http.queue(make_response(200, content=b'gene,logFC\nXIST,-5\n',
                             headers={'Content-Type': 'text/csv'}))
    text = client.get_facet_test_genes('G24/MMG', format='csv', limit=5000)
    assert text.startswith('gene,logFC')
    assert http.last['params']['format'] == 'csv'
    assert http.last['params']['limit'] == 5000


def test_get_facet_test_genes_dataframe(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'rows': [{'gene': 'XIST', 'logFC': -5.0},
                                            {'gene': 'RPS4Y1', 'logFC': 6.0}]}))
    frame = client.get_facet_test_genes('G24/MMG', format='dataframe')
    assert frame['gene'].tolist() == ['XIST', 'RPS4Y1']
    assert 'format' not in http.last['params']


def test_get_facet_test_genes_bad_format(client):
    with pytest.raises(ValueError):
        client.get_facet_test_genes('G24/MMG', format='parquet')


def test_get_facet_test_modules_params(http, client):
    http.queue(make_response(200, {'rows': []}))
    client.get_facet_test_modules('G24/MMG', facet='braak', method='cell_mean',
                                  source='geneset', q_by='perm', sort='q_perm')
    assert http.last['url'] == f'{BASE}/databases/G24/MMG/facet-tests/modules'
    assert http.last['params'] == {'facet': 'braak', 'method': 'cell_mean',
                                   'source': 'geneset', 'q': 0.05,
                                   'q_by': 'perm', 'sort': 'q_perm',
                                   'limit': 100}


def test_get_facet_test_volcano(http, client, tmp_path):
    http.queue(make_response(200, content=b'\x89PNG fake',
                             headers={'Content-Type': 'image/png'}))
    png = client.get_facet_test_volcano('G24/MMG', 'sex', 'microglial cell')
    assert png.startswith(b'\x89PNG')
    assert http.last['url'] == f'{BASE}/databases/G24/MMG/facet-tests/volcano.png'
    assert http.last['params'] == {'facet': 'sex', 'cell_type': 'microglial cell'}
    http.queue(make_response(200, content=b'\x89PNG fake',
                             headers={'Content-Type': 'image/png'}))
    target = client.get_facet_test_volcano('G24/MMG', 'sex', 'microglial cell',
                                           celltype_source='constant_all_cells',
                                           dest=tmp_path / 'v.png')
    assert target.read_bytes().startswith(b'\x89PNG')
    assert http.last['params']['celltype_source'] == 'constant_all_cells'


def test_get_facet_test_volcano_404(http, client):
    http.queue(make_response(404, {'detail': 'no gene-level p values'}))
    with pytest.raises(requests.HTTPError):
        client.get_facet_test_volcano('G24/MMG', 'braak', 'microglial cell')


# ── facet tests, across datasets ────────────────────────────────────────


def test_get_facet_tests_across_datasets(http, client):
    http.queue(make_response(200, {'facet': 'sex', 'rows': [{'db_id': 'A/B'}],
                                   'not_tested': []}))
    result = client.get_facet_tests_across_datasets('ant_sex', top_genes=3)
    assert http.last['url'] == f'{BASE}/facets/ant_sex/tests'
    assert http.last['params'] == {'top_genes': 3}
    assert result['rows'][0]['db_id'] == 'A/B'
    http.queue(make_response(200, {'rows': []}))
    client.get_facet_tests_across_datasets('sex', exclude_secondary=False)
    assert http.last['params'] == {'top_genes': 5, 'exclude_secondary': 'false'}


def test_get_facet_gene_effects(http, client):
    card = {'gene': 'XIST', 'units': [
        {'db_id': 'A/B', 'counted': False,
         'not_counted_reason': 'secondary dataset (reanalysis)'}],
        'replication': [{'celltype_group': 'microglia', 'cl_id': 'CL:0000129',
                         'labels': ['MG'], 'cohorts_tested': 3,
                         'cohorts_sig_same_sign': 3}]}
    http.queue(make_response(200, card))
    result = client.get_facet_gene_effects('sex', 'xist', cell_type='microglia')
    assert http.last['url'] == f'{BASE}/facets/sex/effects'
    assert http.last['params'] == {'gene': 'xist', 'cell_type': 'microglia'}
    assert result['replication'][0]['cl_id'] == 'CL:0000129'


def test_get_facet_gene_effects_dataframe(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'units': [{'db_id': 'A/B', 'logFC': 1.0}]}))
    frame = client.get_facet_gene_effects('sex', 'XIST', format='dataframe',
                                          exclude_secondary=False)
    assert frame['db_id'].tolist() == ['A/B']
    assert http.last['params'] == {'gene': 'XIST', 'exclude_secondary': 'false'}


def test_get_facet_recurring_genes(http, client):
    body = {'celltype_group': 'microglia', 'ranking': 'genes ranked by (1) k',
            'rows': [{'gene': 'XIST', 'cohorts_sig_same_sign': 9,
                      'cohorts_tested': 9, 'cohorts_same_sign': 9,
                      'agreement': 1.0, 'median_abs_logFC': 5.2}]}
    http.queue(make_response(200, body))
    result = client.get_facet_recurring_genes('ant_sex', n=10)
    assert http.last['url'] == f'{BASE}/facets/ant_sex/effects/top'
    assert http.last['params'] == {'n': 10}
    assert result['rows'][0]['agreement'] == 1.0
    http.queue(make_response(200, body))
    client.get_facet_recurring_genes('sex', cell_type='Mic P2RY12',
                                     exclude_secondary=False)
    assert http.last['params'] == {'n': 50, 'cell_type': 'Mic P2RY12',
                                   'exclude_secondary': 'false'}


def test_get_facet_recurring_genes_dataframe(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'rows': [{'gene': 'XIST'}, {'gene': 'UTY'}]}))
    frame = client.get_facet_recurring_genes('sex', format='dataframe')
    assert frame['gene'].tolist() == ['XIST', 'UTY']


def test_get_gene_facet_effects(http, client):
    http.queue(make_response(200, {'gene': 'APOE', 'facets': {'sex': {}}}))
    result = client.get_gene_facet_effects('APOE')
    assert http.last['url'] == f'{BASE}/genes/APOE/facet-effects'
    assert http.last['params'] is None
    assert 'sex' in result['facets']
    http.queue(make_response(200, {'gene': 'APOE', 'facets': {}}))
    client.get_gene_facet_effects('APOE', exclude_secondary=False)
    assert http.last['params'] == {'exclude_secondary': 'false'}


def test_get_facet_cohorts(http, client):
    body = {'status': 'DRAFT', 'n_datasets': 1,
            'datasets': [{'db_id': 'A/B', 'cohort': 'X', 'counted': True}]}
    http.queue(make_response(200, body))
    assert client.get_facet_cohorts()['status'] == 'DRAFT'
    assert http.last['url'] == f'{BASE}/facets/cohorts'


def test_get_facet_cohorts_dataframe(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'datasets': [{'db_id': 'A/B'}]}))
    frame = client.get_facet_cohorts(format='dataframe')
    assert frame['db_id'].tolist() == ['A/B']
