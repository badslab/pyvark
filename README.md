<p align="center"><img src="https://codeberg.org/mfiers/pyvark/raw/branch/main/doc/logo.png" alt="pyvark" width="200"></p>

# pyvark

Python client for the [Anthive](https://codeberg.org/mfiers/anthive4)
single-cell RNA-seq REST API. Sibling of the Go [`vark`](https://codeberg.org/mfiers/vark)
CLI — same backend, two front ends.

API surface verified against **anthive REST API 2.30.0** (2026-07-02).

## Why the dual name?

The Go CLI ships as a binary called `vark`. To avoid clobbering it on
the user's `$PATH` and to keep the PyPI / Codeberg slug obvious, the
**distribution name** is `pyvark` but the **importable name** is `vark`.

```sh
pip install pyvark                                    # distribution
python -c "from vark import AnthiveClient; print('ok')"   # usage
```

(Both CLI and library live next to each other in the same Anthive setup
with no shell collision: `vark` = the Go binary, `vark` = the Python
import.)

## Install

From Codeberg (no PyPI publish yet):

```sh
pip install git+ssh://git@codeberg.org/mfiers/pyvark.git
```

Editable from a local checkout:

```sh
git clone ssh://git@codeberg.org/mfiers/pyvark.git
cd pyvark
pip install -e .
# with pandas for `format='dataframe'` support:
pip install -e ".[pandas]"
```

Pyodide / JupyterLite:

```python
import micropip
await micropip.install("pyvark")
from vark import AnthiveClient
client = AnthiveClient()   # auto-detects {origin}/api/ in the browser
```

## Minimal example

```python
from vark import AnthiveClient

client = AnthiveClient(
    "https://my.anthive.example/api",
    auth=("user", "password"),
)

# What's on this server?
print(client.get_version()["version"])
databases = client.get_databases()
print(f"{len(databases)} datasets available")

# Pick a dataset and show its metadata fields
info = client.get_database_info(databases[0]["id"])
print(info["title"], info["n_cells"], "cells")

# Render a UMAP scatter server-side and write the PNG
plot = client.get_plot(
    info["id"], "scatter",
    color="cell_type",
    palette_categorical="tab20",
    width=6, height=5, dpi=150,
)
open("umap.png", "wb").write(plot["bytes"])

# The X-Plot-Caption header carries anthive's prose figure legend —
# this is the ONLY place the multi-sentence caption exists.
print(plot["caption"])
```

## Reusing vark CLI credentials

Anthive credentials are stored **once** by the Go [`vark`](https://codeberg.org/mfiers/vark)
CLI — username + password are encrypted at rest with [age](https://age-encryption.org)
(modern X25519 + ChaCha20-Poly1305) into `~/.config/vark/secrets.age`.
`pyvark` reads from that same store, so a notebook or script never
needs a password literal, an environment variable, or a `getpass()`
prompt.

### One-time setup (Go CLI side)

Install the Go [`vark`](https://codeberg.org/mfiers/vark) binary, then
register your server:

```sh
vark server login --name myserver \
                  --url https://my.anthive.example/api \
                  --user me
# → prompts for the password; encrypts it into ~/.config/vark/secrets.age
vark server ls          # confirm the entry is there
```

That writes two files:

- `~/.config/vark/config.yaml` — the server registry (name, URL, user,
  `insecure:` flag).
- `~/.config/vark/secrets.age` — age-encrypted password store.

### Install the pyvark extras

```sh
pip install "pyvark[vark-config]"   # adds pyrage (age) + PyYAML
```

The base install of `pyvark` is unchanged; the extras are only needed
for credential discovery.

### Use it from Python

**Auto-discover by URL** — no `auth=` argument, no password in code:

```python
from vark import AnthiveClient

client = AnthiveClient("https://my.anthive.example/api")
# pyvark matches the URL against `vark server ls`, pulls
# (user, password) from secrets.age, and (if insecure: true is set
# on the entry) demotes `verify` to False automatically.
```

**Look up by registered name** — handy when you don't want a URL
hard-coded in the notebook:

```python
client = AnthiveClient.from_vark_server("myserver")
```

### The `vark_config=` constructor knob

| Value         | Behaviour                                                          |
| ------------- | ------------------------------------------------------------------ |
| `None`        | **Default.** Auto-discover; silently no-op if the config dir or extras are missing. |
| `True`        | **Require.** Raise `VarkConfigError` if no entry matches the URL.  |
| `False`       | **Skip.** Never read `~/.config/vark/`, even if it exists.         |
| `str` / `Path`| Use that directory instead of `~/.config/vark/` (useful for tests / portable setups). |

Explicit `auth=(user, password)` always wins — vark-config discovery
never overrides a caller-supplied auth. Pyodide / JupyterLite skip
discovery automatically (no filesystem in the browser).

### Troubleshooting

- **`401 Unauthorized` on the first request.** Did you actually run
  `vark server login` for this server? A fresh `vark` install lays
  down a placeholder `secrets.age` that decrypts cleanly but contains
  no real password — the server then 401s. Re-run `vark server login`
  to overwrite it.
- **`NoSuchEntryError` (or "no matching server entry").** The URL
  passed to `AnthiveClient()` doesn't match any entry in
  `vark server ls`. URLs are normalised (trailing slash stripped, host
  case-folded) before matching, so it's almost always a typo or a
  missing `/api` suffix — compare `vark server ls` output against
  your constructor argument character-for-character.
- **`ImportError: pyrage` or `ImportError: yaml`.** You installed the
  base `pyvark` without the extras. Fix:
  `pip install "pyvark[vark-config]"`.

## API coverage (highlights)

* `get_root`, `get_health`, `get_metrics`, `get_version`,
  `get_changelog` — version + latency telemetry (`/health` exposes
  `mean_response_ms` / `p50_response_ms` / `n_samples`).
* `get_databases`, `get_database_info`, `get_group(group_id)` —
  catalog + per-collection landing-page data (API 2.5+).
* `get_plot(db_id, geom, ...)` — every server-side geom: `scatter`,
  `hexbin`, `kde2d`, `violin`, `box`, `bar`, `histogram`, `ecdf`,
  `kde`, `heatmap`, `rolling`, `volcano`, `ma`, `forest`, `de_heatmap`.
  Captures the `X-Plot-Caption` response header (the multi-sentence
  figure legend — API 2.7.2+). Supports `color_scale=auto|sequential|
  divergent`, plot clamps (`log2fc_clip`, `neglog10p_clip`,
  `logmean_clip`), bar `group_by`, hexbin auto-clip
  (`vmin_quantile` / `vmax_quantile`), per-axis transforms
  (`transform_x` / `transform_y`, `asinh_scale`), KDE knobs
  (`kde_n`, `kde_bw`, `n_levels`, `iso_overlay`, `point_overlay`),
  marginals / regline overlays. Data export via `format="csv"` /
  `"tsv"` returns the dataframe the plot was built from (API 2.6+).
* `list_de_studies`, `get_de_study`, `list_de_contrasts`,
  `get_de_rows`, `get_de_by_gene` — DE data flow (API 2.3+).
* `analytics_schema`, `analytics_query`, `analytics_viz` —
  SELECT-only SQL sandbox + Parquet-backed visualisation.
* `module_score`, `list_module_scores` — on-the-fly and pre-computed
  module scores.
* `list_genesets`, `get_geneset`, `rescan_genesets`.
* `list_catalogs`, `get_catalog`, `get_catalog_module`,
  `get_catalog_score`, `rescan_catalogs` — unified module-catalog
  view over starCAT (weighted programs, one-segment id like
  `MICROGLIA_V1_0`) + genesets (plain gene lists, two-segment id
  like `Sierksma2025/WGCNA`). Score recipes let you reproduce
  binary `*_pos` calls client-side (API 2.30+).
* `pick_fastest(base_urls, ...)` — server-selection helper that
  consumes `/health` latency telemetry.

## Module catalogs (starCAT + genesets)

Anthive REST API 2.30 unifies starCAT programs and genesets behind a
single `/catalogs` view. Both sources answer to the same route
templates, so a client can walk every module catalog without
branching by kind:

```python
from vark import AnthiveClient
client = AnthiveClient("https://my.anthive.example/api")

# 1. Discover every catalog (or filter by source).
inventory = client.list_catalogs(source="starcat")
for cat in inventory["catalogs"]:
    print(cat["source"], cat["catalog_id"], cat.get("n_modules"))

# 2. Drill into one catalog — module + score summaries.
#    catalog_id is one segment for starcat, two for geneset.
starcat = client.get_catalog("starcat", "MICROGLIA_V1_0")
print(len(starcat["modules"]), "modules")
print(len(starcat["scores"]),  "derived scores")

geneset = client.get_catalog("geneset", "Sierksma2025/WGCNA")

# 3. Fetch one module's gene weights (starcat) or list (geneset).
mod = client.get_catalog_module(
    "starcat", "MICROGLIA_V1_0", "Microglia_Border_CAM", top=20,
)
for row in mod["top_genes"]:
    print(f"{row['rank']:2}  {row['gene']:10}  {row['weight']:+.4f}")

# 4. Fetch a derived-score recipe — enough to reproduce it
#    client-side. Binary `*_pos` calls are just
#    `usage[column] > threshold` on normalised usage.
recipe = client.get_catalog_score(
    "starcat", "MICROGLIA_V1_0", "Border_CAM_pos",
)
# {"name": "Border_CAM_pos", "kind": "discrete",
#  "columns": ["Microglia_Border_CAM"], "threshold": 0.0448, ...}
```

`client.rescan_catalogs()` forces a server-side reload after you
drop a new starCAT TSV or geneset YAML onto the store.

## Recipe — module-score vs gene on the XY plot (API 2.29+)

REST API 2.29 lifted the restriction that made `attach_sessions`
columns unusable as `x` / `y` on the XY plot endpoints (they
worked as `color=` already). That unlocks the "score-vs-gene"
figure — compute a module score on the fly, then plot it against a
single gene's expression:

```python
from vark import AnthiveClient
client = AnthiveClient("https://my.anthive.example/api")
db_id = "Sierksma2025/microglia"

# Compute a Seurat-style module score for a small gene list and
# capture the session id the server hands back.
score = client.module_score(
    db_id,
    genes=["APOE", "TREM2", "CD9", "SPP1"],
    name="DAM_score",
)
session_col = score["column"]   # e.g. "session_1::DAM_score"

# Now use the score as X on an XY scatter, gene expression as Y.
# Pre-2.29 servers reject this with 400; 2.29+ returns a plot.
plot = client.get_plot(
    db_id, "scatter",
    x=session_col, y="SPP1",
    color="cell_type",
    marginals="hist", regline=True,
    width=6, height=5, dpi=150,
)
open("dam_vs_spp1.png", "wb").write(plot["bytes"])
print(plot["caption"])
```

`session_col` is dataset-scoped and lives only inside this client's
plot-request context — the server re-materialises it from the
Parquet sidecar keyed on `session_id`. Nothing is written back to
the duckdb.

## Tests

```sh
# Offline (no server needed):
uv run --with pytest --with requests python -m pytest tests/test_offline.py -v

# Live smoke (round-trip):
ANTHIVE_TEST_URL=https://my.anthive/api \
ANTHIVE_TEST_USER=user ANTHIVE_TEST_PASSWORD=pass \
uv run --with pytest --with requests --with pandas \
    python -m pytest tests/test_smoke.py -v
```

## Versioning

`pyvark` starts at **0.1.0** as a clean break from the legacy
`antclient` 1.x history that previously lived under
`anthive4/antclient/`. The Anthive REST API uses its own semver
(`X.Y.Z`) — see `client.AnthiveClient.API_TARGET` for the version this
release was last verified against.

## License

MIT — see `LICENSE`.
