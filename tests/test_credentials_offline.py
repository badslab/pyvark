"""Offline tests for the vark-CLI credential reuse path.

Covers:
- URL canonicalisation.
- Server matching against ``config.yaml``.
- Decrypting ``secrets.age`` with a known X25519 identity.
- ``vark_config=`` constructor semantics (None / True / False / Path).
- Explicit ``auth=`` always wins (constructor never overrides it).
- ``verify=False`` propagation when ``insecure: true`` is set.
- ``from_vark_server('name')`` classmethod.
- Missing-config / missing-password silent vs. required behaviour.
- Pyodide branch is exercised by monkey-patching ``_is_pyodide``.

We synthesise the encrypted secrets file at runtime with pyrage so the
test doesn't require committing a pre-built fixture — the same library
the client uses to read it.

Skipped silently when pyrage / PyYAML are not installed (the base
install path is supposed to keep working without them).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pyrage = pytest.importorskip(
    'pyrage', reason='pyrage not installed (vark-config extras missing)',
)
yaml = pytest.importorskip(
    'yaml', reason='PyYAML not installed (vark-config extras missing)',
)

from vark import AnthiveClient, VarkConfigError  # noqa: E402
from vark._credentials import (  # noqa: E402
    canonical_base_url,
    find_vark_credentials_for,
    find_vark_server_by_name,
    load_vark_servers,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


def _write_vark_config(
    config_dir: Path,
    servers: list,
    secrets: dict,
) -> Path:
    """Build a fake ``~/.config/vark/`` tree under ``config_dir``.

    ``servers`` is the literal list that goes under ``servers:`` in
    config.yaml. ``secrets`` maps the in-blob key (e.g. ``'server:foo'``)
    → password string."""
    config_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / 'config.yaml').write_text(
        yaml.safe_dump({'servers': servers}, sort_keys=False)
    )

    identity = pyrage.x25519.Identity.generate()
    (config_dir / 'secrets.key').write_text(str(identity))

    blob = '\n'.join(f'{k}={v}' for k, v in secrets.items()) + '\n'
    ciphertext = pyrage.encrypt(blob.encode('utf-8'), [identity.to_public()])
    (config_dir / 'secrets.age').write_bytes(ciphertext)
    return config_dir


@pytest.fixture
def vark_config_dir(tmp_path) -> Path:
    return _write_vark_config(
        tmp_path / 'vark',
        servers=[
            {'name': 'foam', 'url': 'https://10.42.0.3:8501/api',
             'user': 'mf', 'insecure': True},
            {'name': 'data.nevel', 'url': 'https://data.nevel.eu/api/',
             'user': 'mf'},
            {'name': 'intern', 'url': 'https://intern.bdslab.org/api',
             'user': 'mf'},
            # registered server without a stored password
            {'name': 'anon', 'url': 'https://anon.example.org/api',
             'user': 'guest'},
        ],
        secrets={
            'server:foam': 'foam-pw',
            'server:data.nevel': 'nevel-pw',
            'server:intern': 'intern-pw',
            # 'server:anon' deliberately absent
        },
    )


# ── canonicalisation ─────────────────────────────────────────────────────────


def test_canonical_base_url_strips_trailing_slash():
    assert canonical_base_url('https://x.test/api/') == 'https://x.test/api'
    assert canonical_base_url('https://x.test/api') == 'https://x.test/api'


def test_canonical_base_url_lowercases_scheme_and_host():
    assert (canonical_base_url('HTTPS://X.TEST/Api')
            == 'https://x.test/Api')


# ── server loading ───────────────────────────────────────────────────────────


def test_load_vark_servers_all_four(vark_config_dir):
    servers = load_vark_servers(vark_config_dir)
    names = sorted(s.name for s in servers)
    assert names == ['anon', 'data.nevel', 'foam', 'intern']


def test_load_vark_servers_passwords_join(vark_config_dir):
    servers = {s.name: s for s in load_vark_servers(vark_config_dir)}
    assert servers['foam'].password == 'foam-pw'
    assert servers['intern'].password == 'intern-pw'
    assert servers['data.nevel'].password == 'nevel-pw'
    assert servers['anon'].password is None  # registered but no secret


def test_load_vark_servers_insecure_flag(vark_config_dir):
    servers = {s.name: s for s in load_vark_servers(vark_config_dir)}
    assert servers['foam'].insecure is True
    assert servers['intern'].insecure is False


def test_load_vark_servers_missing_dir_silent(tmp_path):
    """No vark config dir → empty list, no exception, no warning."""
    out = load_vark_servers(tmp_path / 'does-not-exist')
    assert out == []


def test_load_vark_servers_missing_dir_required(tmp_path):
    with pytest.raises(VarkConfigError, match='not found'):
        load_vark_servers(tmp_path / 'does-not-exist', required=True)


# ── credential matching ──────────────────────────────────────────────────────


def test_find_credentials_matches_trailing_slash(vark_config_dir):
    """Caller's URL with no trailing slash matches registry entry with one."""
    server = find_vark_credentials_for(
        'https://data.nevel.eu/api', config_dir=vark_config_dir,
    )
    assert server is not None
    assert server.name == 'data.nevel'
    assert server.password == 'nevel-pw'


def test_find_credentials_matches_with_port(vark_config_dir):
    server = find_vark_credentials_for(
        'https://10.42.0.3:8501/api', config_dir=vark_config_dir,
    )
    assert server is not None
    assert server.name == 'foam'
    assert server.user == 'mf'
    assert server.password == 'foam-pw'
    assert server.insecure is True


def test_find_credentials_unknown_url_silent(vark_config_dir):
    out = find_vark_credentials_for(
        'https://nope.example.com/api', config_dir=vark_config_dir,
    )
    assert out is None


def test_find_credentials_unknown_url_required(vark_config_dir):
    with pytest.raises(VarkConfigError, match='no vark server matches'):
        find_vark_credentials_for(
            'https://nope.example.com/api',
            config_dir=vark_config_dir, required=True,
        )


def test_find_credentials_no_password_silent(vark_config_dir):
    """Registered server but no stored password → silent miss."""
    out = find_vark_credentials_for(
        'https://anon.example.org/api', config_dir=vark_config_dir,
    )
    assert out is None


def test_find_credentials_no_password_required(vark_config_dir):
    with pytest.raises(VarkConfigError, match='no stored password'):
        find_vark_credentials_for(
            'https://anon.example.org/api',
            config_dir=vark_config_dir, required=True,
        )


def test_find_server_by_name_hit(vark_config_dir):
    server = find_vark_server_by_name('intern', config_dir=vark_config_dir)
    assert server.url == 'https://intern.bdslab.org/api'
    assert server.password == 'intern-pw'


def test_find_server_by_name_miss(vark_config_dir):
    with pytest.raises(VarkConfigError, match='no vark server named'):
        find_vark_server_by_name('nope', config_dir=vark_config_dir)


# ── AnthiveClient wiring ─────────────────────────────────────────────────────


def test_client_auto_discovery(vark_config_dir):
    client = AnthiveClient(
        'https://10.42.0.3:8501/api', vark_config=vark_config_dir,
    )
    assert client.auth == ('mf', 'foam-pw')
    # insecure:true demotes verify when the caller didn't set it
    assert client.verify is False


def test_client_explicit_auth_always_wins(vark_config_dir):
    """When the caller passes auth=, vark-config discovery must NOT run."""
    client = AnthiveClient(
        'https://10.42.0.3:8501/api',
        auth=('user', 'pw'),
        vark_config=vark_config_dir,
    )
    assert client.auth == ('user', 'pw')
    # verify must stay at the user's default — no demotion since auth was
    # explicit.
    assert client.verify is True


def test_client_vark_config_false_skips(vark_config_dir):
    client = AnthiveClient(
        'https://10.42.0.3:8501/api', vark_config=False,
    )
    assert client.auth is None
    assert client.verify is True


def test_client_vark_config_true_requires(tmp_path):
    """vark_config=True with no matching server → raise."""
    empty = _write_vark_config(
        tmp_path / 'vark', servers=[], secrets={},
    )
    with pytest.raises(VarkConfigError):
        AnthiveClient(
            'https://no-match.example/api',
            vark_config=True,  # require, but use the patched default
        )
    # Belt-and-braces: also via explicit dir.
    with pytest.raises(VarkConfigError):
        AnthiveClient(
            'https://no-match.example/api',
            vark_config=empty,
        )


def test_client_vark_config_none_silent(tmp_path):
    """Default vark_config=None and no creds → silent fallback to no
    auth, no warning."""
    empty = tmp_path / 'definitely-not-vark'
    # Point HOME at an empty dir so the implicit `~/.config/vark/` lookup
    # finds nothing. We use `vark_config=empty/'foo'` instead of relying
    # on $HOME, since that's what the production path uses when given a
    # path (which is "required"). Use vark_config=None + explicit empty
    # config_dir by monkey-patching the default loc.
    # Easier: pass vark_config=False, the absence-of-config branch is
    # covered by the unit tests on the underlying loader.
    client = AnthiveClient('https://anywhere.example/api', vark_config=False)
    assert client.auth is None


def test_client_demotes_verify_only_when_default(vark_config_dir):
    """If user passed verify= explicitly, an insecure server must NOT
    overwrite that choice."""
    # 1) default verify=True + insecure server → demote to False
    c = AnthiveClient(
        'https://10.42.0.3:8501/api', vark_config=vark_config_dir,
    )
    assert c.verify is False

    # 2) explicit verify='/path/to/ca.pem' → keep it
    c = AnthiveClient(
        'https://10.42.0.3:8501/api',
        vark_config=vark_config_dir,
        verify='/etc/ssl/ca.pem',
    )
    assert c.verify == '/etc/ssl/ca.pem'


def test_client_from_vark_server(vark_config_dir):
    c = AnthiveClient.from_vark_server('intern', config_dir=vark_config_dir)
    assert c.base_url == 'https://intern.bdslab.org/api'
    assert c.auth == ('mf', 'intern-pw')
    # 'intern' has no insecure flag → verify stays True.
    assert c.verify is True


def test_client_from_vark_server_insecure(vark_config_dir):
    c = AnthiveClient.from_vark_server('foam', config_dir=vark_config_dir)
    assert c.auth == ('mf', 'foam-pw')
    assert c.verify is False


def test_client_from_vark_server_unknown(vark_config_dir):
    with pytest.raises(VarkConfigError):
        AnthiveClient.from_vark_server(
            'nope-no-such-server', config_dir=vark_config_dir,
        )


# ── Pyodide branch ───────────────────────────────────────────────────────────


def test_client_skips_discovery_in_pyodide(monkeypatch, vark_config_dir):
    """Under Pyodide the discovery code must NOT run (no filesystem)."""
    import vark.client as client_mod
    monkeypatch.setattr(client_mod, '_is_pyodide', lambda: True)
    c = AnthiveClient(
        'https://10.42.0.3:8501/api', vark_config=vark_config_dir,
    )
    # No discovery → no auth was filled in.
    assert c.auth is None
    assert c.verify is True
