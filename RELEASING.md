# Releasing pyvark to PyPI

The package is published as **`pyvark`** on PyPI; users import it as **`vark`**.

## One-time setup

1. **PyPI account** — register at https://pypi.org/account/register/ (and ideally https://test.pypi.org/account/register/ for the staging registry).

2. **2FA** — PyPI now requires it for upload accounts; set it up under your account settings before issuing a token.

3. **API token** — at https://pypi.org/manage/account/token/ create a token. First release: scope **"Entire account"** (no project exists yet to scope to). After the first upload, revoke it and create a new one scoped to project **pyvark** only.

4. **Store the token** in `~/.pypirc`:

   ```ini
   [pypi]
   username = __token__
   password = pypi-AgEIcHlwa…   # the full token, including the 'pypi-' prefix

   [testpypi]
   repository = https://test.pypi.org/legacy/
   username = __token__
   password = pypi-AgENdGVzdC5w…  # a separate TestPyPI token
   ```

   Lock it down: `chmod 600 ~/.pypirc`.

## Git remotes and the KU Leuven GitLab mirror

Codeberg (`git@codeberg.org:mfiers/pyvark.git`) is the main repository.
`git@gitlab.kuleuven.be:bdslab/anthive/pyvark.git` mirrors it, the same
way anthive4 is mirrored. In the maintainer checkout `origin` fetches
from Codeberg and has two push URLs, Codeberg first and GitLab second,
so a plain `git push` updates both. `push.followTags` is on, so annotated
release tags go along. A separate `gitlab` remote is there for checks
(`git ls-remote gitlab`). To set up another clone the same way:

```bash
git remote set-url --add --push origin git@codeberg.org:mfiers/pyvark.git
git remote set-url --add --push origin git@gitlab.kuleuven.be:bdslab/anthive/pyvark.git
git remote add gitlab git@gitlab.kuleuven.be:bdslab/anthive/pyvark.git
git config push.followTags true
git remote set-head origin -d   # see the note below
```

Commits that reach Codeberg some other way (another clone, a pull
request merged on codeberg.org) only reach GitLab at the next push from
here. Catch up with:

```bash
git fetch origin && git push gitlab 'refs/remotes/origin/*:refs/heads/*' --follow-tags
```

GitLab refuses a branch called `HEAD` and then rejects the whole push,
so this glob only works without the local `refs/remotes/origin/HEAD`
symref. `git remote set-head origin -d` removes it; `git fetch` does not
bring it back.

## Release workflow

```bash
cd /tmp/pyvark   # or wherever your working clone lives

# 1. Make sure main is what you want to publish
git checkout main && git pull origin main
git status   # should be clean

# 2. Bump version in pyproject.toml (and tag in CHANGELOG.md if you keep one)
#    Edit pyproject.toml's `version = "X.Y.Z"`
#    Commit: git commit -am "bump version to X.Y.Z"

# 3. Tag the release
git tag -a vX.Y.Z -m "release X.Y.Z"
git push origin main --tags

# 4. Clean and build
rm -rf build/ dist/ pyvark.egg-info/
uv build       # or `python -m build` if you don't have uv

# 5. Sanity-check the artifacts
ls -la dist/                                          # wheel + sdist
unzip -l dist/pyvark-X.Y.Z-py3-none-any.whl           # wheel contents
tar -tzf dist/pyvark-X.Y.Z.tar.gz                     # sdist contents
unzip -p dist/pyvark-X.Y.Z-py3-none-any.whl \
        pyvark-X.Y.Z.dist-info/METADATA | head -40   # what PyPI will display

# 6. Upload to TestPyPI first (catches metadata bugs before they're permanent)
uvx twine upload --repository testpypi dist/*

# 7. Verify the test upload (the `python -c` runs INSIDE the uv-managed env;
#    `uv run -c …` does NOT work — `-c` is python's flag, not uv's)
uv run --quiet --index-url https://test.pypi.org/simple/ \
       --extra-index-url https://pypi.org/simple/ \
       --with pyvark==X.Y.Z --no-project --python 3.11 \
       python -c "from vark import AnthiveClient; print(AnthiveClient.API_TARGET)"

# 8. Upload to real PyPI
uvx twine upload dist/*

# 9. Verify from clean machine
uv run --quiet --with pyvark==X.Y.Z --no-project --python 3.11 \
       python -c "from vark import AnthiveClient; print(AnthiveClient.API_TARGET)"
```

## Versioning

- Major releases (X.0.0) — breaking API changes to `AnthiveClient`'s public surface.
- Minor (0.X.0) — new endpoints / new kwargs / new return fields without breaking existing code.
- Patch (0.0.X) — bug fixes, doc fixes, dependency bumps.

`API_TARGET` (the anthive REST API version this release was last verified against) is informational, not a hard requirement — pyvark continues to work against newer / slightly older anthive servers, it just may not surface their newest knobs.

## PyPI name vs import name

`pyproject.toml` declares two separate things:

```toml
[project]
name = "pyvark"          # the PyPI distribution name → `pip install pyvark`

[tool.setuptools]
packages = ["vark"]      # the Python package name → `from vark import ...`
```

This is intentional — the Go `vark` CLI also lives at `codeberg.org/mfiers/vark`, so disambiguating on PyPI by prefixing `py` avoids cross-tooling confusion. Once installed, the Python idiom (`from vark import ...`) wins.

## Common pitfalls

- **README image paths must be absolute URLs** for PyPI to render them. The logo at the top of `README.md` uses `https://codeberg.org/mfiers/pyvark/raw/branch/main/doc/logo.png` so it renders on both Codeberg and PyPI.
- **PyPI does not allow re-uploading the same version.** If you push 0.1.0 and notice a bug, bump to 0.1.1 — don't try to overwrite.
- **`twine check dist/*`** catches the most common metadata errors before upload. Run it if you're nervous.
- The wheel's `top_level.txt` should contain `vark` (verified during build); if it ever drifts to `pyvark`, `from vark import …` breaks. Worth checking `unzip -p dist/*.whl pyvark-*.dist-info/top_level.txt` after build.
