"""Integration test: pyvark's artefact methods against a throw-away ant-serve.

Starts ``bin/api/ant-serve`` from an anthive4 tree (REST API 2.47.0+) on a
free loopback port in 18700-18799, with a temporary store that holds two
analysis collections and their artefacts (written with anthive4's own
``tests/artefact_helpers.py``), a temporary state dir and a small fake S3
(HEAD and presigned GET, path style) in this process. Optionally one
dataset collection is COPIED in (``ANTHIVE_IT_COLLECTION``) to test a
dataset artefact. Nothing is written outside the pytest tmp dir; no real
store, no real bucket.

Skipped unless ``ANTHIVE4_SOURCE`` points at an anthive4 tree. Building
the store runs ``uv run --with pyyaml`` with that tree's ``lib/``.

Environment:
    ANTHIVE4_SOURCE        anthive4 tree whose bin/api/ant-serve is run.
    ANTHIVE_IT_COLLECTION  optional collection folder to copy (``.md``,
                           ``.duckdb``, ``.h5ad.mus``, ``.env``), e.g.
                           ``/path/to/h5adstore/Sankowski2019``; its first
                           dataset gets an artefact.

Run with::

    ANTHIVE4_SOURCE=/path/to/anthive4 \\
    ANTHIVE_IT_COLLECTION=/path/to/h5adstore/Sankowski2019 \\
        uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_integration_artefacts.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import unquote, urlsplit

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vark import (  # noqa: E402
    AnthiveClient,
    ArtefactError,
    ArtefactFileNotFoundError,
    ArtefactIntegrityError,
    ArtefactNotFoundError,
    ArtefactNotOnThisSiteError,
    ArtefactPurgedError,
)

SOURCE = os.environ.get('ANTHIVE4_SOURCE')
pytestmark = pytest.mark.skipif(
    not SOURCE, reason='set ANTHIVE4_SOURCE to an anthive4 tree to run')

FIG1 = b'\x89PNG version one'
FIG2 = b'\x89PNG version two bytes'
PANEL = b'\x89PNG panel b'
S3_BODY = b'S3 only body ' * 1000

#: run with the anthive4 tree's lib/ on sys.path; argv: source, store, dataset folder|'', file id|''
BUILD_SCRIPT = r'''
import hashlib, json, sys
from pathlib import Path
source, store, folder, file_id, group_id = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
sys.path.insert(0, str(source / 'lib'))
sys.path.insert(0, str(source))
from tests.artefact_helpers import write_artefact, write_index_md
FIG1 = b'\x89PNG version one'
FIG2 = b'\x89PNG version two bytes'
PANEL = b'\x89PNG panel b'
S3_BODY = b'S3 only body ' * 1000
write_index_md(store, 'Atlas2026', group='Atlas2026', group_id='AT6', collection_kind='analysis',
               title='Atlas analyses', authors=['A. Analyst'], year=2026, access='public', created_by='alice')
write_index_md(store, 'Notes2026', group='Notes2026', group_id='NO6', collection_kind='analysis',
               title='Internal notes', authors=['A. Analyst'], year=2026, access='internal', created_by='alice')
write_artefact(store, 'Atlas2026', 'AT6', '_group', 'figure', 'atlas-umap',
               [{'files': {'a.png': FIG1}}, {'files': {'a.png': FIG2, 'panels/b.png': PANEL}}], previews=True)
write_artefact(store, 'Atlas2026', 'AT6', '_group', 'table', 'atlas-table',
               [{'files': {'t.tsv': b'gene\tx\nA\t1\n'}, 'state': 'purged', 'purged_by': 'root',
                 'purged_by_admin': True}, {'files': {'t.tsv': b'gene\tx\nA\t2\n'}}])
s3_only = write_artefact(store, 'Atlas2026', 'AT6', '_group', 'report', 'atlas-s3',
                         [{'files': {'r.pdf': S3_BODY}}], local_files=False)
bad = write_artefact(store, 'Atlas2026', 'AT6', '_group', 'report', 'atlas-bad',
                     [{'files': {'r.pdf': b'good'}}], local_files=False)
write_artefact(store, 'Atlas2026', 'AT6', '_group', 'other', 'atlas-gone', [{'files': {'x.txt': b'nowhere'}}],
               local_files=False)
write_artefact(store, 'Notes2026', 'NO6', '_group', 'notebook', 'notes-nb', [{'files': {'n.ipynb': b'{}'}}])
if folder:
    write_artefact(store, folder, group_id, file_id, 'figure', 'it-violin', [{'files': {'v.png': FIG1}}])
objects = {
    str(s3_only['path'].file_rel(1, 'r.pdf')): {'body': S3_BODY.hex(),
                                                 'sha256': hashlib.sha256(S3_BODY).hexdigest()},
    # stored bytes and sha256 metadata differ from the manifest's
    str(bad['path'].file_rel(1, 'r.pdf')): {'body': b'evil'.hex(), 'sha256': hashlib.sha256(b'evil').hexdigest()},
}
print(json.dumps(objects))
'''


def _free_port(start: int = 18700, stop: int = 18800,
               exclude: Optional[int] = None) -> int:
    for port in range(start, stop):
        if port == exclude:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    pytest.skip(f'no free port in {start}-{stop - 1}')


class FakeS3:
    """Path-style HEAD and GET for a fixed object map; logs every request."""

    def __init__(self, port: int, objects: Dict[str, Dict[str, str]]):
        self.objects = objects
        self.requests: List[Dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, with_body: bool) -> None:
                parts = urlsplit(self.path)
                bucket, _, key = unquote(parts.path).lstrip('/').partition('/')
                fake.requests.append({
                    'method': self.command, 'key': key,
                    'signed': 'X-Amz-Signature' in parts.query,
                    'authorization': self.headers.get('Authorization'),
                    'disposition': 'response-content-disposition' in parts.query})
                found = fake.objects.get(key) if bucket == 'labbucket' else None
                if found is None:
                    self.send_response(404)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                body = bytes.fromhex(found['body'])
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('x-amz-meta-sha256', found['sha256'])
                self.send_header('ETag', '"etag"')
                self.end_headers()
                if with_body:
                    self.wfile.write(body)

            def do_HEAD(self) -> None:  # noqa: N802
                self._answer(False)

            def do_GET(self) -> None:  # noqa: N802
                self._answer(True)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _copy_collection(collection: Path, store: Path) -> Optional[Dict[str, str]]:
    """Copy a collection's catalog files; return its first dataset's ids."""
    target = store / collection.name
    target.mkdir(parents=True)
    for entry in collection.iterdir():
        if entry.is_file() and (entry.suffix in ('.md', '.duckdb', '.mus') or entry.name == '.env'):
            shutil.copy2(entry, target / entry.name)
    group_id = None
    for line in (target / 'index.md').read_text().splitlines():
        if line.startswith('group_id:'):
            group_id = line.split(':', 1)[1].strip().strip('\'"')
    for md in sorted(target.glob('*.md')):
        if md.name == 'index.md' or not md.with_suffix('.duckdb').exists():
            continue
        for line in md.read_text().splitlines():
            if line.startswith('id:'):
                file_id = line.split(':', 1)[1].strip().strip('\'"')
                return {'folder': collection.name, 'group_id': group_id, 'file_id': file_id}
    return None


@pytest.fixture(scope='module')
def server(tmp_path_factory) -> Iterator[Dict[str, Any]]:
    source = Path(SOURCE).resolve()
    serve = source / 'bin' / 'api' / 'ant-serve'
    if not (source / 'lib' / 'artefacts.py').exists():
        pytest.skip(f'{source} has no artefact store (REST API 2.47.0+)')
    root = tmp_path_factory.mktemp('anthive-artefacts-it')
    store = root / 'h5adstore'
    store.mkdir()
    dataset = None
    if os.environ.get('ANTHIVE_IT_COLLECTION'):
        dataset = _copy_collection(Path(os.environ['ANTHIVE_IT_COLLECTION']), store)
    built = subprocess.run(
        ['uv', 'run', '--quiet', '--with', 'pyyaml', '--no-project', 'python', '-c', BUILD_SCRIPT,
         str(source), str(store), (dataset or {}).get('folder', ''), (dataset or {}).get('file_id', ''),
         (dataset or {}).get('group_id') or ''],
        check=True, capture_output=True, text=True, cwd=str(root))
    objects = json.loads(built.stdout.strip().splitlines()[-1])
    s3_port = _free_port()
    api_port = _free_port(exclude=s3_port)
    fake_s3 = FakeS3(s3_port, objects)
    config = root / 'anthive.yaml'
    config.write_text(f"""\
h5adstore: {store}
library: {root / 'library'}
library_index: {root / 'library_index'}
state_dir: {root / 'state'}
tmp_dir: {root / 'tmp'}
model_cache: {root / 'models'}
webapp_dir: {root / 'webapp'}
geneset_store: {root / 'genesetstore'}
catalog_scan: local
auth:
  mode: trusted-proxy
  admins: []
s3:
  endpoint: http://127.0.0.1:{s3_port}
  region: us-east-1
  bucket: labbucket
  use_path_style: true
  access_key_id: AKIAFAKEFAKEFAKE
  secret_access_key: fakefakefakefakefakefakefakefakefake
  prefix: ''
""")
    env = {**os.environ, 'ANTHIVE_CONFIG': str(config), 'HF_HUB_OFFLINE': '1',
           'PYTHONUNBUFFERED': '1', 'ANTHIVE_WARMUP': '0', 'ANTHIVE_FACET_WARMUP': '0'}
    for key in ('ANTHIVE_H5ADSTORE', 'ANTHIVE_LIBRARY', 'ANTHIVE_STATE_DIR', 'ANTHIVE_AUTH_MODE',
                'ANTHIVE_LIBRARY_INDEX', 'ANTHIVE_ARTEFACTS_S3_ACCESS_KEY_ID',
                'ANTHIVE_ARTEFACTS_S3_SECRET_ACCESS_KEY'):
        env.pop(key, None)
    log_path = root / 'ant-serve.log'
    log = open(log_path, 'w')
    process = subprocess.Popen(
        [str(serve), '--host', '127.0.0.1', '--port', str(api_port), '--data-folder', str(store)],
        cwd=str(source), env=env, stdout=log, stderr=subprocess.STDOUT)
    base_url = f'http://127.0.0.1:{api_port}'
    try:
        deadline = time.time() + 600
        while True:
            if process.poll() is not None:
                pytest.fail(f'ant-serve exited:\n{log_path.read_text()[-4000:]}')
            try:
                if requests.get(f'{base_url}/health', timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                pytest.fail(f'ant-serve did not come up:\n{log_path.read_text()[-4000:]}')
            time.sleep(1)
        yield {'base_url': base_url, 'fake_s3': fake_s3, 'dataset': dataset}
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        fake_s3.close()


def _client(server: Dict[str, Any], user: Optional[str] = None) -> AnthiveClient:
    client = AnthiveClient(server['base_url'], vark_config=False)
    # A proxied caller, not a loopback tool (those count as signed in).
    client.headers['X-Forwarded-For'] = '10.1.2.3'
    if user:
        client.headers['Remote-User'] = user
        client.headers['Remote-Groups'] = 'users'
    return client


@pytest.fixture(scope='module')
def anon(server) -> AnthiveClient:
    return _client(server)


@pytest.fixture(scope='module')
def alice(server) -> AnthiveClient:
    return _client(server, 'alice')


def test_server_is_2_47(anon):
    assert not anon._server_older_than((2, 47, 0)), anon.get_version().get('version')


def test_listing_follows_access_and_pages(anon, alice):
    anonymous = [row['ref'] for row in anon.list_artefacts(limit=2, all_pages=True)['artefacts']]
    assert anonymous == sorted(anonymous)
    assert {'AT6/_group/atlas-umap', 'AT6/_group/atlas-table'} <= set(anonymous)
    assert 'NO6/_group/notes-nb' not in anonymous
    signed_in = [row['ref'] for row in alice.list_artefacts(limit=200)['artefacts']]
    assert 'NO6/_group/notes-nb' in signed_in
    frame = alice.list_artefacts(kind='report', format='dataframe')
    assert sorted(frame['ref']) == ['AT6/_group/atlas-bad', 'AT6/_group/atlas-s3']


def test_listing_refusals(anon):
    with pytest.raises(ArtefactError) as caught:
        anon.list_artefacts(owner='alice')
    assert caught.value.status == 'invalid'
    with pytest.raises(ArtefactError) as caught:
        anon.list_artefacts(cursor='garbage')
    assert caught.value.status == 'invalid_cursor'


def test_detail_versions_and_tombstone(anon):
    detail = anon.get_artefact('AT6/_group/atlas-umap')
    assert [version['version'] for version in detail['versions']] == [1, 2]
    assert detail['manifest']['version'] == 2 and 'made_from' in detail['manifest']
    assert anon.get_artefact('AT6/_group/atlas-umap@v1')['version'] == 1
    tombstone = anon.get_artefact_versions('AT6/_group/atlas-table')['versions'][0]
    assert tombstone['state'] == 'purged' and tombstone['purged_by'] == 'an admin'
    with pytest.raises(ArtefactPurgedError) as caught:
        anon.get_artefact_version('AT6/_group/atlas-table@v1')
    assert caught.value.tombstone['version'] == 1
    assert anon.get_artefact_preview('AT6/_group/atlas-umap', 'a.png.webp').startswith(b'RIFF')


def test_download_local_copies_verified(anon, tmp_path):
    written = anon.download_artefact('AT6/_group/atlas-umap', tmp_path / 'umap')
    assert written['a.png'].read_bytes() == FIG2
    assert written['panels/b.png'].read_bytes() == PANEL
    assert json.loads(written['manifest.json'].read_text())['version'] == 2
    assert anon.download_artefact_file('AT6/_group/atlas-umap@v1', 'a.png') == FIG1


def test_download_redirect_to_signed_link(server, anon, tmp_path):
    path = anon.download_artefact_file('AT6/_group/atlas-s3', 'r.pdf', tmp_path)
    assert path.read_bytes() == S3_BODY
    gets = [entry for entry in server['fake_s3'].requests if entry['method'] == 'GET']
    assert gets and all(entry['signed'] and not entry['authorization'] for entry in gets)
    assert all(entry['disposition'] for entry in gets)


def test_download_refusals(anon):
    with pytest.raises(ArtefactIntegrityError) as caught:
        anon.download_artefact_file('AT6/_group/atlas-bad', 'r.pdf')
    assert caught.value.status_code == 502
    with pytest.raises(ArtefactNotOnThisSiteError):
        anon.download_artefact_file('AT6/_group/atlas-gone', 'x.txt')
    with pytest.raises(ArtefactNotFoundError):
        anon.get_artefact('NO6/_group/notes-nb')


def test_collections(server, anon, alice):
    assert [row['group_id'] for row in anon.list_analysis_collections()] == ['AT6']
    analysis = alice.list_analysis_collections()
    assert [row['group_id'] for row in analysis] == ['AT6', 'NO6']
    atlas = analysis[0]
    assert atlas['collection_kind'] == 'analysis' and atlas['artefacts_count'] == 5
    assert atlas['n_datasets'] == 0 and atlas['access'] == 'public'
    everything = alice.list_collections()
    assert everything['n_collections'] == len(everything['collections'])
    kinds = {row['group_id']: row['collection_kind'] for row in everything['collections']}
    assert kinds['AT6'] == 'analysis' and kinds['NO6'] == 'analysis'
    if server['dataset']:
        assert kinds[server['dataset']['group_id']] == 'datasets'
        datasets_only = alice.list_collections(kind='datasets')['collections']
        assert {row['collection_kind'] for row in datasets_only} == {'datasets'}
    with pytest.raises(ArtefactError) as caught:
        anon.list_collections(kind='movies')
    assert caught.value.status == 'invalid_kind'
    group = anon.get_group('AT6')
    assert group['collection_kind'] == 'analysis' and group['artefacts_count'] == 5


def test_new_error_words(anon):
    with pytest.raises(ArtefactError) as caught:
        anon.list_artefacts(group_id='!!')
    assert caught.value.status == 'invalid_group_id'
    with pytest.raises(ArtefactError) as caught:
        anon.list_artefacts(limit=500)
    assert caught.value.status == 'invalid_limit'


def test_server_file_not_found(server, anon):
    # bypass the client's manifest check to reach the server's answer
    response = anon._request('GET', '/artefacts/AT6/_group/atlas-umap/v2/files/nope.png',
                             allow_redirects=False)
    assert response.status_code == 404
    assert response.json()['status'] == 'file_not_found'
    with pytest.raises(ArtefactFileNotFoundError):
        anon.download_artefact_file('AT6/_group/atlas-umap', 'nope.png')


def test_artefact_purges(anon, alice):
    with pytest.raises(ArtefactError) as caught:
        anon.list_artefact_purges()
    assert caught.value.status_code == 403
    assert alice.list_artefact_purges() == {'purges': []}
    with pytest.raises(ArtefactError) as caught:
        alice.list_artefact_purges(state='gone')
    assert caught.value.status == 'invalid_state'


def test_dataset_artefact(server, alice):
    dataset = server['dataset']
    if not dataset:
        pytest.skip('set ANTHIVE_IT_COLLECTION to test a dataset artefact')
    db_id = f"{dataset['group_id']}/{dataset['file_id']}"
    rows = alice.list_artefacts(db_id=db_id)['artefacts']
    assert [row['ref'] for row in rows] == [f'{db_id}/it-violin']
    detail = alice.get_artefact(f'{db_id}/it-violin')
    assert detail['manifest']['made_from'][0]['db_id'] == db_id
    assert alice.get_database_info(db_id)['artefacts_count'] == 1
    assert hashlib.sha256(alice.download_artefact_file(f'{db_id}/it-violin', 'v.png')).hexdigest() == \
        hashlib.sha256(FIG1).hexdigest()
