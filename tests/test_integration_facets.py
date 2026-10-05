"""Integration test: the facet, facet-test, donor-group and
``exclude_secondary`` surface against a throw-away ant-serve that serves
the REAL h5adstore read-only.

The server runs from an anthive4 tree on a free loopback port with a
temporary state dir. It never sees the real store directly: the store is
mirrored as a tree of fresh directories holding symlinks to the real
files (``_``-prefixed and hidden folders are left out), so caches and
indexes the server creates land in the pytest tmp dir. The facet results
folder (``<store>/_facet_tests``) is passed as ``facet_results_dir``;
the server only reads it. After the run the test checks that no real
store file it could reach changed (mtime and size) and fails otherwise;
changes inside the facet results folder only warn, because
ant-facet-test reruns write there while other work goes on.

Skipped unless both are set:
    ANTHIVE4_SOURCE    anthive4 tree whose bin/api/ant-serve is run, e.g.
                       ``git -C anthive4 archive main | tar -x -C /tmp/a4``.
    ANTHIVE_IT_STORE   the real h5adstore (read only).

Run with::

    ANTHIVE4_SOURCE=/tmp/a4 ANTHIVE_IT_STORE=/path/to/h5adstore \\
        uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_integration_facets.py -v
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, Iterator, Tuple

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vark import AnthiveClient  # noqa: E402

SOURCE = os.environ.get('ANTHIVE4_SOURCE')
STORE = os.environ.get('ANTHIVE_IT_STORE')
pytestmark = pytest.mark.skipif(
    not (SOURCE and STORE),
    reason='set ANTHIVE4_SOURCE and ANTHIVE_IT_STORE to run')


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _mirror_store(real_store: Path, mirror: Path) -> Dict[Path, Tuple[float, int]]:
    """Mirror ``real_store`` as directories + file symlinks; return the
    (mtime, size) of every linked real file."""
    snapshot: Dict[Path, Tuple[float, int]] = {}
    for directory, subdirs, files in os.walk(real_store):
        subdirs[:] = [name for name in subdirs
                      if not name.startswith(('_', '.'))]
        relative = Path(directory).relative_to(real_store)
        target_dir = mirror / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.startswith('.'):
                continue
            real_file = Path(directory) / name
            try:
                stat = real_file.stat()
            except OSError:
                continue
            (target_dir / name).symlink_to(real_file)
            snapshot[real_file] = (stat.st_mtime, stat.st_size)
    return snapshot


def _snapshot_tree(root: Path) -> Dict[Path, Tuple[float, int]]:
    snapshot: Dict[Path, Tuple[float, int]] = {}
    for directory, _subdirs, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            stat = path.stat()
            snapshot[path] = (stat.st_mtime, stat.st_size)
    return snapshot


def _changed(before: Dict[Path, Tuple[float, int]]) -> list:
    changed = []
    for path, (mtime, size) in before.items():
        try:
            stat = path.stat()
        except OSError:
            changed.append(f'{path} (gone)')
            continue
        if (stat.st_mtime, stat.st_size) != (mtime, size):
            changed.append(str(path))
    return changed


@pytest.fixture(scope='module')
def server(tmp_path_factory) -> Iterator[dict]:
    source = Path(SOURCE).resolve()
    real_store = Path(STORE).resolve()
    serve = source / 'bin' / 'api' / 'ant-serve'
    assert serve.exists(), f'no ant-serve under {source}'
    facet_results = real_store / '_facet_tests'
    root = tmp_path_factory.mktemp('anthive-facets-it')
    mirror = root / 'h5adstore'
    store_snapshot = _mirror_store(real_store, mirror)
    results_snapshot = (_snapshot_tree(facet_results)
                        if facet_results.is_dir() else {})
    for folder in ('library', 'library_index', 'genesetstore'):
        (root / folder).mkdir()
    config = root / 'anthive.yaml'
    config.write_text(f"""\
h5adstore: {mirror}
facet_results_dir: {facet_results}
library: {root / 'library'}
library_index: {root / 'library_index'}
state_dir: {root / 'state'}
tmp_dir: {root / 'tmp'}
model_cache: {root / 'models'}
webapp_dir: {root / 'webapp'}
geneset_store: {root / 'genesetstore'}
catalog_scan: local
library_git_push: false
library_s3_autopush: false
auth:
  mode: none
s3:
  bucket: null
""")
    port = _free_port()
    env = {**os.environ, 'ANTHIVE_CONFIG': str(config),
           'HF_HUB_OFFLINE': '1', 'PYTHONUNBUFFERED': '1'}
    for key in list(env):
        if key.startswith('ANTHIVE_') and key != 'ANTHIVE_CONFIG':
            env.pop(key)
    log_path = root / 'ant-serve.log'
    log = open(log_path, 'w')
    process = subprocess.Popen(
        [str(serve), '--host', '127.0.0.1', '--port', str(port),
         '--data-folder', str(mirror)],
        cwd=str(source), env=env, stdout=log, stderr=subprocess.STDOUT)
    base_url = f'http://127.0.0.1:{port}'
    try:
        deadline = time.time() + 900
        while True:
            if process.poll() is not None:
                pytest.fail(f'ant-serve exited:\n{log_path.read_text()[-4000:]}')
            try:
                response = requests.get(f'{base_url}/databases', timeout=5)
                if response.status_code == 200 and response.json().get('total'):
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                pytest.fail(f'ant-serve did not come up:\n{log_path.read_text()[-4000:]}')
            time.sleep(2)
        yield {'base_url': base_url, 'log': log_path}
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
    changed = _changed(store_snapshot)
    assert not changed, ('real store files changed during the run (another '
                         f'process may have written them): {changed[:20]}')
    # The facet results folder is rewritten by ant-facet-test reruns, which
    # may run while this test does; the server only reads it (parquet and
    # json readers), so a change there is reported, not failed.
    changed_results = _changed(results_snapshot)
    if changed_results:
        warnings.warn('facet result files changed during the run (an '
                      f'ant-facet-test rerun?): {changed_results[:10]}')


@pytest.fixture(scope='module')
def client(server) -> AnthiveClient:
    return AnthiveClient(server['base_url'], vark_config=False, timeout=600)


@pytest.fixture(scope='module')
def sex_overview(client) -> dict:
    overview = client.get_facet_tests_across_datasets('ant_sex', top_genes=3)
    if not overview['rows']:
        pytest.skip('no tested sex units in this store')
    return overview


@pytest.fixture(scope='module')
def tested_unit(sex_overview) -> dict:
    """A primary, non-descriptive sex unit with genes at q < 0.05."""
    for row in sex_overview['rows']:
        if (not row['is_secondary']
                and not (row.get('flags') or {}).get('descriptive_only')
                and (row.get('genes') or {}).get('n_q05')):
            return row
    pytest.skip('no sex unit with significant genes')


# ── lineage and donor groups ────────────────────────────────────────────


def test_version(client):
    version = client.get_version()['version']
    assert tuple(int(part) for part in version.split('.')[:2]) >= (2, 42), version


def test_database_lineage_fields(client):
    databases = client.get_databases()
    assert databases
    for row in databases:
        assert row['designation'] in ('primary', 'reanalysis', 'unresolved')
        assert isinstance(row['reanalysis_of'], list)
        assert isinstance(row['has_donor_uid'], bool)
        assert 'donor_group' in row
        if row['designation'] != 'reanalysis':
            assert row['reanalysis_of'] == []
    info = client.get_database_info(databases[0]['id'])
    assert info['designation'] == databases[0]['designation']


def test_donor_groups(client):
    result = client.get_donor_groups()
    assert result['n_groups'] == len(result['groups'])
    if not result['groups']:
        pytest.skip('no donor groups in this store')
    for group in result['groups']:
        datasets = group['datasets']
        assert group['n_datasets'] == len(datasets)
        assert group['n_primary'] + group['n_reanalysis'] + group['n_unresolved'] \
            == len(datasets)
        assert group['n_cells'] == sum(d['n_cells'] for d in datasets
                                       if not d['is_secondary'])
    slug = result['groups'][0]['donor_group']
    one = client.get_donor_groups(slug)
    assert [g['donor_group'] for g in one['groups']] == [slug]
    with pytest.raises(requests.HTTPError) as excinfo:
        client.get_donor_groups('no-such-donor-group-xyz')
    assert excinfo.value.response.status_code == 404


def test_donor_groups_dataframe(client):
    pytest.importorskip('pandas')
    frame = client.get_donor_groups(format='dataframe')
    raw = client.get_donor_groups()
    assert len(frame) == sum(g['n_datasets'] for g in raw['groups'])


# ── exclude_secondary ───────────────────────────────────────────────────


def test_gene_stats_all_exclude_secondary(client):
    excluded = client.get_gene_stats_all('XIST')
    included = client.get_gene_stats_all('XIST', exclude_secondary=False)
    assert excluded['exclude_secondary'] is True
    assert included['exclude_secondary'] is False
    assert all(not r.get('is_secondary') for r in excluded['results'])
    # n_excluded_secondary counts secondaries before the layer and gene
    # checks, so it bounds the difference rather than equalling it.
    difference = len(included['results']) - len(excluded['results'])
    assert 0 <= difference <= excluded['n_excluded_secondary']
    assert included['n_excluded_secondary'] == 0


def test_module_variability_exclude_secondary(client):
    excluded = client.get_module_variability(limit=5)
    included = client.get_module_variability(limit=5, exclude_secondary=False)
    assert 'n_excluded_secondary' in excluded
    assert included.get('n_excluded_secondary', 0) == 0


# ── facets ──────────────────────────────────────────────────────────────


def test_list_facets_full(client):
    full = client.list_facets(full=True)
    assert isinstance(full['facets_visible'], list)
    assert full['definitions_status']['state']
    for row in full['facets']:
        assert isinstance(row['hidden_by_config'], bool)
        assert 'label' in row and 'defined' in row
    assert client.list_facets() == full['facets']


def test_get_facet_definition_mapping_and_secondary(client):
    detail = client.get_facet('ant_sex', top_modules=5)
    assert detail['definition']['status'] == 'registered'
    assert 'non_carriers' in detail
    assert any('mapping_kind' in row for row in detail['datasets'])
    included = client.get_facet('ant_sex', top_modules=5, mapping=False,
                                exclude_secondary=False)
    assert included.get('non_carriers') is None   # mapping=False
    assert not any('mapping_kind' in row for row in included['datasets'])
    assert included['exclude_secondary'] is False
    assert detail['total_n_cells'] <= included['total_n_cells']
    for row in detail['datasets']:
        if row.get('is_secondary'):
            assert row['counted'] is False


def test_get_database_facets(client, tested_unit):
    result = client.get_database_facets(tested_unit['db_id'])
    assert result['db_id'] == tested_unit['db_id']
    facets = {row['facet']: row for row in result['facets']}
    assert 'ant_sex' in facets
    assert facets['ant_sex']['mapping_kind'] in (
        'renamed', 'derived', 'constant', 'native', 'computed')
    fast = client.get_database_facets(tested_unit['db_id'], counts=False)
    assert {row['facet'] for row in fast['facets']} == set(facets)


# ── facet tests, one dataset ────────────────────────────────────────────


def test_facet_test_summary(client, tested_unit):
    summary = client.get_facet_tests(tested_unit['db_id'])
    assert summary['status'] == 'tested'
    units = [u for u in summary['units'] if u['facet'] == 'sex' and u['tested']]
    assert units
    model = units[0]['model']
    assert model['genes']['formula'].startswith('expression ~')
    assert 'descriptive_only' in units[0]['flags']


def test_facet_test_genes(client, tested_unit):
    db_id, cell_type = tested_unit['db_id'], tested_unit['cell_type']
    result = client.get_facet_test_genes(db_id, facet='sex', cell_type=cell_type,
                                         limit=5)
    assert 0 < result['n_returned'] <= 5
    assert all(row['q_value'] < 0.05 for row in result['rows'])
    csv_text = client.get_facet_test_genes(db_id, facet='sex',
                                           cell_type=cell_type, limit=3,
                                           format='csv')
    assert csv_text.splitlines()[0].startswith('facet,')
    with pytest.raises(requests.HTTPError) as excinfo:
        client.get_facet_test_genes(db_id, limit=5000)   # json cap is 2000
    assert excinfo.value.response.status_code == 400


def test_facet_test_genes_dataframe(client, tested_unit):
    pytest.importorskip('pandas')
    frame = client.get_facet_test_genes(tested_unit['db_id'], facet='sex',
                                        q=1, limit=10, format='dataframe')
    assert len(frame) == 10
    assert {'gene', 'logFC', 'q_value', 'descriptive_only'} <= set(frame.columns)


def test_facet_test_modules(client, sex_overview):
    with_modules = [row for row in sex_overview['rows'] if row.get('modules')]
    if not with_modules:
        pytest.skip('no sex unit with module results')
    row = with_modules[0]
    result = client.get_facet_test_modules(row['db_id'], facet='sex',
                                           cell_type=row['cell_type'],
                                           q=1, limit=5)
    assert result['n_returned'] > 0
    assert result['n_returned'] <= 5
    if result['rows']:
        assert {'q_param', 'p_perm', 'std_effect'} <= set(result['rows'][0])


def test_facet_test_volcano(client, tested_unit, tmp_path):
    png = client.get_facet_test_volcano(tested_unit['db_id'], 'sex',
                                        tested_unit['cell_type'],
                                        celltype_source=tested_unit['celltype_source'])
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


# ── facet tests, across datasets ────────────────────────────────────────


def test_across_datasets(sex_overview):
    assert sex_overview['facet_column'] == 'ant_sex'
    donors = [row.get('n_donors') or 0 for row in sex_overview['rows']]
    assert donors == sorted(donors, reverse=True)
    for row in sex_overview['rows']:
        assert 'celltype_group' in row and 'is_secondary' in row
        if row['is_secondary']:
            assert row['counted'] is False


def test_gene_effects_counted_and_reasons(client):
    card = client.get_facet_gene_effects('sex', 'XIST')
    assert card['units'], 'XIST not tested for sex'
    for unit in card['units']:
        if unit['counted']:
            assert unit['not_counted_reason'] is None
        else:
            assert unit['not_counted_reason']
        if unit['descriptive_only']:
            assert unit['q_value'] is None
    for entry in card['replication']:
        assert entry['cell_type'] == entry['celltype_group']
        assert isinstance(entry['labels'], list)
        assert 'cl_id' in entry
        assert entry['cohorts_sig_same_sign'] <= entry['cohorts_tested']
    assert 'replicated' in card['definition']


def test_gene_effects_dataframe(client):
    pytest.importorskip('pandas')
    frame = client.get_facet_gene_effects('ant_sex', 'XIST', format='dataframe')
    assert {'db_id', 'logFC', 'counted', 'not_counted_reason'} <= set(frame.columns)


def test_recurring_genes_ranking(client):
    result = client.get_facet_recurring_genes('sex', n=30)
    assert result['ranking']
    assert result['celltype_group'] == result['cell_type']
    keys = [(-row['cohorts_sig_same_sign'], -(row['agreement'] or 0),
             -(row['median_abs_logFC'] or 0)) for row in result['rows']]
    assert keys == sorted(keys)
    for row in result['rows']:
        assert row['cohorts_same_sign'] <= row['cohorts_tested']
        assert 0 <= row['agreement'] <= 1


def test_gene_facet_effects_all_facets(client):
    result = client.get_gene_facet_effects('XIST')
    assert set(result['facets']) == set(AnthiveClient.TESTED_FACETS)


def test_treatment_is_not_a_tested_facet(client):
    with pytest.raises(requests.HTTPError) as excinfo:
        client.get_facet_gene_effects('treatment', 'XIST')
    assert excinfo.value.response.status_code == 404


def test_cohorts(client):
    result = client.get_facet_cohorts()
    assert result['status'] == 'DRAFT'
    assert result['n_datasets'] == len(result['datasets'])
