# pyvark — Changelog

Versioned record of the Python client. The targeted REST API version is
recorded in `vark.AnthiveClient.API_TARGET`.

## 0.4.0 — 2026-08-08

### Added — REST API 2.34 / 2.35 / 2.36 `bin_color`

- **`AnthiveClient.get_plot(..., bin_color=N, bin_color_method='quantile')`**
  — bin a continuous `color` field (numerical obs or gene) into
  ``N`` categorical groups server-side before plotting.
  `bin_color` is an int in ``2..20``; `bin_color_method` is
  ``'quantile'`` (default, equal-count) or ``'width'`` (equal-width).
  Wired on **scatter, hexbin** (2.34), **rolling** (2.34),
  **kde2d** (2.35), **histogram, ecdf, kde** (2.36) — seven geoms.
  On scatter/hexbin the param is optional; on rolling/kde2d/
  histogram/ecdf/kde a continuous `color` **requires** `bin_color`
  (server returns 400 otherwise).

### Fixed

- **`PLOT_GEOMS` gains `de_quadrant`** (REST API 2.12) — previously
  missing, so `get_plot(..., 'de_quadrant', …)` raised a client-side
  ``ValueError`` before the request ever left the machine. Also add
  it to the offline PLOT_GEOMS test.

### Changed

- **`AnthiveClient.API_TARGET`** bumped from ``"2.30.0"`` to
  ``"2.36.0"`` — the version this release was last verified against.

## 0.3.0 — 2026-07-06

### Added — REST API 2.30 catalog family

- **`AnthiveClient.list_catalogs(source=None)`** — `GET /catalogs`.
  Cross-source discovery of every module catalog on the server
  (`source='geneset'` and `source='starcat'`). Optional filter by
  source.
- **`AnthiveClient.get_catalog(source, catalog_id)`** —
  `GET /catalogs/{source}/{catalog_id}`. One catalog + its module
  summaries + score recipes + metadata. `catalog_id` is path-style —
  `"MICROGLIA_V1_0"` for starcat (one segment) or
  `"Sierksma2025/WGCNA"` for geneset (two segments); both work on the
  same route.
- **`AnthiveClient.get_catalog_module(source, catalog_id, module_name,
  top=None)`** — `GET /catalogs/{source}/{catalog_id}/modules/{name}`.
  One module's gene list ± weights. starcat modules carry a
  `{gene: weight}` dict + ranked `top_genes`; genesets carry a plain
  gene list. `top=N` clamps to top-N by `|weight|` (starcat) or
  first-N (geneset).
- **`AnthiveClient.get_catalog_score(source, catalog_id, score_name)`**
  — `GET /catalogs/{source}/{catalog_id}/scores/{name}`. Returns the
  derived-score recipe (composite / discrete-threshold /
  multinomial) — enough to reproduce the score client-side and to
  explain what a binary `*_pos` sidecar column actually thresholds.
- **`AnthiveClient.rescan_catalogs()`** — `POST /catalogs/rescan`.
  Invalidate the server-side catalog cache; returns the freshly
  reloaded registry.

### Notes — REST API 2.29 (no client change required)

- `attach_sessions` columns are now usable as `x` / `y` on the XY
  plot endpoints (previously the server 400'd). Existing `get_plot`
  calls that were rejected — session-vs-gene, session-vs-obsnum,
  session-vs-session — start returning 200 with no client-side
  change. See the new `README.md` recipe for a "module score vs
  gene" figure built on top of this.

### Changed

- **`AnthiveClient.API_TARGET`** bumped from `"2.7.2"` to `"2.30.0"`
  — the version this release was last verified against. This is a
  documentation string, not a runtime gate, so older servers keep
  working (endpoints they don't expose just 404).

### Docs

- Expanded the **"Reusing vark CLI credentials"** README section into a
  definitive reference: explicit WHY (age-encrypted store, no password
  literals in notebooks), one-time Go-CLI setup walkthrough
  (`vark server login`), a `vark_config=` mode table, and a
  troubleshooting block (401 from a fresh-install placeholder
  `secrets.age`, `NoSuchEntryError` URL-mismatch, missing
  `[vark-config]` extras). The section is the anchor target of
  auto-generated anthive notebooks
  (`https://codeberg.org/mfiers/pyvark#reusing-vark-cli-credentials`).
- New README section **"Module catalogs (starcat + genesets)"** with
  a walkthrough of the 2.30 catalog family (list → catalog →
  module → score recipe) plus a **"Score vs gene"** recipe that
  exercises the 2.29 XY plot fix (`module_score(...)` →
  `session_id` → `get_plot(..., x=<session>, y='SPP1')`).

## 0.2.0 — 2026-06-22

### Added

- **Reuse Go vark CLI credentials.** When `AnthiveClient(base_url)` is
  called without `auth=`, the client now looks up `~/.config/vark/`
  (the Go [`vark`](https://codeberg.org/mfiers/vark) CLI's local
  config + age-encrypted secrets store) and auto-wires the matching
  server's basic-auth credentials. The new constructor kwarg
  `vark_config=` controls this:
  - `None` (default) — auto, silent fallback.
  - `True` — required (raise `VarkConfigError` on miss).
  - `False` — skip entirely.
  - `str | Path` — use a custom config dir.
- **`AnthiveClient.from_vark_server('name')`** classmethod — build a
  client from a named entry in the Go CLI's `config.yaml`.
- **`vark.VarkConfigError`** — new exception type, raised when
  discovery is required but cannot succeed.
- **`insecure: true` propagates** as `verify=False` (unless the caller
  passed `verify=` explicitly).

### Packaging

- New optional-dependencies group **`vark-config`** —
  `pip install pyvark[vark-config]` adds `pyrage` (age decryption) +
  `PyYAML` (config.yaml). The base install is unchanged; auto-discovery
  silently no-ops when the extras aren't installed.

### Notes

- Pyodide / JupyterLite skip credential discovery automatically
  (there's no `~/.config/vark/` in the browser).
- Explicit `auth=` always wins — vark-config discovery never overrides
  a caller-supplied auth.

## 0.1.0 — 2026-06-22

Initial release. Clean break from the legacy `antclient` 1.x history
(previously at `anthive4/antclient/`).

### Coverage — REST API 2.7.2

- **Plot endpoints**: per-geom URLs for every geom on the server —
  `scatter`, `hexbin`, `kde2d`, `violin`, `box`, `bar`, `histogram`,
  `ecdf`, `kde`, `heatmap`, `rolling`, `volcano`, `ma`, `forest`,
  `de_heatmap`.
- **Caption capture**: `get_plot()` reads the `X-Plot-Caption`
  response header and surfaces it as `result['caption']`. This is the
  only place anthive emits the multi-sentence figure legend (matches
  the Go vark v0.0.10 contract).
- **Plot clamps (API 2.7+)**: `log2fc_clip`, `neglog10p_clip`,
  `logmean_clip` — symmetric / upper-bound axis clamps for volcano /
  ma plots (visible in caption as well).
- **`color_scale`** — first-class top-level kwarg on `get_plot()`;
  forces `auto` | `sequential` | `divergent`.
- **`de_heatmap` (API 2.7)**: full contrasts × genes/modules matrix
  with `study`, `term`, `contrasts`, `genes`, `value`, `sig_overlay`,
  `padj_threshold`.
- **Bar `group_by` (API 2.6)**: in-plot clustering of x-bars.
- **Bar composition**: `bar_mode='stack'`, `normalize=True`, `facet`.
- **CSV / TSV plot-data export (API 2.6)**: `format='csv'` / `'tsv'`
  returns the dataframe the figure was built from.
- **kde2d controls (API 2.4)**: `kde_n`, `kde_bw`, `n_levels`,
  `iso_overlay`, `point_overlay`, `marginals`, `regline`.
- **Per-axis transforms**: `transform_x`, `transform_y`, `asinh_scale`
  on scatter / hexbin / kde2d (with the legacy `log_x` / `log_y`
  booleans still accepted as `log1p` aliases).
- **Hexbin auto-clip**: `vmin_quantile`, `vmax_quantile` — colorbar
  shows `extend='both'` arrows server-side when clipping fires.
- **`/groups/{group_id}` (API 2.5)**: new `get_group()` for the
  collection landing-page data (prose body, citation, accession,
  dataset list).
- **DE flow (API 2.3)**: `list_de_studies`, `get_de_study`,
  `list_de_contrasts`, `get_de_rows`, `get_de_by_gene`.
- **Analytics sandbox**: `analytics_schema`, `analytics_query`,
  `analytics_viz`.
- **Module scores**: `module_score` (on-the-fly), `list_module_scores`
  (pre-computed).
- **Genesets**: `list_genesets`, `get_geneset`, `rescan_genesets`.
- **Server selection**: `AnthiveClient.pick_fastest()` — consumes
  `/health` `p50_response_ms` / `mean_response_ms` / `n_samples`.

### Packaging

- Distribution name `pyvark` on Codeberg
  (`codeberg.org/mfiers/pyvark`); importable as `from vark import …`.
- License: MIT.
- `verify=` constructor arg for self-signed TLS endpoints (forwarded
  to `requests`).
