"""Offline tests for the read-only dataset deposit methods of pyvark
0.11.0 (anthive REST API 2.46.0) and the 2.46 ``/health`` change.
Uploading is ``vark datasets upload`` and stays out of pyvark.

Run with::

    uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_deposits_offline.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vark  # noqa: E402
from vark import AnthiveClient, DatasetDepositError  # noqa: E402
from test_library_offline import (  # noqa: E402,F401  (fixtures)
    BASE,
    client,
    http,
    make_response,
)


DEPOSIT_METHODS = ('list_deposits', 'get_deposit', 'get_deposit_report',
                   'get_deposit_vocab', 'get_deposit_group')


def test_version_and_target():
    assert vark.__version__ == '0.12.1'
    assert AnthiveClient.API_TARGET == '2.47.0'


def test_no_upload_methods_and_docs_point_to_vark():
    names = set(dir(AnthiveClient))
    assert not {name for name in names
                if 'deposit' in name and name.startswith(
                    ('create', 'upload', 'complete', 'withdraw', 'approve',
                     'reject'))}
    assert 'vark datasets upload' in AnthiveClient.__doc__
    assert 'vark datasets upload' in AnthiveClient.list_deposits.__doc__
    for name in DEPOSIT_METHODS:
        assert '2.46.0' in getattr(AnthiveClient, name).__doc__


def test_list_deposits(http, client):
    http.queue(make_response(200, {'deposits': [{'deposit_id': 'd1'}],
                                   'all': False}))
    result = client.list_deposits()
    assert http.last['url'] == f'{BASE}/datasets/deposit'
    assert not http.last['params']
    assert result['deposits'][0]['deposit_id'] == 'd1'
    client.list_deposits(all=True)
    assert http.last['params'] == {'all': 'true'}


def test_get_deposit_and_report(http, client):
    client.get_deposit('d1')
    assert http.last['url'] == f'{BASE}/datasets/deposit/d1'
    client.get_deposit_report('d1')
    assert http.last['url'] == f'{BASE}/datasets/deposit/d1/report'


def test_vocab_and_group(http, client):
    client.get_deposit_vocab()
    assert http.last['url'] == f'{BASE}/datasets/deposit/vocab'
    client.get_deposit_group('Sierksma2025')
    assert http.last['url'] == f'{BASE}/datasets/deposit/groups/Sierksma2025'
    assert not http.last['params']
    client.get_deposit_group('Sierksma2025', basename='S25_MIC')
    assert http.last['params'] == {'basename': 'S25_MIC'}


@pytest.mark.parametrize('status_code,word', [
    (403, 'forbidden'), (404, 'no_report'), (429, 'rate_limited'),
    (503, 'disabled')])
def test_errors_raise_deposit_error(http, client, status_code, word):
    http.queue(make_response(status_code, {'status': word,
                                           'message': 'nope'}))
    with pytest.raises(DatasetDepositError) as excinfo:
        client.get_deposit_report('d1')
    error = excinfo.value
    assert error.status == word and error.status_code == status_code
    assert isinstance(error, requests.HTTPError)
    assert 'nope' in str(error)


def test_health_empty_catalog_documented(http, client):
    assert 'empty catalog' in AnthiveClient.get_health.__doc__
    http.queue(make_response(200, {'status': 'healthy', 'databases': 0,
                                   'note': 'empty catalog'}))
    assert client.get_health()['note'] == 'empty catalog'


def test_score_sidecar_docstrings():
    module_scores = AnthiveClient.list_module_scores.__doc__
    for field in ('storage', 'query_table', 'query_sql', 'count_by_storage',
                  'sidecar_error', 'scores_sidecar'):
        assert field in module_scores
    schema = AnthiveClient.analytics_schema.__doc__
    assert 'score_sidecar' in schema and 'example_sql' in schema
    assert 'FILTER' in schema
