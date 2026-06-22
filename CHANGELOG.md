# pyvark — Changelog

Versioned record of the Python client. The targeted REST API version is
recorded in `vark.AnthiveClient.API_TARGET`.

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
