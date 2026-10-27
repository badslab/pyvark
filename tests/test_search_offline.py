"""Offline tests for the catalogue search and the front-page numbers
(anthive REST API 2.48.0): ``AnthiveClient.search`` for
``GET /search`` and ``AnthiveClient.stats`` for ``GET /stats``. HTTP is
mocked with the recorder from ``test_library_offline``.

Run with::

    uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_search_offline.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vark import AnthiveClient, ArtefactNotFoundError, ServerTooOldError  # noqa: E402
from test_library_offline import (  # noqa: E402,F401  (fixtures)
    BASE,
    client,
    http,
    make_response,
)


SEARCH_ANSWER = {
    'query': 'TREM2 microglia',
    'words': ['trem2', 'microglia'],
    'gene_words': ['trem2'],
    'datasets': [
        {'db_id': 'M24/M23', 'group_id': 'M24', 'file_id': 'M23',
         'title': 'Mancuso_2023', 'n_cells': 127755,
         'matched_in': ['collection', 'cell_types']},
        {'db_id': 'WA4/MPF', 'group_id': 'WA4', 'file_id': 'MPF',
         'title': 'Wachter2024_Micro_PFC', 'n_cells': 75740,
         'matched_in': ['collection']},
    ],
    'n_datasets': 9,
    'datasets_basis': 'mentions',
    'collections': [{'group_id': 'WA4', 'title': 'Wachter2024',
                     'kind': 'datasets', 'matched_in': ['collection']}],
    'n_collections': 1,
    'genes': [{'gene': 'TREM2', 'n_datasets': 140}],
    'suggestions': [],
    'genesets': None,
    'n_genesets': None,
    'papers': [{'citekey': 'mancuso2024', 'title': 'Xenografted microglia',
                'authors': 'Mancuso R', 'year': 2024, 'doi': '10.1/x',
                'matched_in': ['title'],
                'passages': [{'page_start': 3, 'page_end': 3,
                              'section': 'results', 'snippet': 'TREM2 ...'}]}],
    'n_papers': 1,
    'artefacts': [], 'n_artefacts': 0,
    'facets': [], 'n_facets': 0,
    'help': [], 'n_help': 0,
}


# ── search ──────────────────────────────────────────────────────────────


def test_search_minimal_sends_only_q(http, client):
    http.queue(make_response(200, SEARCH_ANSWER))
    result = client.search('TREM2 microglia')
    assert result == SEARCH_ANSWER
    assert http.last['method'] == 'GET'
    assert http.last['url'] == f'{BASE}/search'
    assert http.last['params'] == {'q': 'TREM2 microglia'}
    assert http.last['auth'] == ('tester', 'not-a-real-password')


def test_search_limit_and_kind_list(http, client):
    http.queue(make_response(200, SEARCH_ANSWER))
    client.search('TREM2', limit=5, kind=['genes', 'papers'])
    assert http.last['params'] == {'q': 'TREM2', 'limit': 5,
                                   'kind': 'genes,papers'}


@pytest.mark.parametrize('kind, sent', [
    ('datasets', 'datasets'),
    ('genes,papers', 'genes,papers'),
    (('help', 'facets'), 'help,facets'),
    (['artefacts', ' collections '], 'artefacts,collections'),
])
def test_search_kind_forms(http, client, kind, sent):
    http.queue(make_response(200, SEARCH_ANSWER))
    client.search('x', kind=kind)
    assert http.last['params']['kind'] == sent


def test_search_kinds_constant_covers_the_response_groups():
    assert set(AnthiveClient.SEARCH_KINDS) == {
        'datasets', 'collections', 'genes', 'genesets', 'papers',
        'artefacts', 'facets', 'help'}
    for kind in AnthiveClient.SEARCH_KINDS:
        assert kind in SEARCH_ANSWER


def test_search_unknown_kind_is_refused_before_any_request(http, client):
    with pytest.raises(ValueError, match='unknown search kind'):
        client.search('TREM2', kind='dataset')
    with pytest.raises(ValueError, match='unknown search kind'):
        client.search('TREM2', kind=['genes', 'cells'])
    assert http.calls == []


@pytest.mark.parametrize('query', ['', '   '])
def test_search_empty_query_is_refused(http, client, query):
    with pytest.raises(ValueError, match='at least one word'):
        client.search(query)
    assert http.calls == []


def test_search_null_groups_pass_through(http, client):
    http.queue(make_response(200, SEARCH_ANSWER))
    result = client.search('TREM2')
    assert result['genesets'] is None
    assert result['n_genesets'] is None


def test_search_dataframe_one_kind(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, SEARCH_ANSWER))
    frame = client.search('TREM2 microglia', kind='datasets',
                          format='dataframe')
    assert list(frame['db_id']) == ['M24/M23', 'WA4/MPF']
    assert frame.loc[0, 'matched_in'] == ['collection', 'cell_types']
    assert http.last['params']['kind'] == 'datasets'


def test_search_dataframe_papers_keep_passages(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, SEARCH_ANSWER))
    frame = client.search('TREM2', kind=['papers'], format='dataframe')
    assert list(frame['citekey']) == ['mancuso2024']
    assert frame.loc[0, 'passages'][0]['section'] == 'results'


def test_search_dataframe_null_group_is_empty(http, client):
    pytest.importorskip('pandas')
    http.queue(make_response(200, SEARCH_ANSWER))
    frame = client.search('TREM2', kind='genesets', format='dataframe')
    assert frame.empty


@pytest.mark.parametrize('kind', [None, ['genes', 'papers']])
def test_search_dataframe_needs_exactly_one_kind(http, client, kind):
    with pytest.raises(ValueError, match='exactly one kind'):
        client.search('TREM2', kind=kind, format='dataframe')
    assert http.calls == []


def test_search_unknown_format(http, client):
    with pytest.raises(ValueError, match="'json' or 'dataframe'"):
        client.search('TREM2', format='csv')
    assert http.calls == []


def test_search_422_stays_http_error(http, client):
    http.queue(make_response(422, {'detail': [{'loc': ['query', 'limit'],
                                               'msg': 'too large'}]}))
    with pytest.raises(requests.HTTPError) as caught:
        client.search('TREM2', limit=10000)
    assert not isinstance(caught.value, ServerTooOldError)
    assert len(http.calls) == 1


# ── stats ───────────────────────────────────────────────────────────────


def test_stats_passes_the_dict_through(http, client):
    answer = {'n_datasets': 153, 'n_collections': 63, 'n_cells': 17028665,
              'n_genes': None, 'organisms': {'human': 130, 'mouse': 19},
              'recently_updated': [{'db_id': 'Z20/ALL'}],
              'some_future_key': 1}
    http.queue(make_response(200, answer))
    assert client.stats() == answer
    assert http.last['method'] == 'GET'
    assert http.last['url'] == f'{BASE}/stats'
    assert http.last['params'] is None


# ── servers older than 2.48.0 ───────────────────────────────────────────


@pytest.mark.parametrize('call, route', [
    (lambda c: c.search('TREM2'), '/search'),
    (lambda c: c.stats(), '/stats'),
])
def test_old_server_raises_server_too_old(http, client, call, route):
    http.queue(make_response(404, {'detail': 'Not Found'},
                             url=f'{BASE}{route}'),
               make_response(200, {'version': '2.47.2'}))
    with pytest.raises(ServerTooOldError) as caught:
        call(client)
    error = caught.value
    assert error.status_code == 404
    assert error.required_version == '2.48.0'
    assert error.server_version == '2.47.2'
    assert '2.48.0+' in str(error) and '2.47.2' in str(error)
    assert route in str(error)
    assert isinstance(error, requests.HTTPError)
    assert not isinstance(error, ArtefactNotFoundError)
    assert http.calls[1]['url'] == f'{BASE}/version'


def test_old_server_version_unreadable(http, client):
    http.queue(make_response(404, {'detail': 'Not Found'}),
               make_response(500, {}), make_response(500, {}))
    with pytest.raises(ServerTooOldError, match='version unknown'):
        client.stats()


def test_new_server_404_with_other_detail_is_plain_http_error(http, client):
    http.queue(make_response(404, {'detail': 'something else'}))
    with pytest.raises(requests.HTTPError) as caught:
        client.stats()
    assert not isinstance(caught.value, ServerTooOldError)
    assert len(http.calls) == 1


def test_new_methods_are_documented_with_api_version():
    for name in ('search', 'stats'):
        assert '2.48.0' in getattr(AnthiveClient, name).__doc__, name
