"""Offline tests for the 503 ``warming_up`` retry added in pyvark 0.10.1
(anthive REST API 2.46.1+: facet routes answer 503 ``{status:
"warming_up", retry_after: N}`` with a ``Retry-After`` header right
after a server restart). HTTP and ``time.sleep`` are mocked.

Run with::

    uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_warmup_offline.py -v
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vark  # noqa: E402
import vark.client as client_module  # noqa: E402
from vark import (AnthiveClient, AnthiveWarmingUpError,  # noqa: E402
                  ServerWarmingUpWarning)
from test_library_offline import (  # noqa: E402,F401  (fixtures)
    BASE,
    client,
    http,
    make_response,
)


def warming(retry_after=7, header='7'):
    body = {'status': 'warming_up'}
    if retry_after is not None:
        body['retry_after'] = retry_after
    headers = {'Retry-After': header} if header is not None else {}
    return make_response(503, body, headers=headers)


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(client_module.time, 'sleep', recorded.append)
    return recorded


def test_version():
    assert tuple(int(part) for part in vark.__version__.split('.')) >= (0, 10, 1)


def test_default_max_wait():
    assert AnthiveClient('http://x', vark_config=False).warmup_max_wait == 180


def test_retries_until_ready_and_respects_retry_after(http, client, sleeps,
                                                      caplog):
    http.queue(warming(7), warming(3), make_response(200, {'rows': [1]}))
    with caplog.at_level(logging.WARNING, logger='vark'):
        with pytest.warns(ServerWarmingUpWarning):
            result = client.get_facet_top_genes('sex')
    assert result == {'rows': [1]}
    assert sleeps == [7.0, 3.0]
    assert len(http.calls) == 3
    assert all(call['url'] == f'{BASE}/facets/sex/effects/top'
               for call in http.calls)
    assert sum('warming up' in record.message for record in caplog.records) == 2


def test_header_used_when_body_has_no_retry_after(http, client, sleeps):
    http.queue(warming(retry_after=None, header='4'), make_response(200, {}))
    with pytest.warns(ServerWarmingUpWarning):
        client.get_facet_effects_overview('sex')
    assert sleeps == [4.0]


def test_gives_up_after_max_wait(http, client, sleeps):
    client.warmup_max_wait = 10
    http.queue(warming(4), warming(4), warming(4), warming(4))
    with pytest.warns(ServerWarmingUpWarning):
        with pytest.raises(AnthiveWarmingUpError) as excinfo:
            client.get_facet_top_genes('sex')
    assert sleeps == [4.0, 4.0, 2.0]     # last pause capped at the budget
    error = excinfo.value
    assert error.waited == 10 and error.retry_after == 4.0
    assert error.status_code == 503
    assert isinstance(error, requests.HTTPError)
    assert 'warming up' in str(error)


def test_zero_max_wait_raises_at_once(http, client, sleeps):
    client.warmup_max_wait = 0
    http.queue(warming(7))
    with pytest.raises(AnthiveWarmingUpError):
        client.get_facet_top_genes('sex')
    assert sleeps == [] and len(http.calls) == 1


def test_raw_get_and_post_also_wait(http, client, sleeps):
    http.queue(warming(2), make_response(200, content=b'PNG', headers={
        'Content-Type': 'image/png'}))
    with pytest.warns(ServerWarmingUpWarning):
        plot = client.get_facet_donor_plot('sex', 'microglia', gene='XIST')
    assert plot['bytes'] == b'PNG'
    http.queue(warming(2), make_response(200, {'ok': True}))
    with pytest.warns(ServerWarmingUpWarning):
        assert client._post('/x') == {'ok': True}
    assert sleeps == [2.0, 2.0]


@pytest.mark.parametrize('body', [{'status': 'disabled'}, {'detail': 'busy'}])
def test_other_503_unchanged(http, client, sleeps, body):
    http.queue(make_response(503, body))
    with pytest.raises(requests.HTTPError) as excinfo:
        client.get_facet_top_genes('sex')
    assert not isinstance(excinfo.value, AnthiveWarmingUpError)
    assert sleeps == [] and len(http.calls) == 1


def test_non_json_503_unchanged(http, client, sleeps):
    http.queue(make_response(503, content=b'Bad gateway'))
    with pytest.raises(requests.HTTPError):
        client.get_facet_top_genes('sex')
    assert sleeps == []
