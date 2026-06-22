# pyvark

Python client for the [Anthive](https://codeberg.org/mfiers/anthive4)
single-cell RNA-seq REST API. Sibling of the Go [`vark`](https://codeberg.org/mfiers/vark)
CLI — same backend, two front ends.

API surface verified against **anthive REST API 2.7.2** (2026-06-20).

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
* `pick_fastest(base_urls, ...)` — server-selection helper that
  consumes `/health` latency telemetry.

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
