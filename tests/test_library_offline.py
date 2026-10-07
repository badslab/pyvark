"""Offline tests for the paper-library, upload, download and API-2.41
alignment methods of ``vark.AnthiveClient``. HTTP is mocked: every
``requests.get`` / ``requests.post`` / ``requests.request`` call is
recorded and answered with a real ``requests.Response`` built in memory.

Run with::

    uv run --with pytest --with requests --no-project \
        python -m pytest tests/test_library_offline.py -v
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vark  # noqa: E402
from vark import (  # noqa: E402
    AnthiveClient,
    PaperDuplicateError,
    PaperInvalidError,
    PaperNotPDFError,
    PaperTooLargeError,
    PaperUploadDisabledError,
    PaperUploadError,
    PaperUploadForbiddenError,
)

BASE = 'http://anthive.test/api'
PDF_BYTES = b'%PDF-1.4\n%fake pdf for tests\n%%EOF\n'


def make_response(status: int = 200, body: Any = None, *,
                  content: Optional[bytes] = None,
                  headers: Optional[Dict[str, str]] = None,
                  url: str = BASE) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.reason = {200: 'OK', 201: 'Created', 403: 'Forbidden',
                       404: 'Not Found', 409: 'Conflict', 413: 'Too Large',
                       415: 'Unsupported', 422: 'Unprocessable',
                       503: 'Service Unavailable'}.get(status, '')
    if content is None:
        content = json.dumps(body if body is not None else {}).encode()
        response.headers['Content-Type'] = 'application/json'
    response._content = content
    response._content_consumed = True
    response.raw = io.BytesIO(content)
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


class FakeHTTP:
    """Records calls; answers from a queue (or a single fixed response)."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.responses: List[requests.Response] = []

    def queue(self, *responses: requests.Response) -> None:
        self.responses.extend(responses)

    def _answer(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        files = kwargs.get('files')
        recorded_files = None
        if files:
            recorded_files = {}
            for key, value in files.items():
                name, payload = value[0], value[1]
                if hasattr(payload, 'read'):
                    payload = payload.read()
                recorded_files[key] = (name, payload)
        self.calls.append({'method': method, 'url': url,
                           'params': kwargs.get('params'),
                           'json': kwargs.get('json'),
                           'data': kwargs.get('data'),
                           'files': recorded_files,
                           'auth': kwargs.get('auth'),
                           'timeout': kwargs.get('timeout'),
                           'stream': kwargs.get('stream')})
        if not self.responses:
            return make_response(200, {})
        return self.responses.pop(0)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        return self._answer(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._answer('GET', url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self._answer('POST', url, **kwargs)

    @property
    def last(self) -> Dict[str, Any]:
        return self.calls[-1]


@pytest.fixture
def http(monkeypatch) -> FakeHTTP:
    fake = FakeHTTP()
    monkeypatch.setattr(requests, 'request', fake.request)
    monkeypatch.setattr(requests, 'get', fake.get)
    monkeypatch.setattr(requests, 'post', fake.post)
    return fake


@pytest.fixture
def client(monkeypatch) -> AnthiveClient:
    monkeypatch.delenv('ANTHIVE_USER', raising=False)
    monkeypatch.delenv('ANTHIVE_PASSWORD', raising=False)
    return AnthiveClient(BASE, auth=('tester', 'not-a-real-password'),
                         vark_config=False)


# ── versions ────────────────────────────────────────────────────────────


def test_api_target_is_2_41():
    major, minor, _ = (int(part) for part in AnthiveClient.API_TARGET.split('.'))
    assert (major, minor) >= (2, 41)


def test_version_matches_pyproject():
    pyproject = (Path(__file__).resolve().parent.parent / 'pyproject.toml').read_text()
    assert f'version = "{vark.__version__}"' in pyproject


# ── library reads ───────────────────────────────────────────────────────


def test_list_papers_forwards_filters_and_unwraps(http, client):
    http.queue(make_response(200, {'n': 2, 'papers': [
        {'citekey': 'lee2026plasticity'}, {'citekey': 'mathys2023singlecell'}]}))
    papers = client.list_papers(role='source', disease='Alzheimer disease',
                                year=2024, q='microglia')
    assert [paper['citekey'] for paper in papers] == [
        'lee2026plasticity', 'mathys2023singlecell']
    call = http.last
    assert call['url'] == f'{BASE}/papers'
    assert call['params'] == {'role': 'source', 'disease': 'Alzheimer disease',
                              'year': '2024', 'q': 'microglia'}
    assert call['auth'] == ('tester', 'not-a-real-password')


def test_list_papers_without_filters_sends_no_params(http, client):
    http.queue(make_response(200, {'n': 0, 'papers': []}))
    assert client.list_papers() == []
    assert http.last['params'] is None


def test_list_papers_year_range(http, client):
    http.queue(make_response(200, {'n': 0, 'papers': []}))
    client.list_papers(year='2020..2024')
    assert http.last['params'] == {'year': '2020..2024'}


def test_get_paper(http, client):
    http.queue(make_response(200, {'citekey': 'lee2026plasticity', 'title': 'T'}))
    paper = client.get_paper('lee2026plasticity')
    assert paper['title'] == 'T'
    assert http.last['url'] == f'{BASE}/papers/lee2026plasticity'


def test_get_paper_404_raises_http_error(http, client):
    http.queue(make_response(404, {'detail': 'paper not found: nope'}))
    with pytest.raises(requests.HTTPError):
        client.get_paper('nope')


def test_get_related_papers_kind_list(http, client):
    http.queue(make_response(200, {'citekey': 'a', 'related': [{'citekey': 'b'}]}))
    related = client.get_related_papers('a', kind=['cohort', 'author'], limit=5)
    assert related == [{'citekey': 'b'}]
    assert http.last['url'] == f'{BASE}/papers/a/related'
    assert http.last['params'] == {'limit': 5, 'kind': 'cohort,author'}


def test_get_paper_page(http, client):
    http.queue(make_response(200, {'citekey': 'a', 'page': 3, 'n_pages': 9,
                                   'text': 'hello'}))
    page = client.get_paper_page('a', 3)
    assert page['text'] == 'hello'
    assert http.last['url'] == f'{BASE}/papers/a/pages/3'


def test_get_paper_bibtex(http, client):
    http.queue(make_response(200, content=b'@article{a,\n}\n',
                             headers={'Content-Type': 'application/x-bibtex'}))
    text = client.get_paper_bibtex('a', classic=True)
    assert text.startswith('@article{a')
    assert http.last['url'] == f'{BASE}/papers/a.bib'
    assert http.last['params'] == {'classic': 'true'}


def test_get_library_bibtex_selection(http, client):
    http.queue(make_response(200, content=b'@article{a,}\n@article{b,}\n'))
    text = client.get_library_bibtex(citekeys=['a', 'b'])
    assert text.count('@article') == 2
    assert http.last['url'] == f'{BASE}/library.bib'
    assert http.last['params'] == {'citekeys': 'a,b'}


def test_get_library_bibtex_all(http, client):
    http.queue(make_response(200, content=b''))
    client.get_library_bibtex()
    assert http.last['params'] is None


def test_search_literature_params(http, client):
    http.queue(make_response(200, {'query': 'TREM2', 'mode': 'keyword',
                                   'results': [], 'warnings': []}))
    result = client.search_literature('TREM2', k=5, mode='keyword',
                                      section=['methods', 'results'],
                                      citekey='a,b', year='2020..2024')
    assert result['mode'] == 'keyword'
    assert http.last['url'] == f'{BASE}/search/literature'
    assert http.last['params'] == {'q': 'TREM2', 'k': 5, 'mode': 'keyword',
                                   'section': 'methods,results',
                                   'citekey': 'a,b', 'year': '2020..2024'}


def test_search_literature_rejects_bad_mode(client):
    with pytest.raises(ValueError):
        client.search_literature('TREM2', mode='fuzzy')


def test_get_database_papers(http, client):
    http.queue(make_response(200, {'db_id': 'L26/FMG', 'papers': [
        {'citekey': 'lee2026plasticity', 'role': 'source'}]}))
    papers = client.get_database_papers('L26/FMG')
    assert papers[0]['role'] == 'source'
    assert http.last['url'] == f'{BASE}/databases/L26/FMG/papers'


def test_get_database_context(http, client):
    http.queue(make_response(200, {'db_id': 'L26/FMG'}))
    client.get_database_context('L26/FMG', level='full', budget_tokens=8000)
    assert http.last['url'] == f'{BASE}/databases/L26/FMG/context'
    assert http.last['params'] == {'level': 'full', 'budget_tokens': 8000}


def test_get_library_status(http, client):
    http.queue(make_response(200, {'papers': 3, 'upload_index': None}))
    assert client.get_library_status()['papers'] == 3
    assert http.last['url'] == f'{BASE}/library/status'


# ── downloads ───────────────────────────────────────────────────────────


def test_download_paper_pdf_bytes(http, client):
    http.queue(make_response(200, content=PDF_BYTES,
                             headers={'Content-Type': 'application/pdf'}))
    data = client.download_paper_pdf('a')
    assert data == PDF_BYTES
    assert http.last['url'] == f'{BASE}/papers/a/file'
    assert http.last['method'] == 'GET'


def test_download_paper_pdf_to_directory_uses_server_name(http, client, tmp_path):
    http.queue(make_response(
        200, content=PDF_BYTES,
        headers={'Content-Disposition': 'inline; filename="lee2026plasticity.pdf"'}))
    target = client.download_paper_pdf('lee2026plasticity', dest=tmp_path)
    assert target == tmp_path / 'lee2026plasticity.pdf'
    assert target.read_bytes() == PDF_BYTES
    assert http.last['stream'] is True


def test_download_paper_pdf_to_directory_fallback_name(http, client, tmp_path):
    http.queue(make_response(200, content=PDF_BYTES))
    target = client.download_paper_pdf('abc2020x', dest=tmp_path)
    assert target.name == 'abc2020x.pdf'


def test_download_paper_pdf_strips_path_from_disposition(http, client, tmp_path):
    http.queue(make_response(
        200, content=PDF_BYTES,
        headers={'Content-Disposition': 'inline; filename="../../evil.pdf"'}))
    target = client.download_paper_pdf('a', dest=tmp_path)
    assert target == tmp_path / 'evil.pdf'


def test_download_paper_pdf_to_file(http, client, tmp_path):
    http.queue(make_response(200, content=PDF_BYTES))
    target = client.download_paper_pdf('a', dest=tmp_path / 'x.pdf')
    assert target.read_bytes() == PDF_BYTES


def test_download_paper_pdf_404(http, client):
    http.queue(make_response(404, {'detail': 'no PDF for a'}))
    with pytest.raises(requests.HTTPError):
        client.download_paper_pdf('a')


def test_list_database_files_and_downloads(http, client, tmp_path):
    http.queue(make_response(200, {'db_id': 'G/F', 'files': [
        {'kind': 'h5ad', 'filename': 'F.h5ad'},
        {'kind': 'static', 'filename': 'table.tsv'}]}))
    files = client.list_database_files('G/F')
    assert [row['kind'] for row in files] == ['h5ad', 'static']
    http.queue(make_response(200, content=b'h5'),
               make_response(200, content=b'a\tb\n'))
    assert client.download_database_file('G/F') == b'h5'
    assert http.calls[-1]['url'] == f'{BASE}/databases/G/F/download/h5ad'
    target = client.download_static_file('G/F', 'table.tsv', dest=tmp_path)
    assert target.read_bytes() == b'a\tb\n'
    assert http.calls[-1]['url'] == f'{BASE}/databases/G/F/download-static/table.tsv'


# ── upload requirements ─────────────────────────────────────────────────


def test_upload_requirements_ok(http, client):
    body = {'uploads_enabled': True, 'default_role': 'background',
            'roles': {'background': 'of interest to the lab'},
            'entrytypes': {'article': 'journal article'}}
    http.queue(make_response(200, body))
    assert client.get_paper_upload_requirements() == body
    assert http.last['url'] == f'{BASE}/papers/upload/requirements'


def test_upload_requirements_forbidden(http, client):
    http.queue(make_response(403, {
        'status': 'forbidden',
        'message': 'Only users in admins can add papers to the library.'}))
    with pytest.raises(PaperUploadForbiddenError) as info:
        client.get_paper_upload_requirements()
    assert info.value.status_code == 403
    assert 'Only users in admins' in str(info.value)
    # Backward compatible: still a requests.HTTPError.
    assert isinstance(info.value, requests.HTTPError)


# ── upload ──────────────────────────────────────────────────────────────

RECORD = {
    'entrytype': 'article',
    'title': 'A test paper',
    'author': ['Doe, Jane'],
    'year': 2024,
    'doi': '10.1234/test.2024',
}


def test_upload_paper_dict_with_pdf_bytes(http, client):
    http.queue(make_response(201, {'status': 'created', 'citekey': 'doe2024test'}))
    result = client.upload_paper(RECORD, PDF_BYTES, folder='reading',
                                 role='method', papers_for={'G/F': 'related'},
                                 dry_run=False, enrich=False)
    assert result['citekey'] == 'doe2024test'
    call = http.last
    assert call['method'] == 'POST'
    assert call['url'] == f'{BASE}/papers/upload'
    metadata = json.loads(call['data']['metadata'])
    assert metadata['anthive_role'] == 'method'
    assert metadata['papers_for'] == {'G/F': 'related'}
    assert metadata['title'] == 'A test paper'
    assert call['data']['folder'] == 'reading'
    assert call['data']['enrich'] == 'false'
    assert call['data']['dry_run'] == 'false'
    assert call['data']['update'] == 'false'
    assert call['files']['file'] == ('paper.pdf', PDF_BYTES)


def test_upload_paper_does_not_mutate_caller_dict(http, client):
    record = dict(RECORD)
    http.queue(make_response(201, {'status': 'created'}))
    client.upload_paper(record, role='source')
    assert 'anthive_role' not in record


def test_upload_paper_without_pdf_is_multipart(http, client):
    http.queue(make_response(200, {'status': 'dry_run', 'citekey': 'doe2024test'}))
    client.upload_paper(RECORD, dry_run=True)
    call = http.last
    # Metadata goes as a multipart part so the request is form-data.
    assert call['files']['metadata'][0] is None
    assert json.loads(call['files']['metadata'][1])['doi'] == RECORD['doi']
    assert call['data']['dry_run'] == 'true'
    assert 'folder' not in call['data']


def test_upload_paper_pdf_path_and_md_path(http, client, tmp_path):
    record = tmp_path / 'doe2024test.md'
    record.write_text('---\nentrytype: article\ntitle: T\n---\nnotes\n')
    pdf = tmp_path / 'doe2024test.pdf'
    pdf.write_bytes(PDF_BYTES)
    http.queue(make_response(201, {'status': 'created'}))
    client.upload_paper(record, pdf)
    call = http.last
    assert call['data']['metadata'].startswith('---\nentrytype: article')
    assert call['files']['file'] == ('doe2024test.pdf', PDF_BYTES)


def test_upload_paper_papers_for_list_passed_through(http, client):
    http.queue(make_response(201, {'status': 'created'}))
    client.upload_paper(json.dumps(RECORD), papers_for=['G/F', 'G2:reanalysis'])
    metadata = json.loads(http.last['files']['metadata'][1])
    assert metadata['papers_for'] == ['G/F', 'G2:reanalysis']


def test_upload_paper_role_with_md_text_is_refused(client):
    with pytest.raises(ValueError):
        client.upload_paper('---\ntitle: T\n---\n', role='source')


def test_upload_paper_rejects_bad_metadata_type(client):
    with pytest.raises(TypeError):
        client.upload_paper(42)  # type: ignore[arg-type]


@pytest.mark.parametrize('status, body, error_class', [
    (403, {'status': 'forbidden', 'message': 'Only users in admins can add papers to the library.'},
     PaperUploadForbiddenError),
    (503, {'status': 'disabled', 'message': 'Paper uploads are switched off on this site (services.paper_upload).'},
     PaperUploadDisabledError),
    (409, {'status': 'duplicate', 'existing_citekey': 'doe2024test', 'matched_on': 'doi'},
     PaperDuplicateError),
    (422, {'status': 'invalid', 'errors': [{'field': 'title', 'message': 'required'}],
           'missing_required': ['title']}, PaperInvalidError),
    (413, {'status': 'too_large', 'message': 'PDF over 25 MB'}, PaperTooLargeError),
    (415, {'status': 'not_pdf', 'message': 'not a PDF'}, PaperNotPDFError),
])
def test_upload_paper_error_mapping(http, client, status, body, error_class):
    http.queue(make_response(status, body))
    with pytest.raises(error_class) as info:
        client.upload_paper(RECORD, PDF_BYTES)
    error = info.value
    assert isinstance(error, PaperUploadError)
    assert isinstance(error, requests.HTTPError)
    assert error.status_code == status
    assert error.body == body
    if error_class is PaperDuplicateError:
        assert error.existing_citekey == 'doe2024test'
        assert error.matched_on == 'doi'
    if error_class is PaperInvalidError:
        assert error.missing_required == ['title']
        assert error.errors[0]['field'] == 'title'


def test_upload_paper_other_503_is_not_disabled(http, client):
    http.queue(make_response(503, {'detail': 'paper library is still loading'}))
    with pytest.raises(requests.HTTPError) as info:
        client.upload_paper(RECORD)
    assert not isinstance(info.value, PaperUploadDisabledError)
    assert info.value.status_code == 503


# ── bulk upload ─────────────────────────────────────────────────────────


def test_upload_papers_records_outcomes(http, client):
    http.queue(
        make_response(201, {'status': 'created', 'citekey': 'a2024x'}),
        make_response(409, {'status': 'duplicate', 'existing_citekey': 'b2024y',
                            'matched_on': 'doi'}),
        make_response(422, {'status': 'invalid', 'errors': [], 'missing_required': ['title']}),
    )
    outcomes = client.upload_papers(
        [{'metadata': RECORD, 'pdf': PDF_BYTES}, (RECORD, None), {'metadata': {}}],
        dry_run=True,
    )
    assert [outcome['ok'] for outcome in outcomes] == [True, False, False]
    assert outcomes[0]['citekey'] == 'a2024x'
    assert outcomes[1]['status'] == 'duplicate'
    assert outcomes[1]['http_status'] == 409
    assert outcomes[2]['status'] == 'invalid'
    # defaults apply to every item
    assert all(call['data']['dry_run'] == 'true' for call in http.calls)


def test_upload_papers_item_overrides_default(http, client):
    http.queue(make_response(201, {'status': 'created'}))
    client.upload_papers([{'metadata': RECORD, 'folder': 'lab'}], folder='reading')
    assert http.last['data']['folder'] == 'lab'


def test_upload_papers_stop_on_error(http, client):
    http.queue(make_response(409, {'status': 'duplicate'}))
    with pytest.raises(PaperDuplicateError):
        client.upload_papers([(RECORD, None), (RECORD, None)], stop_on_error=True)
    assert len(http.calls) == 1


@pytest.mark.parametrize('status, body, error_class', [
    (403, {'status': 'forbidden', 'message': 'no'}, PaperUploadForbiddenError),
    (503, {'status': 'disabled', 'message': 'off'}, PaperUploadDisabledError),
])
def test_upload_papers_aborts_on_forbidden_or_disabled(http, client, status, body,
                                                       error_class):
    http.queue(make_response(status, body))
    with pytest.raises(error_class):
        client.upload_papers([(RECORD, None), (RECORD, None)])
    assert len(http.calls) == 1


def test_paper_items_from_folder(tmp_path):
    (tmp_path / 'a2024x.md').write_text('---\ntitle: A\n---\n')
    (tmp_path / 'a2024x.pdf').write_bytes(PDF_BYTES)
    (tmp_path / 'b2024y.md').write_text('---\ntitle: B\n---\n')
    (tmp_path / 'README.md').write_text('# readme\n')
    items = AnthiveClient.paper_items_from_folder(tmp_path)
    assert [item['metadata'].name for item in items] == ['a2024x.md', 'b2024y.md']
    assert items[0]['pdf'] == tmp_path / 'a2024x.pdf'
    assert items[1]['pdf'] is None


# ── API alignment fixes ─────────────────────────────────────────────────


def test_gene_stats_default_lets_server_pick_layer(http, client):
    http.queue(make_response(200, {'stats': []}))
    client.get_gene_stats('G/F', ['APOE', 'CLU'])
    assert http.last['params'] == {'genes': 'APOE,CLU'}


def test_gene_stats_explicit_layer_and_top(http, client):
    http.queue(make_response(200, {'stats': []}))
    client.get_gene_stats('G/F', layer='X')
    assert http.last['params'] == {'layer': 'X'}
    http.queue(make_response(200, {'stats': []}))
    client.get_gene_stats('G/F', top=20)
    assert http.last['params'] == {'top': 20}


def test_gene_stats_all_filters(http, client):
    http.queue(make_response(200, {'results': []}))
    client.get_gene_stats_all('APOE', organism=['human', 'mouse'],
                              tissue='brain', include_remote=True)
    assert http.last['params'] == {'genes': 'APOE', 'case_sensitive': False,
                                   'organism': 'human,mouse', 'tissue': 'brain',
                                   'include_remote': True}


def test_module_score_payload_and_dataframe(http, client):
    pytest.importorskip('pandas')
    response_body = {'session_id': 'f' * 32, 'summary': {'mean': 0.1, 'max': 1.0}}
    http.queue(make_response(200, response_body))
    result = client.module_score('G/F', ['APOE'], name='ignored',
                                 n_control=50, seed=1, subset=['sex:female'])
    assert result['session_id'] == 'f' * 32
    assert http.last['json'] == {'genes': ['APOE'], 'layer': 'X',
                                 'n_control': 50, 'seed': 1,
                                 'subset': ['sex:female']}
    http.queue(make_response(200, response_body))
    frame = client.module_score('G/F', ['APOE'], format='dataframe')
    assert list(frame.columns) == ['mean', 'max']
    assert len(frame) == 1


def test_analytics_query_attach_sessions(http, client):
    http.queue(make_response(200, {'session_id': 'a' * 32, 'preview': []}))
    client.analytics_query('G/F', 'SELECT * FROM scores', limit=10,
                           attach_sessions='b' * 32, timeout=30)
    assert http.last['json'] == {'sql': 'SELECT * FROM scores',
                                 'timeout': 30, 'attach_sessions': ['b' * 32]}


def test_get_plot_attach_sessions(http, client):
    http.queue(make_response(200, content=b'png',
                             headers={'Content-Type': 'image/png'}))
    client.get_plot('G/F', 'scatter', x='module_score', y='SPP1',
                    attach_sessions='c' * 32)
    assert http.last['params']['attach_sessions'] == ['c' * 32]


def test_list_genesets_filters(http, client):
    http.queue(make_response(200, {'count': 0, 'genesets': []}))
    client.list_genesets(organism='human')
    assert http.last['url'] == f'{BASE}/genesets'
    assert http.last['params'] == {'organism': 'human'}


def test_list_genesets_no_filters_sends_no_params(http, client):
    http.queue(make_response(200, {'count': 0, 'genesets': []}))
    client.list_genesets()
    assert http.last['params'] is None


def test_module_variability_param_names(http, client):
    http.queue(make_response(200, {'rows': []}))
    client.get_module_variability('G/F', statistic='eta2', min_value=0.1)
    assert http.last['url'] == f'{BASE}/module-variability'
    assert http.last['params'] == {'sort': 'value:desc', 'limit': 500,
                                   'dataset': 'G/F', 'statistic': 'eta2',
                                   'min': 0.1}


def test_admin_release_params(http, client):
    http.queue(make_response(200, {'released': True}))
    client.admin_release('G/F', duration_seconds=60)
    assert http.last['method'] == 'POST'
    assert http.last['url'] == f'{BASE}/admin/release/G/F'
    assert http.last['params'] == {'duration_seconds': 60}


# ── credentials from the environment ────────────────────────────────────


def test_env_credentials_used_when_no_auth(monkeypatch):
    monkeypatch.setenv('ANTHIVE_USER', 'envuser')
    monkeypatch.setenv('ANTHIVE_PASSWORD', 'envsecret')
    client = AnthiveClient(BASE)
    assert client.auth == ('envuser', 'envsecret')


def test_explicit_auth_beats_env(monkeypatch):
    monkeypatch.setenv('ANTHIVE_USER', 'envuser')
    monkeypatch.setenv('ANTHIVE_PASSWORD', 'envsecret')
    client = AnthiveClient(BASE, auth=('explicit', 'pw'))
    assert client.auth == ('explicit', 'pw')


def test_env_user_without_password_is_ignored(monkeypatch):
    monkeypatch.setenv('ANTHIVE_USER', 'envuser')
    monkeypatch.delenv('ANTHIVE_PASSWORD', raising=False)
    client = AnthiveClient(BASE, vark_config=False)
    assert client.auth is None


def test_get_library_status_non_admin_shape(http, client):
    body = {'papers': 3, 'linked_datasets': 2, 'index': {'model': 'm'},
            'issues': {'errors': [], 'warnings': []},
            'n_errors': 1, 'n_warnings': 4}
    http.queue(make_response(200, body))
    status = client.get_library_status()
    assert 'unresolved_references' not in status
    assert 'library_dir' not in status
    assert (status['n_errors'], status['n_warnings']) == (1, 4)


def test_get_library_status_docstring_names_admin_fields():
    doc = AnthiveClient.get_library_status.__doc__
    for name in ('n_errors', 'n_warnings', 'unresolved_references',
                 'library_dir', 'index.path'):
        assert name in doc
