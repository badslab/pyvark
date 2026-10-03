"""Integration test: pyvark against a throw-away ant-serve.

Starts ``bin/api/ant-serve`` from an anthive4 checkout on a free loopback
port, with a temporary state dir, a temporary h5adstore and a temporary
paper library that holds COPIES of a few records (git-initialised so
uploads can commit). Nothing is written outside a pytest tmp dir: no
real library, no real h5adstore, no S3 (no bucket is configured).

Skipped unless ``ANTHIVE4_SOURCE`` points at an anthive4 checkout (for
example ``git -C anthive4 archive main | tar -x -C /tmp/anthive4-main``).

Environment:
    ANTHIVE4_SOURCE       anthive4 tree whose bin/api/ant-serve is run.
    ANTHIVE_IT_LIBRARY    library to copy records from (default
                          ``$ANTHIVE4_SOURCE/data/library``).
    ANTHIVE_IT_CITEKEYS   comma-separated records to copy (default:
                          the first three records that have a PDF).
    ANTHIVE_IT_COLLECTION optional h5adstore collection folder; its .md,
                          .duckdb, .h5ad.mus, .env and static/ files are
                          copied so dataset-level endpoints can be tested.
    ANTHIVE_IT_DATASET    optional ``group/file`` id expected to have
                          linked papers.

The server runs with ``auth.mode: basic`` and one admin; the client sends
the ``Remote-User`` header a proxy would add. Run with::

    ANTHIVE4_SOURCE=/tmp/anthive4-main \\
    ANTHIVE_IT_COLLECTION=/path/to/h5adstore/Sankowski2019 \\
        uv run --with pytest --with requests --with pandas --no-project \\
        python -m pytest tests/test_integration_server.py -v
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator, List

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vark import (  # noqa: E402
    AnthiveClient,
    PaperDuplicateError,
    PaperInvalidError,
    PaperUploadDisabledError,
    PaperUploadForbiddenError,
)

SOURCE = os.environ.get('ANTHIVE4_SOURCE')
pytestmark = pytest.mark.skipif(
    not SOURCE, reason='set ANTHIVE4_SOURCE to an anthive4 checkout to run')

ADMIN = 'pyvark-it'


def _minimal_pdf(text: str) -> bytes:
    """A small but valid one-page PDF (correct xref offsets)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _copy_records(source_library: Path, target_library: Path) -> List[str]:
    wanted = [key.strip() for key in
              os.environ.get('ANTHIVE_IT_CITEKEYS', '').split(',') if key.strip()]
    records = sorted(source_library.glob('papers/**/*.md'))
    chosen = []
    for record in records:
        if record.name in ('README.md', 'REVIEW.md'):
            continue
        if wanted:
            if record.stem not in wanted:
                continue
        elif not record.with_suffix('.pdf').exists():
            continue
        chosen.append(record)
        if not wanted and len(chosen) == 3:
            break
    citekeys = []
    for record in chosen:
        relative = record.relative_to(source_library)
        destination = target_library / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record, destination)
        pdf = record.with_suffix('.pdf')
        if pdf.exists():
            shutil.copy2(pdf, destination.with_suffix('.pdf'))
        citekeys.append(record.stem)
    for folder in ('lab', 'datasets', 'methods', 'reading', 'proposals'):
        (target_library / 'papers' / folder).mkdir(parents=True, exist_ok=True)
    return citekeys


def _copy_collection(collection: Path, store: Path) -> None:
    target = store / collection.name
    target.mkdir(parents=True)
    for entry in collection.iterdir():
        if entry.is_file() and (entry.suffix in ('.md', '.duckdb', '.mus')
                                or entry.name == '.env'):
            shutil.copy2(entry, target / entry.name)
    static = collection / 'static'
    if static.is_dir():
        shutil.copytree(static, target / 'static')


@pytest.fixture(scope='module')
def server(tmp_path_factory) -> Iterator[dict]:
    source = Path(SOURCE).resolve()
    serve = source / 'bin' / 'api' / 'ant-serve'
    assert serve.exists(), f'no ant-serve under {source}'
    root = tmp_path_factory.mktemp('anthive-it')
    library = root / 'library'
    store = root / 'h5adstore'
    store.mkdir()
    (root / 'library_index').mkdir()
    source_library = Path(os.environ.get('ANTHIVE_IT_LIBRARY',
                                         source / 'data' / 'library'))
    if not source_library.is_dir():
        pytest.skip(f'no library to copy records from at {source_library}')
    citekeys = _copy_records(source_library, library)
    assert citekeys, 'no records copied'
    collection = os.environ.get('ANTHIVE_IT_COLLECTION')
    if collection:
        _copy_collection(Path(collection), store)
    git_env = {**os.environ, 'GIT_AUTHOR_NAME': 'it', 'GIT_AUTHOR_EMAIL': 'it@x',
               'GIT_COMMITTER_NAME': 'it', 'GIT_COMMITTER_EMAIL': 'it@x'}
    subprocess.run(['git', 'init', '-q', str(library)], check=True)
    (library / '.gitignore').write_text('*.pdf\n')
    subprocess.run(['git', '-C', str(library), 'add', '-A'], check=True, env=git_env)
    subprocess.run(['git', '-C', str(library), '-c', 'commit.gpgsign=false',
                    'commit', '-qm', 'test library'], check=True, env=git_env)
    config = root / 'anthive.yaml'
    config.write_text(f"""\
h5adstore: {store}
library: {library}
library_index: {root / 'library_index'}
state_dir: {root / 'state'}
tmp_dir: {root / 'tmp'}
model_cache: {root / 'models'}
webapp_dir: {root / 'webapp'}
geneset_store: {root / 'genesetstore'}
catalog_scan: local
library_upload_groups: [admins]
library_git_push: false
library_s3_autopush: false
auth:
  mode: basic
  admins: [{ADMIN}]
s3:
  bucket: null
""")
    port = _free_port()
    env = {**os.environ, 'ANTHIVE_CONFIG': str(config),
           'HF_HUB_OFFLINE': '1', 'PYTHONUNBUFFERED': '1'}
    for key in ('ANTHIVE_H5ADSTORE', 'ANTHIVE_LIBRARY', 'ANTHIVE_STATE_DIR',
                'ANTHIVE_AUTH_MODE', 'ANTHIVE_LIBRARY_INDEX'):
        env.pop(key, None)
    log_path = root / 'ant-serve.log'
    log = open(log_path, 'w')
    process = subprocess.Popen(
        [str(serve), '--host', '127.0.0.1', '--port', str(port),
         '--data-folder', str(store)],
        cwd=str(source), env=env, stdout=log, stderr=subprocess.STDOUT)
    base_url = f'http://127.0.0.1:{port}'
    try:
        deadline = time.time() + 600
        while True:
            if process.poll() is not None:
                pytest.fail(f'ant-serve exited:\n{log_path.read_text()[-4000:]}')
            try:
                status = requests.get(f'{base_url}/library/status', timeout=2)
                if status.status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                pytest.fail(f'ant-serve did not come up:\n{log_path.read_text()[-4000:]}')
            time.sleep(1)
        yield {'base_url': base_url, 'library': library, 'citekeys': citekeys,
               'log': log_path, 'store': store}
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        # Restore permissions in case a test failed while the library was r/o.
        for path in (library, library / 'papers'):
            if path.exists():
                path.chmod(0o755)


@pytest.fixture(scope='module')
def admin(server) -> AnthiveClient:
    client = AnthiveClient(server['base_url'], vark_config=False)
    client.headers['Remote-User'] = ADMIN   # what the basic-auth proxy adds
    return client


@pytest.fixture(scope='module')
def reader(server) -> AnthiveClient:
    client = AnthiveClient(server['base_url'], vark_config=False)
    client.headers['Remote-User'] = 'someone-else'
    return client


# ── reads ───────────────────────────────────────────────────────────────


def test_version_is_at_least_api_target(admin):
    version = admin.get_version()['version']
    assert tuple(int(p) for p in version.split('.')[:2]) >= (2, 41), version


def test_list_and_get_papers(admin, server):
    papers = admin.list_papers()
    listed = {paper['citekey'] for paper in papers}
    assert set(server['citekeys']) <= listed
    citekey = server['citekeys'][0]
    paper = admin.get_paper(citekey)
    assert paper['citekey'] == citekey
    assert 'access' not in paper and 'llm' not in paper   # gone in 2.41
    year = str(paper.get('year') or paper.get('date', ''))[:4]
    if year.isdigit():
        assert citekey in {p['citekey'] for p in admin.list_papers(year=year)}


def test_list_papers_dataframe(admin, server):
    pytest.importorskip('pandas')
    frame = admin.list_papers(format='dataframe')
    assert 'citekey' in frame.columns
    assert len(frame) >= len(server['citekeys'])


def test_unknown_paper_is_404(admin):
    with pytest.raises(requests.HTTPError) as info:
        admin.get_paper('nosuchpaper1900x')
    assert info.value.response.status_code == 404


def test_bibtex(admin, server):
    citekey = server['citekeys'][0]
    entry = admin.get_paper_bibtex(citekey)
    assert entry.lstrip().startswith('@') and citekey in entry
    classic = admin.get_paper_bibtex(citekey, classic=True)
    assert citekey in classic
    whole = admin.get_library_bibtex()
    assert all(key in whole for key in server['citekeys'])
    some = admin.get_library_bibtex(citekeys=server['citekeys'][:1])
    assert server['citekeys'][0] in some
    if len(server['citekeys']) > 1:
        assert server['citekeys'][1] not in some


def test_related_and_status(admin, server):
    related = admin.get_related_papers(server['citekeys'][0], limit=5)
    assert isinstance(related, list)
    status = admin.get_library_status()
    assert isinstance(status, dict)


def test_download_pdf(admin, server, tmp_path):
    citekey = server['citekeys'][0]
    data = admin.download_paper_pdf(citekey)
    assert data[:5] == b'%PDF-'
    target = admin.download_paper_pdf(citekey, dest=tmp_path)
    assert target.parent == tmp_path and target.read_bytes() == data


def test_search_literature_without_index(admin):
    # The temp server has no literature index: the call must still answer.
    result = admin.search_literature('microglia', k=3, mode='keyword')
    assert 'results' in result


def test_dataset_papers(admin, server):
    databases = admin.get_databases()
    if not databases:
        pytest.skip('no collection copied (set ANTHIVE_IT_COLLECTION)')
    expected = os.environ.get('ANTHIVE_IT_DATASET') or databases[0]['id']
    papers = admin.get_database_papers(expected)
    assert isinstance(papers, list)
    if os.environ.get('ANTHIVE_IT_DATASET'):
        assert papers, f'no papers linked to {expected}'
        assert all('citekey' in paper for paper in papers)
    context = admin.get_database_context(expected, budget_tokens=500)
    assert isinstance(context, dict)
    files = admin.list_database_files(expected)
    assert isinstance(files, list)


def test_existing_surface_on_dataset(admin):
    """A quick pass over pre-library methods to confirm they still match."""
    databases = admin.get_databases()
    if not databases:
        pytest.skip('no collection copied (set ANTHIVE_IT_COLLECTION)')
    db_id = databases[0]['id']
    info = admin.get_database_info(db_id)
    assert info
    genes = admin.search_genes(db_id, q='APO', limit=5)
    assert isinstance(genes, list)
    layers = admin.get_layers(db_id)
    assert 'X' in layers
    fields = admin.get_metadata_fields(db_id)
    assert 'categorical' in fields and 'numerical' in fields
    embeddings = admin.get_embeddings(db_id)
    assert isinstance(embeddings, dict)
    cells = admin.get_cells(db_id, metadata=fields['categorical'][:1], limit=5)
    assert len(cells['data']) <= 5
    summary = admin.get_obs_summary(db_id)
    assert 'columns' in summary
    numerical = fields['numerical'][0]
    plot = admin.get_plot(db_id, 'histogram', x=numerical,
                          format='csv', width=4, height=3, dpi=72)
    assert numerical.encode() in plot['bytes']
    # Gene-level reads need the dataset's layer parquet sidecars, which a
    # copied .duckdb may reference by absolute path outside the sandbox.
    try:
        stats = admin.get_gene_stats(db_id, top=5)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 500:
            pytest.skip(f'gene-level data not reachable from the temp store: {exc}')
        raise
    assert isinstance(stats, list)


def test_module_score_session_plot(admin):
    databases = admin.get_databases()
    if not databases:
        pytest.skip('no collection copied (set ANTHIVE_IT_COLLECTION)')
    db_id = databases[0]['id']
    try:
        score = admin.module_score(db_id, ['P2RY12', 'CX3CR1', 'TMEM119'])
    except requests.HTTPError as exc:
        pytest.skip(f'module_score unavailable on this dataset: {exc} {exc.response.text if exc.response is not None else ""}')
    assert 'session_id' in score and 'summary' in score
    plot = admin.get_plot(db_id, 'histogram', x='module_score',
                          attach_sessions=score['session_id'],
                          format='csv', width=4, height=3, dpi=72)
    assert b'module_score' in plot['bytes']
    query = admin.analytics_query(
        db_id, 'SELECT COUNT(*) AS n FROM scores',
        attach_sessions=score['session_id'])
    assert query['row_count'] == 1


# ── upload ──────────────────────────────────────────────────────────────

NEW_RECORD = {
    'entrytype': 'article',
    'title': 'A synthetic record for the pyvark integration test',
    'author': ['Tester, Pyvark'],
    'year': 2026,
    'doi': '10.99999/pyvark.it.2026',
    'journaltitle': 'Journal of Tests',
}


def test_requirements_forbidden_for_non_uploader(reader):
    with pytest.raises(PaperUploadForbiddenError) as info:
        reader.get_paper_upload_requirements()
    assert info.value.status_code == 403
    assert info.value.body.get('status') == 'forbidden'


def test_upload_forbidden_for_non_uploader(reader):
    with pytest.raises(PaperUploadForbiddenError):
        reader.upload_paper(NEW_RECORD, dry_run=True, enrich=False)


def test_requirements_for_uploader(admin):
    requirements = admin.get_paper_upload_requirements()
    assert requirements['uploads_enabled'] is True
    assert requirements['default_role'] == 'background'
    assert isinstance(requirements['roles'], dict)
    assert isinstance(requirements['entrytypes'], dict)
    assert 'proposals' in requirements['folders']


def test_upload_dry_run_then_real_then_duplicate(admin, server):
    dry = admin.upload_paper(NEW_RECORD, _minimal_pdf('pyvark'), enrich=False,
                             dry_run=True, papers_for=['S19/SMI'])
    assert dry['status'] == 'dry_run'
    citekey = dry['citekey']
    assert not list(server['library'].glob(f'papers/**/{citekey}.md'))

    created = admin.upload_paper(NEW_RECORD, _minimal_pdf('pyvark'), enrich=False,
                                 papers_for={'S19/SMI': 'related'})
    assert created['status'] == 'created'
    assert created['citekey'] == citekey
    written = list(server['library'].glob(f'papers/**/{citekey}.md'))
    assert written, 'record not written to the temp library'
    text = written[0].read_text()
    assert 'anthive_role: background' in text          # 2.41 default role
    assert 'anthive_proposed_links' in text
    log = subprocess.run(['git', '-C', str(server['library']), 'log', '--format=%an',
                          '-1'], capture_output=True, text=True).stdout.strip()
    assert log == ADMIN

    # The new paper is readable straight away.
    assert admin.get_paper(citekey)['citekey'] == citekey
    assert admin.download_paper_pdf(citekey)[:5] == b'%PDF-'

    with pytest.raises(PaperDuplicateError) as info:
        admin.upload_paper(NEW_RECORD, enrich=False)
    assert info.value.existing_citekey == citekey
    assert info.value.matched_on in ('doi', 'citekey')


def test_upload_invalid(admin):
    with pytest.raises(PaperInvalidError) as info:
        admin.upload_paper({'entrytype': 'article', 'title': 'No authors'},
                           enrich=False, dry_run=True)
    assert info.value.status_code == 422
    assert info.value.missing_required or info.value.errors


def test_bulk_upload(admin, tmp_path):
    folder = tmp_path / 'bulk'
    folder.mkdir()
    (folder / 'one.md').write_text(
        "---\nentrytype: report\ntype: technical report\n"
        "title: Bulk upload report one\nauthor:\n- Tester, Bulk\nyear: 2026\n"
        "institution: KU Leuven\n---\nFirst bulk record.\n")
    (folder / 'one.pdf').write_bytes(_minimal_pdf('bulk one'))
    (folder / 'two.md').write_text(
        "---\nentrytype: article\ntitle: Missing identifier\n"
        "author:\n- Tester, Bulk\nyear: 2026\n---\n")
    outcomes = admin.upload_papers(AnthiveClient.paper_items_from_folder(folder),
                                   enrich=False)
    assert [outcome['ok'] for outcome in outcomes] == [True, False]
    assert outcomes[1]['status'] == 'invalid'
    assert outcomes[1]['http_status'] == 422


def test_upload_disabled_when_library_read_only(admin, server):
    library = server['library']
    library.chmod(0o555)
    (library / 'papers').chmod(0o555)
    try:
        with pytest.raises(PaperUploadDisabledError) as info:
            admin.upload_paper({**NEW_RECORD, 'doi': '10.99999/pyvark.it.ro'},
                               enrich=False)
        assert info.value.status_code == 503
        assert admin.get_paper_upload_requirements()['uploads_enabled'] is False
    finally:
        (library / 'papers').chmod(0o755)
        library.chmod(0o755)
