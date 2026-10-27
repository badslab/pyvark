<p align="center"><img src="https://gitlab.kuleuven.be/bdslab/anthive/pyvark/-/raw/main/doc/logo.png" alt="pyvark" width="200"></p>

# pyvark

pyvark is the Python client for [Anthive](https://gitlab.kuleuven.be/bdslab/anthive/anthive4),
a browser and REST API for curated single-cell, bulk and spatial
transcriptomics datasets (mostly human microglia), the papers behind
them and the analysis files made from them. With pyvark you list
datasets, read expression and cell metadata, render the server's plots,
run donor-level facet tests, search the paper library and download
versioned analysis artefacts, from a script, a notebook or JupyterLite.
It is the Python sibling of the Go [`vark`](https://codeberg.org/mfiers/vark)
command line client; both talk to the same API.

The package is called `pyvark` on PyPI and is imported as `vark`.

## Supported servers

| pyvark | anthive REST API |
| --- | --- |
| 0.12.x | 2.46 and newer; the artefact store and collection listing need 2.47.0+, `search` and `stats` 2.48.0+ |

`AnthiveClient.API_TARGET` names the API version a release was checked
against (0.12.1: 2.47.0, 0.12.2: 2.48.0). On an older server the methods it does not
have raise a clear error: artefact and collection calls on a 2.46
server raise `ServerTooOldError` ("needs anthive REST API 2.47.0+")
instead of a bare 404, and `search` and `stats` on a server before
2.48 raise it with "needs anthive REST API 2.48.0+".
`get_version()["compatible_pyvark"]` tells you
the oldest pyvark a server works with.

## Install

```sh
pip install pyvark                # or: uv add pyvark
pip install "pyvark[pandas]"      # format="dataframe" results
pip install "pyvark[vark-config]" # reuse the Go vark CLI's stored logins
```

Python 3.9 to 3.13. The only required dependency is `requests`.

In JupyterLite (Pyodide):

```python
import micropip
await micropip.install("pyvark")
from vark import AnthiveClient
client = AnthiveClient()   # uses {origin}/api/ of the page
```

## Quick start

```python
import getpass
from vark import AnthiveClient

client = AnthiveClient("https://my.anthive.example/api", auth=("me", getpass.getpass()))
print(client.get_version()["version"])                         # e.g. 2.47.0
datasets = client.get_databases(format="dataframe")             # one row per dataset
db_id = datasets["id"].iloc[0]                                  # e.g. "AL1/CBL"
stats = client.get_gene_stats(db_id, ["TREM2", "APOE"], format="dataframe")
plot = client.get_plot(db_id, "scatter", color="TREM2")         # UMAP coloured by TREM2
open("trem2_umap.png", "wb").write(plot["bytes"])               # plot["caption"]: the legend
client.download_artefact("AT6/_group/atlas-umap", "atlas-umap/")  # sha256-checked files
```

The last line needs a 2.47 server that holds that artefact; list what
exists with `client.list_artefacts()`.

## Authentication

Anthive sites run behind a login proxy, and the REST API under `/api`
takes your Anthive user name and password as HTTP basic auth on every
kind of site:

- **Authelia sites** (the default): people log in through a login page
  in the browser, while scripts, pyvark and vark send the same user
  name and password as HTTP basic auth on `/api`. There is no separate
  API password.
- **Basic-auth sites**: the same HTTP basic credentials as the browser
  popup.
- **Public mirrors** (`auth.mode: none`): no login; only public
  datasets are served. Leave `auth` out.

There are no REST API tokens. The personal MCP token (`amcp_...`, from
the site's MCP page) only works on `/mcp` for AI clients; it does not
open `/api`. Datasets that are not public are hidden from callers who
are not signed in: they are missing from listings and answer 404.

### Where the client finds credentials

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
CLI: user name and password are encrypted at rest with [age](https://age-encryption.org)
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

- `~/.config/vark/config.yaml`: the server registry (name, URL, user,
  `insecure:` flag).
- `~/.config/vark/secrets.age`: the age-encrypted password store.

### Install the pyvark extras

```sh
pip install "pyvark[vark-config]"   # adds pyrage (age) + PyYAML
```

The base install of `pyvark` is unchanged; the extras are only needed
for credential discovery.

### Use it from Python

**Auto-discover by URL**, with no `auth=` argument, no password in code:

```python
from vark import AnthiveClient

client = AnthiveClient("https://my.anthive.example/api")
# pyvark matches the URL against `vark server ls`, pulls
# (user, password) from secrets.age, and (if insecure: true is set
# on the entry) demotes `verify` to False automatically.
```

**Look up by registered name**, handy when you don't want a URL
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

Explicit `auth=(user, password)` always wins: vark-config discovery
never overrides a caller-supplied auth. Pyodide / JupyterLite skip
discovery automatically (no filesystem in the browser).

### Troubleshooting

- **`401 Unauthorized` on the first request.** Did you actually run
  `vark server login` for this server? A fresh `vark` install lays
  down a placeholder `secrets.age` that decrypts cleanly but contains
  no real password, and the server then answers 401. Re-run `vark server login`
  to overwrite it.
- **`NoSuchEntryError` (or "no matching server entry").** The URL
  passed to `AnthiveClient()` doesn't match any entry in
  `vark server ls`. URLs are normalised (trailing slash stripped, host
  case-folded) before matching, so it's almost always a typo or a
  missing `/api` suffix. Compare `vark server ls` output against
  your constructor argument character-for-character.
- **`ImportError: pyrage` or `ImportError: yaml`.** You installed the
  base `pyvark` without the extras. Fix:
  `pip install "pyvark[vark-config]"`.

## API coverage (highlights)

* `get_root`, `get_health`, `get_metrics`, `get_version`,
  `get_changelog`: version + latency telemetry (`/health` exposes
  `mean_response_ms` / `p50_response_ms` / `n_samples`).
* `get_databases`, `get_database_info`, `get_group(group_id)`:
  catalog + per-collection landing-page data (API 2.5+). Rows carry the
  lineage fields `designation`, `reanalysis_of`, `donor_group` and
  `has_donor_uid` on current servers.
* Catalogue search (API 2.48.0): `search(q, limit=None, kind=None)`
  is the keyword search of the web front page, grouped by kind
  (`datasets`, `collections`, `genes`, `genesets`, `papers`,
  `artefacts`, `facets`, `help`; `AnthiveClient.SEARCH_KINDS`). A group
  the site lacks is `None`. `kind='papers', format='dataframe'` gives
  one group as a DataFrame. `stats()` returns the front-page numbers
  for you (datasets, cells, genes, gene sets, papers, artefacts you may
  see). See [Search](#search).
* `get_donor_groups`: datasets that share a donor pool (do not count
  them as independent donors).
* `get_plot(db_id, geom, ...)`: every server-side geom: `scatter`,
  `hexbin`, `kde2d`, `violin`, `box`, `bar`, `histogram`, `ecdf`,
  `kde`, `heatmap`, `rolling`, `volcano`, `ma`, `forest`, `de_heatmap`,
  `de_quadrant`.
  Captures the `X-Plot-Caption` response header (the multi-sentence
  figure legend, API 2.7.2+). Supports `color_scale=auto|sequential|
  divergent`, plot clamps (`log2fc_clip`, `neglog10p_clip`,
  `logmean_clip`), bar `group_by`, hexbin auto-clip
  (`vmin_quantile` / `vmax_quantile`), per-axis transforms
  (`transform_x` / `transform_y`, `asinh_scale`), KDE knobs
  (`kde_n`, `kde_bw`, `n_levels`, `iso_overlay`, `point_overlay`),
  marginals / regline overlays, and on-the-fly binning of a
  continuous `color` field via `bin_color=N` (2..20) +
  `bin_color_method='quantile'|'width'`, wired on scatter, hexbin,
  rolling (API 2.34+), kde2d (2.35+), histogram / ecdf / kde (2.36+).
  Data export via `format="csv"` /
  `"tsv"` returns the dataframe the plot was built from (API 2.6+).
* `list_de_studies`, `get_de_study`, `list_de_contrasts`,
  `get_de_rows`, `get_de_by_gene`: DE data flow (API 2.3+).
* `analytics_schema`, `analytics_query`, `analytics_viz`:
  SELECT-only SQL sandbox + Parquet-backed visualisation.
* `module_score`, `list_module_scores`: on-the-fly and pre-computed
  module scores.
* `list_genesets`, `get_geneset`, `rescan_genesets`.
* `list_catalogs`, `get_catalog`, `get_catalog_module`,
  `get_catalog_score`, `rescan_catalogs`: unified module-catalog
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
* The APOE facet is `apoe4_carrier` (column `ant_apoe4_carrier`); API
  2.45.0 removed the `apoe_carrier` alias (an unknown facet now;
  `REMOVED_FACET_ALIASES` maps old names). `AnthiveClient.TESTED_FACETS`
  lists the eleven facets with donor-level results (2.45.0 added
  `graft_sex` and `host_sex` for xenografts; `sex` is human post-mortem
  only), `FACET_SCOPES` the facet scopes, `DEPRECATED_FACETS` the
  deprecated facets and what replaces them.
* Plain-language help (API 2.44.0): `explain("replication")` returns
  the maintainers' text as markdown; `get_help`, `get_help_topic`,
  `get_glossary`, `get_glossary_term` and `search_help` give the parts.
  Facet and context responses list `help_topics` to read first.
* Facet scopes (API 2.44.0): `get_facet`, the facet test views and
  `get_module_variability` take `scope=` (`human_postmortem`,
  `xenograft_human_in_mouse`, `in_vitro`). Human and mouse never mix.
* Donor-level facet tests (exploratory): `get_facet_tests`,
  `get_facet_test_genes`, `get_facet_test_modules`,
  `get_facet_test_volcano`, `get_facet_tests_across_datasets`,
  `get_facet_gene_effects`, `get_facet_recurring_genes`,
  `get_gene_facet_effects`, `get_facet_cohorts`. See below.
* API 2.45.0 facet views: `forest=` (`full`, `anchors`, `none`) on
  `get_facet_gene_effects` and `get_gene_facet_effects`;
  `get_facet_recurring_genes` (also `get_facet_top_genes`) pages with
  `n` (up to 100000), `offset` and `fetch_all=True`, and filters with
  `effect_gate` and `strict`; `get_facet_top_modules`,
  `get_facet_effects_overview`, `get_geneset_facet_effects` (module
  replication next to the member genes), `get_gene_detection` (the
  low-detection pill), `get_facet_donor_values` and
  `get_facet_donor_plot` (one value per donor per cohort; optional
  `db_id`).
* Donor variability (API 2.45.0, exploratory):
  `get_database_donor_variability`, `get_gene_donor_variability`,
  `get_geneset_donor_variability`, `get_donor_variability_top`.
* Gene set ranks within one dataset (API 2.45.0): `get_geneset_rank`,
  `get_module_ranks`. Never compare ranks or means between datasets.
* `get_de_study_summary`: significant gene counts of every contrast of
  a DE study in one call (API 2.45.0).
* Access (API 2.45.0): datasets that are not `access: public` are
  invisible to anonymous callers (missing from listings, 404 by id).
  `rescan_databases`, `rescan_genesets`, `rescan_module_variability`,
  `rescan_catalogs`, `get_plot_cache_stats`, `clear_plot_cache`,
  `admin_release` and `admin_restore` need an admin account (403
  otherwise).
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
* Dataset deposits (API 2.46.0, read-only, for members of the site's
  upload groups): `list_deposits`, `get_deposit`, `get_deposit_report`,
  `get_deposit_vocab`, `get_deposit_group`. Upload datasets with the Go
  CLI: `vark datasets upload`.
* Artefact store (API 2.47.0, read-only): `list_artefacts`,
  `get_artefact`, `get_artefact_versions`, `get_artefact_version`,
  `get_artefact_preview`, `download_artefact_file`, `download_artefact`
  (sha256 verified), `list_artefact_purges`, `list_collections` and
  `list_analysis_collections`; see
  [Artefacts](#artefacts). Depositing and purging is the Go CLI
  (`vark artefacts add`, `vark artefacts purge`).
  `wait_for_deposit` follows any deposit until it is live and raises
  `DepositHeldError` when it waits for an admin.
* A server that was just restarted may answer 503 `warming_up` on the
  facet routes (API 2.46.1+). The client waits and retries for up to
  `warmup_max_wait` seconds (default 180, a constructor argument), then
  raises `AnthiveWarmingUpError`.
* `pick_fastest(base_urls, ...)`: a server-selection helper that
  consumes `/health` latency telemetry.

## Search

The search box of the web front page, as one call (API 2.48.0+). Every
word must match; filler words are dropped and AD, PD, MS, ALS, FTD and
APOE4 are expanded. Only what you may see is searched.

```python
hits = client.search("TREM2 microglia Alzheimer", limit=10)
hits["n_datasets"], [row["db_id"] for row in hits["datasets"]]
hits["genes"]                      # [{"gene": "TREM2", "n_datasets": ...}]
hits["papers"][0]["passages"]      # page, section and snippet per hit

# Only some groups (sent as kind=genes,papers).
client.search("TREM2", kind=["genes", "papers"])

# One group as a DataFrame (needs pandas).
datasets = client.search("astrocyte", kind="datasets", format="dataframe")

# The numbers on the front page, for you.
numbers = client.stats()
numbers["n_datasets"], numbers["n_cells"], numbers["n_papers"]
```

`n_genes` and `n_papers` are `None` on a site without a gene index or
a library. Donors are not counted.

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

## Artefacts

An artefact is a versioned, immutable set of analysis files of one
dataset or one collection (a DE table, figures, a notebook, a model).
Its reference is `<group_id>/<scope>/<artefact_id>[@v<N>]`: the scope is
the dataset's file id (`SMI` of `S19/SMI`) or `_group` for the
collection. Without `@v<N>` it means the latest live version. A
published version never changes. Removing one takes two steps: its
owner or an admin can purge it (soft: the version is marked withdrawn,
with who and why, but its files stay listed and downloadable, and an
unpurge makes it live again), and an admin can then delete it for good,
which leaves a tombstone.

```python
from vark import AnthiveClient, ArtefactDeletedError, ArtefactIntegrityError

c = AnthiveClient("https://my.anthive/api")

# What exists for one dataset, or a whole collection (every page).
rows = c.list_artefacts(db_id="S19/SMI")["artefacts"]
frame = c.list_artefacts(group_id="AT6", all_pages=True, format="dataframe")

# One artefact: versions, files and the provenance in the manifest.
detail = c.get_artefact("AT6/_group/atlas-umap")
detail["versions"]              # [{version, state, published}, ...]
detail["manifest"]["made_from"]  # datasets and versions it was made from
detail["manifest"]["declared"]   # author, software, code, as stated
c.get_artefact_versions("AT6/_group/atlas-umap")  # purged and deleted ones too

# Download one version into a folder; every file is checked against
# the manifest's sha256 and the manifest is written beside the files.
paths = c.download_artefact("AT6/_group/atlas-umap@v2", "atlas-umap/")
png = c.download_artefact_file("AT6/_group/atlas-umap", "a.png")  # bytes

# Every collection you may see, or only those that hold analyses
# (no datasets of their own).
c.list_collections()["collections"]
[row["group_id"] for row in c.list_analysis_collections()]

# Your purge, unpurge and delete requests (made with the Go CLI).
c.list_artefact_purges(action="soft", state="done")
```

The download route answers with a 307 to a presigned S3 link that
works for a few minutes, or streams a verified local copy. pyvark
follows the redirect itself, without your credentials, and keeps the
signed URL out of logs and exceptions. A file is written as
`<name>.part` and renamed once its size and sha256 match; otherwise it
is removed and `ArtefactIntegrityError` is raised. Other refusals have
their own classes: `ArtefactNotFoundError` (also for an artefact you
may not see), `ArtefactFileNotFoundError` (the version has no such
file), `ArtefactDeletedError` (a deleted version, with `tombstone`;
`ArtefactPurgedError` is an older name for it), `ArtefactDeletingError`,
`ArtefactNotOnThisSiteError`, `ArtefactStorageUnavailableError` and
`ArtefactRateLimitedError` (both with `retry_after`). A soft-purged
version is not an error: it downloads normally, its version payload has
`purge` (`{purged, purged_by, purge_reason}`), and the download emits
`ArtefactPurgedWarning`.

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

# API 2.45.0: page through every replicated gene, then look at the
# donors behind one result before trusting it.
every = client.get_facet_top_genes("braak", cell_type="microglia",
                                   n=500, fetch_all=True)
values = client.get_facet_donor_values("sex", "microglia", gene="XIST")
plot = client.get_facet_donor_plot("sex", "microglia", gene="XIST",
                                   dest="xist_sex.png")
print(plot["caption"])          # effects, intervals and q per cohort
modules = client.get_facet_top_modules("braak", effect_gate=True)

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
  the replicated genes (`n_replicated`, `n_genes_in_family`);
  `effect_gate=True` keeps those that pass the effect gate
  (`n_effect_gate`) and `strict=True` those that pass the strict tier.
  Module results (`get_facet_top_modules`) use a standardised effect
  gate and have no strict tier. Directionless gene sets (GWAS, MAGMA)
  are `not_tested`, never "not replicated".
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

# 2. Drill into one catalog: module and score summaries.
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

# 4. Fetch a derived-score recipe, enough to reproduce it
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

## Recipe: module score against a gene on the XY plot (API 2.29+)

`module_score` computes a Seurat-style score on the fly and answers
with summary statistics plus a `session_id`. The per-cell scores stay
on the server; attach the session to a plot and the column
`module_score` becomes a plottable field:

```python
from vark import AnthiveClient
client = AnthiveClient("https://my.anthive.example/api")
db_id = "F24/MIC"   # a dataset with module_scoring_available

score = client.module_score(db_id, genes=["APOE", "TREM2", "CD9", "SPP1"])
print(score["genes_found"], score["summary"]["median"])

plot = client.get_plot(
    db_id, "scatter",
    x="module_score", y="SPP1",
    attach_sessions=score["session_id"],
    color="ant_cell_type",
    marginals=True, regline="global",
    width=6, height=5, dpi=150,
)
open("dam_vs_spp1.png", "wb").write(plot["bytes"])
print(plot["caption"])

# The same session as a SQL table called `scores`.
by_type = client.analytics_query(
    db_id,
    "SELECT o.ant_cell_type, AVG(s.module_score) AS mean_score "
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

# Integration, artefacts: a throw-away ant-serve (API 2.47.0+) on a
# free port in 18700-18799, a temporary store built with anthive4's
# tests/artefact_helpers.py and a fake S3 in the test process:
ANTHIVE4_SOURCE=/path/to/anthive4 \
ANTHIVE_IT_COLLECTION=/path/to/h5adstore/Sankowski2019 \
uv run --with pytest --with requests --with pandas --no-project \
    python -m pytest tests/test_integration_artefacts.py -v

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
(`X.Y.Z`); see `client.AnthiveClient.API_TARGET` for the version this
release was last verified against.

## Links

- Source: <https://gitlab.kuleuven.be/bdslab/anthive/pyvark> (mirror:
  <https://codeberg.org/mfiers/pyvark>)
- Issues: <https://codeberg.org/mfiers/pyvark/issues>
- Changelog: <https://gitlab.kuleuven.be/bdslab/anthive/pyvark/-/blob/main/CHANGELOG.md>
- Anthive server: <https://gitlab.kuleuven.be/bdslab/anthive/anthive4>
- Go command line client: <https://codeberg.org/mfiers/vark>

## License

MIT; see `LICENSE`.
