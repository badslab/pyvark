<p align="center"><img src="https://codeberg.org/mfiers/pyvark/raw/branch/main/doc/logo.png" alt="pyvark" width="200"></p>

# pyvark

Python client for the [Anthive](https://codeberg.org/mfiers/anthive4)
single-cell RNA-seq REST API. Sibling of the Go [`vark`](https://codeberg.org/mfiers/vark)
CLI — same backend, two front ends.

API surface verified against **anthive REST API 2.41.0** (2026-10-03).

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

From PyPI:

```sh
pip install pyvark          # or: uv add pyvark
```

Version pin (semver-safe):

```sh
pip install "pyvark>=0.7.0,<0.8"
```

Editable from a local checkout (development):

```sh
git clone ssh://git@codeberg.org/mfiers/pyvark.git
cd pyvark
uv pip install -e .
# with pandas for `format='dataframe'` support:
uv pip install -e ".[pandas]"
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
import os
from vark import AnthiveClient

client = AnthiveClient(
    "https://my.anthive.example/api",
    auth=(os.environ["ANTHIVE_USER"], os.environ["ANTHIVE_PASSWORD"]),
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

## Credentials

Never put a password in a notebook or script. The client finds
credentials in this order:

1. `auth=` passed to the constructor, usually `(user, password)` read
   from somewhere safe (`getpass.getpass()`, a secrets manager, the
   environment). Any `requests.auth.AuthBase` also works.
2. The `ANTHIVE_USER` and `ANTHIVE_PASSWORD` environment variables.
3. The Go vark CLI's encrypted store (next section).
4. `~/.netrc`, which `requests` reads by itself when nothing else gave
   credentials:

   ```
   machine my.anthive.example
   login me
   password ...
   ```

   Keep it private with `chmod 600 ~/.netrc`.

```sh
export ANTHIVE_USER=me
read -rs ANTHIVE_PASSWORD && export ANTHIVE_PASSWORD   # not in shell history
python -c "from vark import AnthiveClient; print(AnthiveClient('https://my.anthive.example/api').get_version()['version'])"
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
  catalog + per-collection landing-page data (API 2.5+). Rows carry the
  lineage fields `designation`, `reanalysis_of`, `donor_group` and
  `has_donor_uid` on current servers.
* `get_donor_groups`: datasets that share a donor pool (do not count
  them as independent donors).
* `get_plot(db_id, geom, ...)` — every server-side geom: `scatter`,
  `hexbin`, `kde2d`, `violin`, `box`, `bar`, `histogram`, `ecdf`,
  `kde`, `heatmap`, `rolling`, `volcano`, `ma`, `forest`, `de_heatmap`,
  `de_quadrant`.
  Captures the `X-Plot-Caption` response header (the multi-sentence
  figure legend — API 2.7.2+). Supports `color_scale=auto|sequential|
  divergent`, plot clamps (`log2fc_clip`, `neglog10p_clip`,
  `logmean_clip`), bar `group_by`, hexbin auto-clip
  (`vmin_quantile` / `vmax_quantile`), per-axis transforms
  (`transform_x` / `transform_y`, `asinh_scale`), KDE knobs
  (`kde_n`, `kde_bw`, `n_levels`, `iso_overlay`, `point_overlay`),
  marginals / regline overlays, and on-the-fly binning of a
  continuous `color` field via `bin_color=N` (2..20) +
  `bin_color_method='quantile'|'width'` — wired on scatter, hexbin,
  rolling (API 2.34+), kde2d (2.35+), histogram / ecdf / kde (2.36+).
  Data export via `format="csv"` /
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
* `list_facets` (`full=True` for `facets_visible` and
  `definitions_status`), `get_facet` (definition, per-dataset mapping,
  `exclude_secondary`), `get_database_facets`,
  `get_gene_variance_by_facet`,
  `get_module_variability` (both per-cell and descriptive, not
  donor-level evidence), `list_geneset_studies`,
  `get_genesets_by_gene`, `get_obs_summary`, `get_obs_top`,
  `get_mus_vocab`.
* `get_databases` rows and `get_database_info` carry `replicate_unit`,
  `replicate_column`, `replicate_basis` and `disease_basis` (DataFrame
  columns with `format='dataframe'`).
* The APOE facet is `apoe4_carrier` (column `ant_apoe4_carrier`); the
  server accepts `apoe_carrier` as a deprecated alias for one release.
  `AnthiveClient.TESTED_FACETS` lists the nine facets with donor-level
  results, `FACET_SCOPES` the facet scopes, `DEPRECATED_FACETS` the
  deprecated facets and what replaces them.
* Facet scopes (API 2.44.0): `get_facet`, the facet test views and
  `get_module_variability` take `scope=` (`human_postmortem`,
  `xenograft_human_in_mouse`, `in_vitro`). Human and mouse never mix.
* Donor-level facet tests (exploratory): `get_facet_tests`,
  `get_facet_test_genes`, `get_facet_test_modules`,
  `get_facet_test_volcano`, `get_facet_tests_across_datasets`,
  `get_facet_gene_effects`, `get_facet_recurring_genes`,
  `get_gene_facet_effects`, `get_facet_cohorts`. See below.
* `exclude_secondary` (default `True`) on `get_gene_stats_all`,
  `get_module_variability`, `get_facet` and the facet test views keeps
  reanalyses out of pooled numbers.
* `list_database_files`, `download_database_file` (the `.h5ad`),
  `download_static_file` (a collection's `static/` files).
* Paper library (API 2.39+): `list_papers`, `get_paper`,
  `get_related_papers`, `get_paper_page`, `get_paper_bibtex`,
  `get_library_bibtex`, `download_paper_pdf`, `search_literature`,
  `get_database_papers`, `get_database_context`, `get_library_status`.
* Paper upload (API 2.40+, uploaders only): `get_paper_upload_requirements`,
  `upload_paper`, `upload_papers`, `paper_items_from_folder`.
* `pick_fastest(base_urls, ...)` — server-selection helper that
  consumes `/health` latency telemetry.

## Paper library

Every anthive site can hold a library of papers and other documents
(articles, preprints, theses, reports, proposals). Each record is
BibLaTeX-compatible and can be linked to datasets with a role
(`source`, `reanalysis`, `method`, `related`, `background`). Everyone
who can sign in to the site sees the whole library, and its text may be
passed on to AI clients.

```python
from vark import AnthiveClient
client = AnthiveClient("https://my.anthive.example/api")   # credentials as above

# Browse and filter (all filters optional, they combine).
for paper in client.list_papers(disease="Alzheimer disease", year="2020..2026"):
    print(paper["citekey"], paper.get("title"))

paper = client.get_paper("sankowski2019mapping")       # record, notes, datasets
related = client.get_related_papers("sankowski2019mapping", kind=["cohort", "author"])

# Which papers belong to a dataset, and a background pack for an LLM.
papers = client.get_database_papers("S19/SMI")
context = client.get_database_context("S19/SMI", level="brief", budget_tokens=4000)

# Passages from the full text (needs the server's literature index).
hits = client.search_literature("TREM2 microglia", k=5, section="results")
for hit in hits["results"]:
    print(hit)

# BibTeX and PDFs.
open("library.bib", "w").write(client.get_library_bibtex())
open("one.bib", "w").write(client.get_paper_bibtex("sankowski2019mapping"))
client.download_paper_pdf("sankowski2019mapping", dest=".")   # saved under the server's name
pdf_bytes = client.download_paper_pdf("sankowski2019mapping")  # or keep it in memory
```

### Uploading papers

Only members of the site's `library_upload_groups` (by default the
admins) may upload, or even see the upload requirements. Everyone else
gets `PaperUploadForbiddenError` (HTTP 403). On a site whose library is
read-only, uploads raise `PaperUploadDisabledError` (HTTP 503) and
nothing is written.

```python
from vark import (AnthiveClient, PaperDuplicateError, PaperInvalidError,
                  PaperUploadDisabledError, PaperUploadForbiddenError)

client = AnthiveClient("https://my.anthive.example/api")

requirements = client.get_paper_upload_requirements()
print(requirements["required"], requirements["default_role"])   # background

record = {
    "entrytype": "article",
    "title": "Mapping microglia states in the human brain",
    "author": ["Sankowski, Roman", "Prinz, Marco"],
    "date": "2019-11-18",
    "doi": "10.1038/s41593-019-0532-y",
}
try:
    result = client.upload_paper(
        record, "sankowski2019.pdf",
        role="source",                    # anthive_role; default background
        papers_for={"S19/SMI": "source"}, # proposed dataset link for a curator
        dry_run=True,                     # validate + enrich, write nothing
    )
    print(result["status"], result["citekey"], result["missing_recommended"])
except PaperDuplicateError as exc:
    print("already there as", exc.existing_citekey, "matched on", exc.matched_on)
except PaperInvalidError as exc:
    print("invalid:", exc.errors, exc.missing_required)
except PaperUploadForbiddenError:
    print("this account may not add papers")
except PaperUploadDisabledError:
    print("uploads are switched off on this site")
```

`metadata` can also be the text of a `.md` record with YAML front matter
or a `pathlib.Path` to one. `update=True` merges into an existing record
instead of raising `PaperDuplicateError`. Set `role="source"` or
`"reanalysis"` only when the data in anthive come from the paper.

Documents other than articles work the same way. A report, thesis,
unpublished manuscript or misc record needs `institution` or `note`
instead of a DOI:

```python
client.upload_paper({
    "entrytype": "report", "type": "project proposal",
    "title": "Microglia states in ageing", "author": ["Doe, Jane"],
    "year": 2026, "institution": "KU Leuven",
}, "proposal.pdf")
```

Bulk upload is a loop on the client (the server takes one paper per
request). Point it at a folder of `name.md` records with sibling
`name.pdf` files:

```python
items = client.paper_items_from_folder("to_upload/")
outcomes = client.upload_papers(items, dry_run=True)
for outcome in outcomes:
    print(outcome["index"], outcome["ok"], outcome["status"], outcome.get("citekey"))
```

`upload_papers` records duplicates and invalid records and goes on
(`stop_on_error=True` re-raises the first one). A 403 or 503 stops the
whole run at once, since no later paper could succeed either.

## Donor-level facet tests

The server serves the output of anthive's donor-level facet tests: for
each dataset and cell type, raw counts are summed per donor and genes
are tested with limma-voom against sex (m vs f), disease (AD vs
control), APOE e4 carrier status and dose, Braak stage (trend per
stage, and early versus late), age (per decade, with and without the
pathology term in the model) and, in xenograft hosts, App-NL-G-F
versus control, with module scores tested by OLS plus label
permutations. Everything is counted per facet scope: human post-mortem
and xenograft results are never combined (`scope=`).

Read these results with their limits in mind. They are **exploratory**.
The unit of analysis is the **donor**, so n is the number of donors, not
cells. Each (dataset, cell type) unit is tested on its own; nothing is
pooled and there is no meta-analysis, and datasets share donors. The
**disease** contrast is **provisional**: "control" means different
things between studies and the vocabulary is not settled.
`AnthiveClient.FACET_TESTS_CAVEATS` holds the same text.

```python
from vark import AnthiveClient
client = AnthiveClient("https://my.anthive/api")

# One dataset: one unit per (facet, cell type), with flags and the model.
summary = client.get_facet_tests("G24/MMG")
for unit in summary["units"]:
    if unit["tested"]:
        print(unit["facet"], unit["cell_type"], unit["level_counts"],
              unit["flags"]["descriptive_only"],
              unit["model"]["genes"]["formula"])

# Gene rows of one unit (q is BH within the unit); CSV or a DataFrame.
genes = client.get_facet_test_genes("G24/MMG", facet="sex",
                                    cell_type="microglial cell", limit=20)
frame = client.get_facet_test_genes("G24/MMG", facet="braak", q=1,
                                    limit=2000, format="dataframe")
png = client.get_facet_test_volcano("G24/MMG", "sex", "microglial cell")

# One gene across every tested dataset, with the replication count.
card = client.get_facet_gene_effects("sex", "XIST", cell_type="microglia")
for entry in card["replication"]:
    print(entry["celltype_group"], entry["badge"])
for unit in card["units"]:
    print(unit["db_id"], unit["logFC"], unit["q_value"],
          unit["counted"], unit["not_counted_reason"])

# Genes that change in the most independent cohorts.
top = client.get_facet_recurring_genes("sex", cell_type="microglia", n=20)
print(top["ranking"])
for row in top["rows"]:
    print(row["gene"], row["cohorts_sig_same_sign"], "of",
          row["cohorts_tested"], row["agreement"], row["direction"])

# Facet scopes: one answer per scope; without scope, by_scope has all.
cards = client.get_gene_facet_effects("TREM2")
print(cards["strongest_facet"], list(cards["by_scope"]))
xeno = client.get_facet_recurring_genes(
    "app_nlgf", scope="xenograft_human_in_mouse")

# Which datasets share donors, and the DRAFT cohort table.
groups = client.get_donor_groups()
cohorts = client.get_facet_cohorts()
```

How to read the fields:

* `descriptive_only`: the unit has no usable p values (cell-level or
  below the replicate floor). p, q, t and the CI are null; only the
  effect estimate is given.
* `counted`: the unit counts towards replication. `not_counted_reason`
  says why not (secondary dataset, descriptive only, dataset not in the
  cohort table, cohort role not counted, unmapped cell type, or another
  unit of the same dataset and cell type group has a more direct cell
  type source).
* `replicated` is a partial-conjunction call: `r_value < 0.05` means the
  effect is present in at least 2 independent cohorts, same direction
  (Benjamini and Heller; Simes combination of the one-sided limma p
  values of one anchor unit per cohort). It says the direction
  reproduces, not that the effect is large. `effect_gate_passed` adds
  the size (at least 2 cohorts with a log2 fold change of at least
  `effect_gate_tau`, a 10 percent change); `replicated_effect` is the
  stricter tier (`r_treat < 0.05`, tested against that minimum effect;
  `replicated_strong` does the same at 25 percent). `k` of `m` is
  descriptive (cohorts individually at `q_value < 0.05` in the
  replicated direction; `k_treat` uses the treat q value).
* Small cohorts (a level with fewer than 5 replicates, numeric facets
  fewer than 10) are tested and counted but flagged `small_sample`;
  `n_small` counts them in a replication entry. Units with
  `analysis_level` `below_floor` (fewer than 4 replicates) or `cell`
  are descriptive only. `lambda_gc` above 1.3 (`inflated`) means the
  p values of that unit are too small. `get_facet_recurring_genes` lists
  replicated genes that pass the effect gate (`n_replicated`,
  `n_effect_gate`, `n_replicated_effect`, `n_genes_in_family`).
  A cohort is a row group of the DRAFT cohort table and counts
  once. Cell type labels are counted by group (`microglial cell`,
  `Microglia` and `Mic P2RY12` are all `microglia`, with `cl_id`
  `CL:0000129`). When several strata of one dataset fall into one group,
  their q is multiplied by `n_sibling_strata` (`q_counted`). The full
  rule is in the response's `definition`.
* `composition_flag`: the share of a donor's cells in the stratum
  differs with the facet, so an effect may reflect composition.
* `dataset_changed`: the dataset changed since the run; results may be
  stale.

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

`module_score` computes a Seurat-style score on the fly and answers
with summary statistics plus a `session_id`. The per-cell scores stay
on the server; attach the session to a plot and the column
`module_score` becomes a plottable field:

```python
from vark import AnthiveClient
client = AnthiveClient("https://my.anthive.example/api")
db_id = "S25/V6W"

score = client.module_score(db_id, genes=["APOE", "TREM2", "CD9", "SPP1"])
print(score["genes_found"], score["summary"]["median"])

plot = client.get_plot(
    db_id, "scatter",
    x="module_score", y="SPP1",
    attach_sessions=score["session_id"],
    color="cell_type",
    marginals="hist", regline=True,
    width=6, height=5, dpi=150,
)
open("dam_vs_spp1.png", "wb").write(plot["bytes"])
print(plot["caption"])

# The same session as a SQL table called `scores`.
by_type = client.analytics_query(
    db_id,
    "SELECT o.cell_type, AVG(s.module_score) AS mean_score "
    "FROM scores s JOIN obscat o USING (cell_name) GROUP BY 1",
    attach_sessions=score["session_id"],
)
```

With two attached sessions the second one's column is called
`session_1::module_score`. Sessions are temporary files on the server
and expire; nothing is written back to the dataset. The dataset needs a
`__gene_bins` table (built by `ant duckdb-check`), otherwise the server
answers 400.

## Tests

```sh
# Offline, mocked HTTP (no server needed):
uv run --with pytest --with requests --with pandas --no-project \
    python -m pytest tests/ -v

# Integration: start a throw-away ant-serve from an anthive4 tree on a
# free loopback port, with a temporary state dir, store and a COPY of a
# few library records (nothing is written outside pytest's tmp dir):
git -C /path/to/anthive4 archive main | tar -x -C /tmp/anthive4-main
ANTHIVE4_SOURCE=/tmp/anthive4-main \
ANTHIVE_IT_LIBRARY=/path/to/anthive4/data/library \
ANTHIVE_IT_CITEKEYS=sankowski2019mapping,ayhan2021resolving \
ANTHIVE_IT_COLLECTION=/path/to/h5adstore/Sankowski2019 \
ANTHIVE_IT_DATASET=S19/SMI \
uv run --with pytest --with requests --with pandas --no-project \
    python -m pytest tests/test_integration_server.py -v

# Integration, facets: the same throw-away server, but serving the REAL
# h5adstore read-only through a symlink mirror (caches land in the tmp
# dir; the test fails if any real store file changes):
ANTHIVE4_SOURCE=/tmp/anthive4-main \
ANTHIVE_IT_STORE=/path/to/h5adstore \
uv run --with pytest --with requests --with pandas --no-project \
    python -m pytest tests/test_integration_facets.py -v

# Live smoke (round-trip):
ANTHIVE_TEST_URL=https://my.anthive/api \
ANTHIVE_TEST_USER=me ANTHIVE_TEST_PASSWORD="$(pass show anthive)" \
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
