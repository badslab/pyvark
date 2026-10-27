"""Offline tests for the artefact store methods of pyvark 0.12.0 (anthive
REST API 2.47.0): listing, detail, versions, version payloads, previews,
downloads that follow the signed 307 redirect with sha256 verification,
analysis collections, the typed errors, and ``wait_for_deposit``.

HTTP is mocked (``requests.get`` / ``requests.post`` /
``requests.request``); no server is needed. Run with::

    uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_artefacts_offline.py -v
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vark  # noqa: E402
from vark import (  # noqa: E402
    AnthiveClient,
    ArtefactDownloadError,
    ArtefactError,
    ArtefactFileNotFoundError,
    ArtefactIntegrityError,
    ArtefactNotFoundError,
    ArtefactNotOnThisSiteError,
    ArtefactDeletedError,
    ArtefactDeletingError,
    ArtefactPurgedError,
    ArtefactPurgedWarning,
    ArtefactPurgingError,
    ArtefactRateLimitedError,
    ArtefactStorageUnavailableError,
    DatasetDepositError,
    ServerTooOldError,
    DepositHeldError,
    DepositNotOwnerError,
    DepositQuotaError,
    DepositStoppedError,
)
from test_library_offline import BASE, FakeHTTP, make_response  # noqa: E402

REF = 'AT6/_group/atlas-umap'
FIGURE = b'\x89PNG artefact bytes'
PANEL = b'panel b'
SIGNED = ('https://s3.example.org/labbucket/Atlas2026/static/artefacts/'
          '_group/figure/atlas-umap/v2/files/a.png?X-Amz-Signature=secret')


class RecordingHTTP(FakeHTTP):
    """FakeHTTP that also keeps every keyword argument of each call."""

    def _answer(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        response = super()._answer(method, url, **kwargs)
        self.calls[-1]['kwargs'] = kwargs
        return response


@pytest.fixture
def http(monkeypatch) -> RecordingHTTP:
    fake = RecordingHTTP()
    monkeypatch.setattr(requests, 'request', fake.request)
    monkeypatch.setattr(requests, 'get', fake.get)
    monkeypatch.setattr(requests, 'post', fake.post)
    return fake


@pytest.fixture
def client(monkeypatch) -> AnthiveClient:
    monkeypatch.delenv('ANTHIVE_USER', raising=False)
    monkeypatch.delenv('ANTHIVE_PASSWORD', raising=False)
    anthive = AnthiveClient(BASE, auth=('tester', 'not-a-real-password'),
                            vark_config=False)
    anthive.headers['X-Custom'] = 'api-only'
    return anthive


def file_entry(name: str, body: bytes, role: str = 'main') -> Dict[str, Any]:
    return {'name': name, 'size': len(body),
            'sha256': hashlib.sha256(body).hexdigest(),
            'content_type': 'image/png', 'role': role,
            'download': f'/artefacts/{REF}/v2/files/{name}', 'preview': None}


def version_payload(files: List[Dict[str, Any]], version: int = 2) -> Dict[str, Any]:
    return {'ref': f'{REF}@v{version}', 'version': version, 'state': 'live',
            'latest': 2,
            'manifest': {'schema': 'anthive.artefact/1',
                         'ref': f'{REF}@v{version}',
                         'made_from': [{'db_id': None, 'dataset_version': None,
                                        'h5ad_sha256': None,
                                        'hidden': 'made from a dataset you '
                                                  'cannot see'}],
                         'files': files},
            'files': files}


def redirect(location: str = SIGNED) -> requests.Response:
    return make_response(307, content=b'', headers={
        'Location': location, 'Cache-Control': 'no-store, private'})


# ── version and exports ─────────────────────────────────────────────────


def test_version_and_target():
    assert vark.__version__ == '0.12.2'
    assert AnthiveClient.API_TARGET == '2.48.0'


def test_methods_documented_with_api_version():
    for name in ('list_artefacts', 'get_artefact', 'get_artefact_versions',
                 'get_artefact_version', 'get_artefact_preview',
                 'download_artefact_file', 'download_artefact',
                 'list_analysis_collections', 'list_collections',
                 'list_artefact_purges'):
        assert '2.47.0' in getattr(AnthiveClient, name).__doc__, name


def test_no_artefact_write_methods():
    names = {name for name in dir(AnthiveClient) if 'artefact' in name}
    assert not {name for name in names if name.startswith(
        ('add', 'create', 'upload', 'deposit', 'purge', 'delete'))}
    assert 'vark artefacts add' in AnthiveClient.__doc__


def test_error_hierarchy():
    for error_class in (ArtefactNotFoundError, ArtefactFileNotFoundError,
                        ArtefactNotOnThisSiteError,
                        ArtefactPurgedError, ArtefactPurgingError,
                        ArtefactIntegrityError, ArtefactRateLimitedError,
                        ArtefactStorageUnavailableError,
                        ArtefactDownloadError):
        assert issubclass(error_class, ArtefactError)
        assert issubclass(error_class, requests.HTTPError)
    for error_class in (DepositNotOwnerError, DepositQuotaError,
                        DepositHeldError, DepositStoppedError):
        assert issubclass(error_class, DatasetDepositError)


# ── references ──────────────────────────────────────────────────────────


@pytest.mark.parametrize('ref, expected', [
    ('S26/SLM/umap-mg', ('S26', 'SLM', 'umap-mg', None)),
    ('S26/SLM/umap-mg@v12', ('S26', 'SLM', 'umap-mg', 'v12')),
    ('AT6/_group/atlas-umap@latest', ('AT6', '_group', 'atlas-umap', 'latest')),
])
def test_parse_artefact_ref(ref, expected):
    assert AnthiveClient.parse_artefact_ref(ref) == expected


@pytest.mark.parametrize('ref', [
    'S26/SLM', 'S26/SLM/Upper', 'S26/../x1', 'S2/SLM/abc', 'S26/SLM/abc@v0',
    'S26/SLM/abc@2', 'S26/_x/abc', 'S26/SLM/abc/def', '', None])
def test_parse_artefact_ref_rejects(ref):
    with pytest.raises(ValueError):
        AnthiveClient.parse_artefact_ref(ref)


# ── listing ─────────────────────────────────────────────────────────────


def test_list_artefacts_params(http, client):
    http.queue(make_response(200, {'artefacts': [{'ref': REF}],
                                   'next_cursor': None}))
    result = client.list_artefacts(db_id='S26/SLM', kind='figure', q='umap',
                                   include_purged=True, limit=10, all=True)
    assert http.last['url'] == f'{BASE}/artefacts'
    assert http.last['params'] == {'limit': 10, 'db_id': 'S26/SLM',
                                   'kind': 'figure', 'q': 'umap',
                                   'include_purged': 'true', 'all': 'true'}
    assert result['artefacts'][0]['ref'] == REF


def test_list_artefacts_defaults_send_only_limit(http, client):
    client.list_artefacts()
    assert http.last['params'] == {'limit': 50}


def test_list_artefacts_all_pages(http, client):
    http.queue(make_response(200, {'artefacts': [{'ref': 'a'}],
                                   'next_cursor': 'c1'}),
               make_response(200, {'artefacts': [{'ref': 'b'}],
                                   'next_cursor': 'c2'}),
               make_response(200, {'artefacts': [{'ref': 'c'}],
                                   'next_cursor': None}))
    result = client.list_artefacts(group_id='AT6', all_pages=True)
    assert [row['ref'] for row in result['artefacts']] == ['a', 'b', 'c']
    assert result['next_cursor'] is None
    assert [call['params'].get('cursor') for call in http.calls] == [None, 'c1', 'c2']
    assert all(call['params']['group_id'] == 'AT6' for call in http.calls)


def test_list_artefacts_all_pages_stops_on_repeated_cursor(http, client):
    http.queue(make_response(200, {'artefacts': [], 'next_cursor': 'c1'}),
               make_response(200, {'artefacts': [], 'next_cursor': 'c1'}))
    with pytest.raises(RuntimeError):
        client.list_artefacts(all_pages=True)


def test_list_artefacts_dataframe(http, client):
    http.queue(make_response(200, {'artefacts': [{'ref': 'a', 'kind': 'figure'},
                                                 {'ref': 'b', 'kind': 'table'}],
                                   'next_cursor': None}))
    frame = client.list_artefacts(format='dataframe')
    assert list(frame['ref']) == ['a', 'b']


def test_list_artefacts_invalid_kind(http, client):
    http.queue(make_response(422, {'status': 'invalid_kind',
                                   'message': 'kind must be one of ...'}))
    with pytest.raises(ArtefactError) as caught:
        client.list_artefacts(kind='movie')
    assert caught.value.status == 'invalid_kind'
    assert caught.value.status_code == 422


# ── detail, versions, version ───────────────────────────────────────────


def test_get_artefact_without_version_is_the_detail(http, client):
    http.queue(make_response(200, {'ref': REF, 'versions': [], 'files': []}))
    assert client.get_artefact(REF)['ref'] == REF
    assert http.last['url'] == f'{BASE}/artefacts/{REF}'


def test_get_artefact_with_version(http, client):
    client.get_artefact(REF + '@v3')
    assert http.last['url'] == f'{BASE}/artefacts/{REF}/v3'
    client.get_artefact(REF, version=4)
    assert http.last['url'] == f'{BASE}/artefacts/{REF}/v4'
    client.get_artefact(REF, version='latest')
    assert http.last['url'] == f'{BASE}/artefacts/{REF}/latest'


def test_version_disagreement_is_refused(client):
    with pytest.raises(ValueError):
        client.get_artefact(REF + '@v3', version=4)
    with pytest.raises(ValueError):
        client.get_artefact_version(REF, version='3')


def test_versions_and_version_paths(http, client):
    client.get_artefact_versions(REF + '@v2')
    assert http.last['url'] == f'{BASE}/artefacts/{REF}/versions'
    client.get_artefact_version(REF)
    assert http.last['url'] == f'{BASE}/artefacts/{REF}/latest'
    client.get_artefact_version(REF + '@v2')
    assert http.last['url'] == f'{BASE}/artefacts/{REF}/v2'


def test_not_found_is_typed(http, client):
    http.queue(make_response(404, {'status': 'not_found', 'message': 'no artefact',
                                   'ref': REF}))
    with pytest.raises(ArtefactNotFoundError) as caught:
        client.get_artefact(REF)
    assert caught.value.ref == REF


def test_deleted_version_has_tombstone(http, client):
    tombstone = {'version': 1, 'state': 'deleted', 'purged_by': 'an admin',
                 'purge_reason': None, 'deleted': '2026-10-21',
                 'deleted_by': 'an admin', 'delete_reason': None}
    http.queue(make_response(410, {'status': 'deleted', 'message': 'deleted',
                                   'ref': REF + '@v1', 'tombstone': tombstone}))
    with pytest.raises(ArtefactDeletedError) as caught:
        client.get_artefact_version(REF + '@v1')
    assert caught.value.tombstone == tombstone
    assert caught.value.status == 'deleted'


def test_purged_error_is_an_alias_of_deleted():
    assert ArtefactPurgedError is ArtefactDeletedError
    assert ArtefactPurgingError is ArtefactDeletingError


def test_old_server_purged_word_maps_to_deleted(http, client):
    http.queue(make_response(410, {'status': 'purged', 'message': 'purged',
                                   'tombstone': {'version': 1}}))
    with pytest.raises(ArtefactDeletedError):
        client.get_artefact_version(REF + '@v1')


@pytest.mark.parametrize('word', ['deleting', 'purging'])
def test_deleting_version(http, client, word):
    http.queue(make_response(409, {'status': word, 'message': 'busy'}))
    with pytest.raises(ArtefactDeletingError):
        client.get_artefact_version(REF, 1)


def soft_purged_payload(files):
    payload = version_payload(files, version=1)
    payload['state'] = 'purged'
    payload['purge'] = {'purged': '2026-10-21', 'purged_by': 'alice',
                        'purge_reason': 'wrong contrast'}
    return payload


def test_soft_purged_version_is_returned_not_raised(http, client):
    http.queue(make_response(200, soft_purged_payload([file_entry('a.png', FIGURE)])))
    payload = client.get_artefact_version(REF + '@v1')
    assert payload['state'] == 'purged'
    assert payload['purge']['purge_reason'] == 'wrong contrast'


def test_soft_purged_download_works_with_warning(http, client, tmp_path):
    files = [file_entry('a.png', FIGURE)]
    http.queue(make_response(200, soft_purged_payload(files)),
               make_response(200, content=FIGURE))
    with pytest.warns(ArtefactPurgedWarning, match='wrong contrast'):
        assert client.download_artefact_file(REF + '@v1', 'a.png') == FIGURE
    http.queue(make_response(200, soft_purged_payload(files)),
               make_response(200, content=FIGURE))
    with pytest.warns(ArtefactPurgedWarning):
        written = client.download_artefact(REF + '@v1', tmp_path)
    assert written['a.png'].read_bytes() == FIGURE


def test_soft_purged_warning_can_be_an_error(http, client):
    import warnings
    http.queue(make_response(200, soft_purged_payload([file_entry('a.png', FIGURE)])))
    with warnings.catch_warnings():
        warnings.simplefilter('error', ArtefactPurgedWarning)
        with pytest.raises(ArtefactPurgedWarning):
            client.download_artefact_file(REF + '@v1', 'a.png')
    assert len(http.calls) == 1


def test_live_download_does_not_warn(http, client):
    import warnings
    http.queue(make_response(200, version_payload([file_entry('a.png', FIGURE)])),
               make_response(200, content=FIGURE))
    with warnings.catch_warnings():
        warnings.simplefilter('error', ArtefactPurgedWarning)
        assert client.download_artefact_file(REF, 'a.png') == FIGURE


def test_preview(http, client):
    http.queue(make_response(200, content=b'RIFFwebp'))
    assert client.get_artefact_preview(REF, 'panels/a.png.webp', 2) == b'RIFFwebp'
    assert http.last['url'] == f'{BASE}/artefacts/{REF}/v2/preview/panels/a.png.webp'


def test_preview_refuses_unsafe_names(client):
    for name in ('../x.webp', '/etc/passwd', 'a/b/c.webp', '.hidden.webp'):
        with pytest.raises(ValueError):
            client.get_artefact_preview(REF, name)


# ── downloads ───────────────────────────────────────────────────────────


def test_download_follows_redirect_without_credentials(http, client):
    files = [file_entry('a.png', FIGURE)]
    http.queue(make_response(200, version_payload(files)), redirect(),
               make_response(200, content=FIGURE))
    assert client.download_artefact_file(REF, 'a.png') == FIGURE
    version_call, api_call, signed_call = http.calls
    assert version_call['url'] == f'{BASE}/artefacts/{REF}/latest'
    # the file is asked for the version that was read, not "latest"
    assert api_call['url'] == f'{BASE}/artefacts/{REF}/v2/files/a.png'
    assert api_call['kwargs']['allow_redirects'] is False
    assert api_call['auth'] == ('tester', 'not-a-real-password')
    assert signed_call['url'] == SIGNED
    assert signed_call['auth'] is None
    assert 'headers' not in signed_call['kwargs']


def test_download_local_copy_without_redirect(http, client):
    files = [file_entry('a.png', FIGURE)]
    http.queue(make_response(200, version_payload(files)),
               make_response(200, content=FIGURE, headers={
                   'Content-Disposition': 'attachment; filename="a.png"'}))
    assert client.download_artefact_file(REF + '@v2', 'a.png') == FIGURE
    assert len(http.calls) == 2


def test_download_to_directory_keeps_subfolder(http, client, tmp_path):
    files = [file_entry('a.png', FIGURE), file_entry('panels/b.png', PANEL,
                                                     'supporting')]
    http.queue(make_response(200, version_payload(files)), redirect(),
               make_response(200, content=PANEL))
    written = client.download_artefact_file(REF, 'panels/b.png', tmp_path)
    assert written == tmp_path / 'panels' / 'b.png'
    assert written.read_bytes() == PANEL
    assert http.calls[1]['url'] == f'{BASE}/artefacts/{REF}/v2/files/panels/b.png'
    assert http.calls[2]['kwargs']['stream'] is True


def test_download_checksum_mismatch_removes_file(http, client, tmp_path):
    files = [file_entry('a.png', FIGURE)]
    tampered = b'X' * len(FIGURE)
    http.queue(make_response(200, version_payload(files)), redirect(),
               make_response(200, content=tampered))
    with pytest.raises(ArtefactIntegrityError) as caught:
        client.download_artefact_file(REF, 'a.png', tmp_path / 'out.png')
    assert caught.value.status == 'checksum_mismatch'
    assert caught.value.expected_sha256 == files[0]['sha256']
    assert caught.value.actual_sha256 == hashlib.sha256(tampered).hexdigest()
    assert list(tmp_path.iterdir()) == []


def test_download_size_mismatch(http, client):
    files = [file_entry('a.png', FIGURE)]
    http.queue(make_response(200, version_payload(files)),
               make_response(200, content=FIGURE + b'extra'))
    with pytest.raises(ArtefactIntegrityError):
        client.download_artefact_file(REF, 'a.png')


def test_download_verify_off(http, client):
    files = [file_entry('a.png', FIGURE)]
    http.queue(make_response(200, version_payload(files)),
               make_response(200, content=b'other'))
    assert client.download_artefact_file(REF, 'a.png', verify=False) == b'other'


def test_download_unknown_file_lists_names(http, client):
    http.queue(make_response(200, version_payload([file_entry('a.png', FIGURE)])))
    with pytest.raises(ArtefactFileNotFoundError, match='a.png') as caught:
        client.download_artefact_file(REF, 'b.png')
    assert caught.value.status == 'file_not_found'
    assert caught.value.file == 'b.png'
    assert len(http.calls) == 1


def test_server_file_not_found_is_typed(http, client):
    http.queue(make_response(200, version_payload([file_entry('a.png', FIGURE)])),
               make_response(404, {'status': 'file_not_found', 'message': 'no file',
                                   'ref': REF + '@v2', 'file': 'a.png'}))
    with pytest.raises(ArtefactFileNotFoundError) as caught:
        client.download_artefact_file(REF, 'a.png')
    assert isinstance(caught.value, ArtefactNotFoundError)
    assert caught.value.ref == REF + '@v2'


def test_listing_new_error_words(http, client):
    http.queue(make_response(422, {'status': 'invalid_group_id', 'message': 'no'}),
               make_response(422, {'status': 'invalid_limit', 'message': 'no'}))
    with pytest.raises(ArtefactError) as caught:
        client.list_artefacts(group_id='!!')
    assert caught.value.status == 'invalid_group_id'
    with pytest.raises(ArtefactError) as caught:
        client.list_artefacts(limit=500)
    assert caught.value.status == 'invalid_limit'


def test_signed_link_failure_hides_signature(http, client):
    http.queue(make_response(200, version_payload([file_entry('a.png', FIGURE)])),
               redirect(), make_response(403, content=b'<Error>expired</Error>',
                                         url=SIGNED))
    with pytest.raises(ArtefactDownloadError) as caught:
        client.download_artefact_file(REF, 'a.png')
    assert 'Signature' not in str(caught.value)
    assert 'secret' not in str(caught.value)
    assert caught.value.response is None
    assert 's3.example.org' in str(caught.value)


@pytest.mark.parametrize('status, word, error_class', [
    (404, 'not_on_this_site', ArtefactNotOnThisSiteError),
    (502, 'integrity_error', ArtefactIntegrityError),
    (503, 'storage_unavailable', ArtefactStorageUnavailableError),
    (429, 'rate_limited', ArtefactRateLimitedError),
])
def test_download_refusals_are_typed(http, client, status, word, error_class):
    http.queue(make_response(200, version_payload([file_entry('a.png', FIGURE)])),
               make_response(status, {'status': word, 'message': 'no',
                                      'ref': REF + '@v2', 'file': 'a.png'},
                             headers={'Retry-After': '30'}))
    with pytest.raises(error_class) as caught:
        client.download_artefact_file(REF, 'a.png')
    assert caught.value.file == 'a.png'
    assert caught.value.retry_after == 30.0


def test_download_artefact_all_files_and_manifest(http, client, tmp_path):
    files = [file_entry('a.png', FIGURE), file_entry('panels/b.png', PANEL,
                                                     'supporting')]
    http.queue(make_response(200, version_payload(files)),
               redirect(), make_response(200, content=FIGURE),
               make_response(200, content=PANEL))
    written = client.download_artefact(REF, tmp_path / 'out')
    assert written['a.png'].read_bytes() == FIGURE
    assert written['panels/b.png'].read_bytes() == PANEL
    manifest = written['manifest.json']
    assert manifest == tmp_path / 'out' / 'manifest.json'
    assert '"schema": "anthive.artefact/1"' in manifest.read_text()
    # one version read, then each file of exactly that version
    assert [call['url'] for call in http.calls if BASE in call['url']] == [
        f'{BASE}/artefacts/{REF}/latest',
        f'{BASE}/artefacts/{REF}/v2/files/a.png',
        f'{BASE}/artefacts/{REF}/v2/files/panels/b.png']


def test_download_artefact_selected_files(http, client, tmp_path):
    files = [file_entry('a.png', FIGURE), file_entry('panels/b.png', PANEL)]
    http.queue(make_response(200, version_payload(files)),
               make_response(200, content=PANEL))
    written = client.download_artefact(REF, tmp_path, files=['panels/b.png'],
                                       write_manifest=False)
    assert set(written) == {'panels/b.png'}


def test_download_artefact_unknown_selected_file(http, client, tmp_path):
    http.queue(make_response(200, version_payload([file_entry('a.png', FIGURE)])))
    with pytest.raises(ArtefactFileNotFoundError):
        client.download_artefact(REF, tmp_path, files=['nope.png'])


def test_download_artefact_manifest_name_clash(http, client, tmp_path):
    body = b'{"user": "file"}'
    files = [file_entry('manifest.json', body)]
    http.queue(make_response(200, version_payload(files)),
               make_response(200, content=body))
    written = client.download_artefact(REF, tmp_path)
    assert written['manifest.json'] == tmp_path / '_manifest.json'
    assert (tmp_path / 'manifest.json').read_bytes() == body


def test_download_refuses_unsafe_manifest_names(http, client, tmp_path):
    files = [file_entry('../escape.png', FIGURE)]
    http.queue(make_response(200, version_payload(files)))
    with pytest.raises(ValueError):
        client.download_artefact(REF, tmp_path)
    assert not (tmp_path.parent / 'escape.png').exists()


# ── analysis collections ────────────────────────────────────────────────


def test_list_collections(http, client):
    http.queue(make_response(200, {'n_collections': 1, 'collections': [
        {'group_id': 'AT6', 'collection_kind': 'analysis', 'n_datasets': 0}]}))
    result = client.list_collections()
    assert http.last['url'] == f'{BASE}/collections'
    assert not http.last['params']
    assert result['n_collections'] == 1
    client.list_collections(kind='datasets')
    assert http.last['params'] == {'kind': 'datasets'}


def test_list_collections_dataframe_and_invalid_kind(http, client):
    http.queue(make_response(200, {'n_collections': 2, 'collections': [
        {'group_id': 'AT6'}, {'group_id': 'S19'}]}),
        make_response(422, {'status': 'invalid_kind', 'message': 'no'}))
    assert list(client.list_collections(format='dataframe')['group_id']) == ['AT6', 'S19']
    with pytest.raises(ArtefactError) as caught:
        client.list_collections(kind='movies')
    assert caught.value.status == 'invalid_kind'


def test_list_analysis_collections_uses_collections_route(http, client):
    http.queue(make_response(200, {'n_collections': 1, 'collections': [
        {'group_id': 'AT6', 'collection_kind': 'analysis'}]}))
    collections = client.list_analysis_collections()
    assert [row['group_id'] for row in collections] == ['AT6']
    assert len(http.calls) == 1
    assert http.last['url'] == f'{BASE}/collections'
    assert http.last['params'] == {'kind': 'analysis'}


# ── servers older than 2.47.0 ───────────────────────────────────────────


@pytest.mark.parametrize('call', [
    lambda c: c.list_artefacts(),
    lambda c: c.get_artefact(REF),
    lambda c: c.get_artefact_versions(REF),
    lambda c: c.download_artefact_file(REF, 'a.png'),
    lambda c: c.get_artefact_preview(REF, 'a.png.webp'),
    lambda c: c.list_collections(),
    lambda c: c.list_artefact_purges(),
    lambda c: c.list_analysis_collections(),
])
def test_old_server_raises_server_too_old(http, client, call):
    http.queue(make_response(404, {'detail': 'Not Found'}),
               make_response(200, {'version': '2.46.4'}))
    with pytest.raises(ServerTooOldError) as caught:
        call(client)
    assert caught.value.server_version == '2.46.4'
    assert caught.value.required_version == '2.47.0'
    assert '2.47.0+' in str(caught.value) and '2.46.4' in str(caught.value)
    assert isinstance(caught.value, ArtefactError)
    assert not isinstance(caught.value, ArtefactNotFoundError)


def test_old_server_check_when_version_unreadable(http, client):
    http.queue(make_response(404, {'detail': 'Not Found'}),
               make_response(500, {}), make_response(500, {}))
    with pytest.raises(ServerTooOldError, match='version unknown'):
        client.list_artefacts()


def test_new_server_404_with_status_word_is_not_too_old(http, client):
    http.queue(make_response(404, {'status': 'not_found', 'message': 'no artefact'}))
    with pytest.raises(ArtefactNotFoundError):
        client.get_artefact(REF)
    assert len(http.calls) == 1


# ── purge requests ──────────────────────────────────────────────────────


def test_list_artefact_purges(http, client):
    purge = {'ref': REF, 'version': 1, 'state': 'needs_decision', 'reason': 'wrong',
             'requested': '2026-10-19', 'updated': '2026-10-19',
             'requested_by': 'tester', 'detail': 'sha256 differs'}
    http.queue(make_response(200, {'purges': [purge]}))
    assert client.list_artefact_purges()['purges'] == [purge]
    assert http.last['url'] == f'{BASE}/artefacts/purges'
    assert not http.last['params']
    client.list_artefact_purges(state='done')
    assert http.last['params'] == {'state': 'done'}
    client.list_artefact_purges(action='soft')
    assert http.last['params'] == {'action': 'soft'}
    client.list_artefact_purges(state='done', action='hard')
    assert http.last['params'] == {'state': 'done', 'action': 'hard'}


def test_list_artefact_purges_refusals(http, client):
    http.queue(make_response(422, {'status': 'invalid_state', 'message': 'no'}),
               make_response(403, {'status': 'forbidden', 'message': 'sign in'}))
    with pytest.raises(ArtefactError) as caught:
        client.list_artefact_purges(state='gone')
    assert caught.value.status == 'invalid_state'
    with pytest.raises(ArtefactError) as caught:
        client.list_artefact_purges()
    assert caught.value.status_code == 403
    http.queue(make_response(422, {'status': 'invalid_action', 'message': 'no'}))
    with pytest.raises(ArtefactError) as caught:
        client.list_artefact_purges(action='nuke')
    assert caught.value.status == 'invalid_action'


# ── deposits: typed refusals and wait_for_deposit ───────────────────────


def test_deposit_not_owner_and_quota_are_typed(http, client):
    http.queue(make_response(403, {'status': 'not_owner', 'message': 'owner only'}))
    with pytest.raises(DepositNotOwnerError):
        client.get_deposit('d1')
    http.queue(make_response(413, {'status': 'quota_exceeded', 'message': 'full'}))
    with pytest.raises(DepositQuotaError) as caught:
        client.get_deposit('d1')
    assert caught.value.status == 'quota_exceeded'


def test_wait_for_deposit_live(http, client, monkeypatch):
    sleeps: List[float] = []
    monkeypatch.setattr(vark.client.time, 'sleep', sleeps.append)
    http.queue(make_response(200, {'deposit_id': 'd1', 'state': 'uploaded'}),
               make_response(200, {'deposit_id': 'd1', 'state': 'checking'}),
               make_response(200, {'deposit_id': 'd1', 'state': 'live',
                                   'artefact': {'ref_version': REF + '@v1'}}))
    result = client.wait_for_deposit('d1', timeout=600, poll_interval=5)
    assert result['artefact']['ref_version'] == REF + '@v1'
    assert sleeps == [5.0, 5.0]


def test_wait_for_deposit_held(http, client, monkeypatch):
    monkeypatch.setattr(vark.client.time, 'sleep', lambda seconds: None)
    http.queue(make_response(200, {'deposit_id': 'd1', 'state': 'held',
                                   'held_reasons': ['public_access',
                                                    'made_from_internal']}))
    with pytest.raises(DepositHeldError) as caught:
        client.wait_for_deposit('d1')
    assert caught.value.held_reasons == ['public_access', 'made_from_internal']
    assert caught.value.status == 'held'
    assert 'made_from_internal' in str(caught.value)


def test_wait_for_deposit_failed(http, client):
    http.queue(make_response(200, {'deposit_id': 'd1', 'state': 'failed',
                                   'error': 'not_owner'}))
    with pytest.raises(DepositStoppedError) as caught:
        client.wait_for_deposit('d1')
    assert caught.value.status == 'failed'
    assert caught.value.deposit['error'] == 'not_owner'


def test_wait_for_deposit_timeout(http, client, monkeypatch):
    monkeypatch.setattr(vark.client.time, 'sleep', lambda seconds: None)
    http.queue(make_response(200, {'deposit_id': 'd1', 'state': 'checking'}))
    with pytest.raises(TimeoutError):
        client.wait_for_deposit('d1', timeout=0)


def test_vocab_caller_rights_pass_through(http, client):
    caller = {'user': 'tester', 'is_admin': False, 'may_deposit_datasets': False,
              'may_deposit_artefacts': True, 'may_create_collections': True}
    http.queue(make_response(200, {'caller': caller, 'artefacts': {
        'may_deposit_artefacts': True, 'may_create_collections': True}}))
    vocab = client.get_deposit_vocab()
    assert vocab['caller'] == caller
    assert vocab['artefacts']['may_create_collections'] is True
    assert 'may_deposit_artefacts' in AnthiveClient.get_deposit_vocab.__doc__
