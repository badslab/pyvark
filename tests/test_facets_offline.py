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
    assert AnthiveClient.TESTED_FACETS == (
        'sex', 'graft_sex', 'host_sex', 'disease', 'apoe4_carrier',
        'apoe4_dose', 'braak', 'braak_threshold', 'age', 'age_adjusted',
        'app_nlgf')
    caveats = AnthiveClient.FACET_TESTS_CAVEATS.lower()
    for phrase in ('exploratory', 'replicate', 'provisional', 'small_sample',
                   'below_floor', 'not_counted_reason', 'r_value < 0.05',
                   'effect_gate_passed', 'replicated_effect', 'lambda_gc',
                   'k of m is descriptive', 'per scope'):
        assert phrase in caveats


@pytest.mark.parametrize('name', [
    'get_facet_tests', 'get_facet_test_genes', 'get_facet_test_modules',
    'get_facet_tests_across_datasets', 'get_facet_gene_effects',
    'get_facet_recurring_genes', 'get_gene_facet_effects',
])
def test_facet_test_docstrings_state_caveats(name):
    doc = getattr(AnthiveClient, name).__doc__.lower()
    assert 'exploratory' in doc
    assert 'donor' in doc or 'replicate' in doc
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


# ── facet engine v2, replicate fields, apoe4 rename ────────────────────


def test_apoe4_rename_and_alias_map():
    assert 'apoe_carrier' not in AnthiveClient.TESTED_FACETS
    # API 2.45.0 removed the alias: it moved to REMOVED_FACET_ALIASES.
    assert AnthiveClient.DEPRECATED_FACET_ALIASES == {}
    assert AnthiveClient.REMOVED_FACET_ALIASES == {
        'apoe_carrier': 'apoe4_carrier',
        'ant_apoe_carrier': 'ant_apoe4_carrier'}


def test_recurring_genes_v2_fields_pass_through(http, client):
    body = {'n_replicated': 12, 'n_genes_in_family': 9000,
            'rows': [{'gene': 'PTPRG', 'r_value': 2e-14, 'p_pc': 1e-18,
                      'k': 4, 'm': 5, 'replicated': True}]}
    http.queue(make_response(200, body))
    result = client.get_facet_recurring_genes('braak')
    assert result['n_replicated'] == 12
    assert result['rows'][0]['replicated'] is True
    http.queue(make_response(200, body))
    frame = client.get_facet_recurring_genes('braak', format='dataframe')
    assert frame['r_value'].tolist() == [2e-14]
    assert frame.attrs == {'n_replicated': 12, 'n_genes_in_family': 9000}


def test_recurring_genes_dataframe_without_family_counts(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'rows': [{'gene': 'A'}]}))
    assert client.get_facet_recurring_genes(
        'sex', format='dataframe').attrs == {}


def test_gene_facet_effects_v2_entry_passes_through(http, client):
    entry = {'r_value': 1.0, 'replicated': False, 'k': 0, 'm': 2,
             'anchors': [{'db_id': 'F24/INN', 'p_treat': 0.5}],
             'replication_method': 'simes', 'legacy_badge': 'x'}
    http.queue(make_response(200, {'gene': 'PTPRG', 'facets': {
        'braak': {'replication': [entry], 'units': []}}}))
    result = client.get_gene_facet_effects('PTPRG')
    assert result['facets']['braak']['replication'][0] == entry


def test_databases_replicate_columns(http, client):
    pytest.importorskip('pandas')
    rows = [{'id': 'AZ5/SLM', 'replicate_unit': 'donor',
             'replicate_column': 'ant_donor', 'replicate_basis': 'declared',
             'disease_basis': 'braak_cerad'}]
    http.queue(make_response(200, {'databases': rows}))
    frame = client.get_databases(format='dataframe')
    assert frame.loc[0, 'replicate_unit'] == 'donor'
    assert frame.loc[0, 'disease_basis'] == 'braak_cerad'


def test_module_variability_dataframe_keeps_basis(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, {'basis': 'per-cell (descriptive)',
                                   'rows': [{'module': 'm1',
                                             'replicate_unit': 'donor'}]}))
    frame = client.get_module_variability(format='dataframe')
    assert frame.attrs['basis'] == 'per-cell (descriptive)'
    assert frame['replicate_unit'].tolist() == ['donor']


@pytest.mark.parametrize('name', ['get_module_variability',
                                  'get_gene_variance_by_facet'])
def test_per_cell_docstrings(name):
    doc = getattr(AnthiveClient, name).__doc__
    assert 'per-cell' in doc and 'descriptive' in doc


# ── API 2.44.0: facet scopes, replication tiers, new constants ──────────


SCOPE_METHODS = [
    ('get_facet', ('ant_age',), '/facets/ant_age'),
    ('get_facet_tests_across_datasets', ('age',), '/facets/age/tests'),
    ('get_facet_gene_effects', ('age', 'APOE'), '/facets/age/effects'),
    ('get_facet_recurring_genes', ('age',), '/facets/age/effects/top'),
    ('get_gene_facet_effects', ('TREM2',), '/genes/TREM2/facet-effects'),
    ('get_module_variability', (), '/module-variability'),
]


def test_api_target_and_constants():
    assert AnthiveClient.API_TARGET == '2.46.0'
    assert AnthiveClient.FACET_SCOPES == (
        'human_postmortem', 'xenograft_human_in_mouse', 'in_vitro')
    assert AnthiveClient.DEFAULT_FACET_SCOPE == 'human_postmortem'
    assert 'mouse_in_vivo' not in AnthiveClient.FACET_SCOPES
    deprecated = AnthiveClient.DEPRECATED_FACETS
    assert deprecated['region'] == ['tissue']
    assert len(deprecated['author_cluster']) == 7
    assert deprecated['lesion'] == []


@pytest.mark.parametrize('method,args,path', SCOPE_METHODS)
def test_scope_is_sent_when_given(http, client, method, args, path):
    http.queue(make_response(200, {'scope': 'xenograft_human_in_mouse'}))
    result = getattr(client, method)(
        *args, scope='xenograft_human_in_mouse')
    assert http.last['url'] == f'{BASE}{path}'
    assert http.last['params']['scope'] == 'xenograft_human_in_mouse'
    assert result['scope'] == 'xenograft_human_in_mouse'


@pytest.mark.parametrize('method,args,path', SCOPE_METHODS)
def test_scope_is_not_sent_by_default(http, client, method, args, path):
    http.queue(make_response(200, {}))
    getattr(client, method)(*args)
    assert 'scope' not in (http.last['params'] or {})


@pytest.mark.parametrize('method,args,path', SCOPE_METHODS)
def test_scope_docstring(method, args, path):
    doc = getattr(AnthiveClient, method).__doc__
    assert 'scope' in doc and 'FACET_SCOPES' in doc


def test_unknown_scope_raises_http_error(http, client):
    http.queue(make_response(400, {'detail': 'scope must be one of ...'}))
    with pytest.raises(requests.HTTPError):
        client.get_facet_recurring_genes('braak', scope='mouse_in_vivo')


def test_gene_facet_effects_keeps_exclude_secondary_with_scope(http, client):
    http.queue(make_response(200, {'gene': 'TREM2', 'facets': {},
                                   'by_scope': {}}))
    client.get_gene_facet_effects('TREM2', exclude_secondary=False,
                                  scope='human_postmortem')
    assert http.last['params'] == {'exclude_secondary': 'false',
                                   'scope': 'human_postmortem'}


def test_replication_entry_v3_fields_pass_through(http, client):
    entry = {'r_value': 0.001, 'replicated': True,
             'effect_gate_passed': False, 'effect_gate_cohorts': ['A'],
             'n_cohorts_ge_tau': 1, 'r_treat': 0.4,
             'replicated_effect': False, 'r_strong': None,
             'replicated_strong': None, 'n_small': 1, 'k_treat': 0}
    http.queue(make_response(200, {
        'scope': 'human_postmortem', 'scopes': ['human_postmortem'],
        'gene_flags': ['sex_chromosome'], 'units': [
            {'db_id': 'A/B', 'analysis_level': 'below_floor',
             'lambda_gc': 1.4, 'inflated': True,
             'covariates_dropped': ['pmi']}],
        'replication': [entry]}))
    result = client.get_facet_gene_effects('age', 'XIST')
    assert result['replication'][0] == entry
    assert result['units'][0]['analysis_level'] == 'below_floor'
    assert result['gene_flags'] == ['sex_chromosome']


def test_recurring_genes_dataframe_keeps_all_family_counts(http, client):
    pytest.importorskip('pandas')
    body = {'n_replicated': 3, 'n_genes_in_family': 100,
            'n_r_significant': 9, 'n_effect_gate': 5,
            'n_replicated_effect': 2,
            'rows': [{'gene': 'A', 'r_value': 0.01}]}
    http.queue(make_response(200, body))
    frame = client.get_facet_recurring_genes('braak', format='dataframe')
    assert frame.attrs == {key: value for key, value in body.items()
                           if key != 'rows'}


def test_databases_facet_fields(http, client):
    pytest.importorskip('pandas')
    rows = [{'id': 'X/Y', 'facet_scope': 'xenograft_human_in_mouse',
             'control_basis': 'wt_host'},
            {'id': 'M/N', 'facet_scope': None, 'control_basis': None}]
    http.queue(make_response(200, {'databases': rows}))
    frame = client.get_databases(format='dataframe')
    assert frame.loc[0, 'facet_scope'] == 'xenograft_human_in_mouse'
    assert frame['facet_scope'].isna().tolist() == [False, True]
    assert frame.loc[0, 'control_basis'] == 'wt_host'


@pytest.mark.parametrize('name', ['get_databases', 'get_database_info'])
def test_dataset_facet_field_docs(name):
    doc = getattr(AnthiveClient, name).__doc__
    for field in ('facet_scope', 'control_basis', 'replicate_basis'):
        assert field in doc
    assert 'facet_exclude' in AnthiveClient.get_databases.__doc__


def test_facet_docstrings_name_new_facets():
    doc = AnthiveClient.get_facet.__doc__
    for name in ('ant_age', 'ant_app_nlgf', 'ant_host_genotype',
                 'tissue_uberon', 'ant_mg_author_cluster'):
        assert name in doc
    tests_doc = AnthiveClient.get_facet_tests.__doc__
    for name in ('persists_after_pathology_adjustment', 'below_floor',
                 'lambda_gc', 'covariates_dropped', 'age_adjusted'):
        assert name in tests_doc


# ── help API (REST API 2.44.0) ──────────────────────────────────────────


def test_help_endpoints(http, client):
    http.queue(make_response(200, {'topics': [], 'glossary': []}))
    client.get_help()
    assert http.last['url'] == f'{BASE}/help'
    http.queue(make_response(200, {'id': 'facet-effects'}))
    client.get_help_topic('facet-effects')
    assert http.last['url'] == f'{BASE}/help/facet-effects'
    assert not http.last['params']
    http.queue(make_response(200, {'id': 'facet-effects'}))
    client.get_help_topic('facet-effects', include_children=False)
    assert http.last['params'] == {'include_children': 'false'}
    http.queue(make_response(200, {'terms': []}))
    client.get_glossary()
    assert http.last['url'] == f'{BASE}/help/glossary'
    assert not http.last['params']
    http.queue(make_response(200, {'terms': []}))
    client.get_glossary(format='html')
    assert http.last['params'] == {'format': 'html'}
    http.queue(make_response(200, {'slug': 'r-value'}))
    client.get_glossary_term('r-value')
    assert http.last['url'] == f'{BASE}/help/glossary/r-value'
    http.queue(make_response(200, {'matches': []}))
    client.search_help('replicate unit')
    assert http.last['url'] == f'{BASE}/help/search'
    assert http.last['params'] == {'q': 'replicate unit'}


def test_get_glossary_bad_format(client):
    with pytest.raises(ValueError):
        client.get_glossary(format='pdf')


def test_help_404_raises(http, client):
    http.queue(make_response(404, {'detail': "Unknown help topic 'x'"}))
    with pytest.raises(requests.HTTPError):
        client.get_help_topic('x')


TOPIC = {'id': 'facet-counting', 'title': 'Counting', 'summary': 'Sum.',
         'body': 'Body text.', 'related': ['facet-effects'],
         'terms': ['r-value']}


def test_explain_topic(http, client):
    http.queue(make_response(200, {'matches': [
        {'id': 'facet-counting', 'kind': 'topic', 'score': 1, 'title': 'C'},
        {'id': 'r-value', 'kind': 'term', 'score': 0.5, 'title': 'r'}]}))
    http.queue(make_response(200, TOPIC))
    text = client.explain('counting')
    assert http.last['url'] == f'{BASE}/help/facet-counting'
    assert text.startswith('# Counting\n\nSum.\n\nBody text.')
    assert 'Related topics: `facet-effects`' in text
    assert 'Glossary terms: `r-value`' in text
    assert text.endswith('Other close matches: term `r-value`')


def test_explain_term(http, client):
    http.queue(make_response(200, {'matches': [
        {'id': 'r-value', 'kind': 'term', 'score': 1, 'title': 'r'}]}))
    http.queue(make_response(200, {'slug': 'r-value', 'term': 'r-value',
                                   'definition': 'Defn.'}))
    assert client.explain('r-value') == '# r-value (glossary)\n\nDefn.'


def test_explain_topic_without_links(http, client):
    http.queue(make_response(200, {'matches': [
        {'id': 't', 'kind': 'topic', 'score': 1, 'title': 'T'}]}))
    http.queue(make_response(200, {'title': 'T', 'summary': 'S', 'body': 'B'}))
    assert client.explain('t') == '# T\n\nS\n\nB'


INDEX = {'topics': [{'id': 'facet-effects', 'title': 'Effects',
                     'summary': 'How.'}],
         'glossary': [{'slug': 'r-value', 'term': 'r-value'}]}


@pytest.mark.parametrize('query', ['', '   ', 'zzz'])
def test_explain_falls_back_to_index(http, client, query):
    if query.strip():
        http.queue(make_response(200, {'matches': []}))
    http.queue(make_response(200, INDEX))
    text = client.explain(query)
    assert '- `facet-effects`: Effects. How.' in text
    assert '`r-value`' in text
    assert text.startswith('No help topic' if query.strip()
                           else '# Anthive help topics')


def test_explain_empty_glossary(http, client):
    http.queue(make_response(200, {'topics': [], 'glossary': []}))
    assert client.explain().endswith('(none)')


@pytest.mark.parametrize('name', [
    'get_facet_tests', 'get_facet_tests_across_datasets',
    'get_facet_gene_effects', 'get_facet_recurring_genes',
    'get_gene_facet_effects', 'get_database_context'])
def test_help_topics_documented(name):
    assert 'help_topics' in getattr(AnthiveClient, name).__doc__


def test_help_topics_pass_through(http, client):
    http.queue(make_response(200, {'gene': 'A', 'facets': {},
                                   'help_topics': ['facet-effects']}))
    assert client.get_gene_facet_effects('A')['help_topics'] == [
        'facet-effects']


# ── gene card trimming and late 2.44.0 fields ───────────────────────────


@pytest.mark.parametrize('facet,expected', [
    ('age', 'age'), (['age', 'braak'], 'age,braak'), (('sex',), 'sex')])
def test_gene_facet_effects_facet_param(http, client, facet, expected):
    http.queue(make_response(200, {'gene': 'A', 'facets': {}}))
    client.get_gene_facet_effects('A', facet=facet)
    assert http.last['params'] == {'facet': expected}


def test_gene_facet_effects_include_units_false(http, client):
    http.queue(make_response(200, {'gene': 'A', 'facets': {
        'sex': {'n_units': 3, 'units': [], 'replication': []}}}))
    result = client.get_gene_facet_effects(
        'A', include_units=False, scope='human_postmortem',
        exclude_secondary=False, facet='sex')
    assert http.last['params'] == {
        'exclude_secondary': 'false', 'scope': 'human_postmortem',
        'facet': 'sex', 'include_units': 'false'}
    assert result['facets']['sex']['n_units'] == 3


def test_gene_facet_effects_defaults_send_nothing(http, client):
    http.queue(make_response(200, {'gene': 'A', 'facets': {}}))
    client.get_gene_facet_effects('A')
    assert not http.last['params']


def test_gene_facet_effects_docstring_names_trimming():
    doc = AnthiveClient.get_gene_facet_effects.__doc__
    for word in ('include_units', 'facet', 'replicate_unit',
                 'replicate_column', 'empty'):
        assert word in doc


def test_recurring_genes_strong_tier(http, client):
    pytest.importorskip('pandas')
    body = {'n_replicated': 2, 'n_replicated_strong': 1, 'rows': [
        {'gene': 'A', 'r_strong': 0.01, 'replicated_strong': True,
         'persists_after_pathology_adjustment': True}]}
    http.queue(make_response(200, body))
    assert client.get_facet_recurring_genes('age')['rows'][0][
        'persists_after_pathology_adjustment'] is True
    http.queue(make_response(200, body))
    frame = client.get_facet_recurring_genes('age', format='dataframe')
    assert frame.attrs == {'n_replicated': 2, 'n_replicated_strong': 1}
    doc = AnthiveClient.get_facet_recurring_genes.__doc__
    for word in ('r_strong', 'replicated_strong', 'n_replicated_strong',
                 'persists_after_pathology_adjustment'):
        assert word in doc


def test_facet_exclude_fields(http, client):
    pytest.importorskip('pandas')
    rows = [{'id': 'S/P', 'facet_exclude': True,
             'facet_exclude_reason': 'spatial'},
            {'id': 'A/B', 'facet_exclude': False,
             'facet_exclude_reason': None}]
    http.queue(make_response(200, {'databases': rows}))
    frame = client.get_databases(format='dataframe')
    assert frame['facet_exclude'].tolist() == [True, False]
    for name in ('get_databases', 'get_database_info', 'get_facet_tests'):
        assert 'facet_exclude_reason' in getattr(AnthiveClient, name).__doc__
