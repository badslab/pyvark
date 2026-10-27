# pyvark changelog

Versioned record of the Python client. The targeted REST API version is
recorded in `vark.AnthiveClient.API_TARGET`.

## 0.12.2 (2026-10-27)

Released with anthive REST API 2.48.0. `API_TARGET` is now "2.48.0".
Adds the catalogue search and front-page numbers of 2.48 and follows
the two-stage artefact purge. pyvark has no write methods, so purging,
unpurging and deleting stay with the Go CLI.

### Added

- `search(q, limit=None, kind=None, format='json')` for `GET /search`
  (anthive REST API 2.48.0): the catalogue keyword search
  of the web front page, grouped by kind. Returns the server's dict
  (`datasets`, `collections`, `genes`, `genesets`, `papers`,
  `artefacts`, `facets`, `help`, each with its `n_*` count; a group the
  site lacks is `None`). `kind` takes one name or a list from the new
  `AnthiveClient.SEARCH_KINDS` and is sent as a comma list; an unknown
  name raises `ValueError` before any request. `format='dataframe'`
  with exactly one `kind` returns that group's rows as a DataFrame.
- `stats()` for `GET /stats` (REST API 2.48.0): the front-page numbers
  for the caller, passed through as the server sends them.
- On a server without these routes (FastAPI's bare 404) both raise
  `ServerTooOldError` with `required_version` "2.48.0" and a message
  that names the server's version and says it needs anthive REST API
  2.48.0+.

### Changed

- Version state `purged` now means a soft purge: the version is
  withdrawn but still listed and downloadable, and its entry adds
  `purged`, `purged_by` and `purge_reason`. It is not an error any more.
  `get_artefact_version` returns it with `purge: {purged, purged_by,
  purge_reason}` (`None` for other versions).
- `download_artefact` and `download_artefact_file` download a
  soft-purged version as usual and emit the new `ArtefactPurgedWarning`
  (who, when and why); `warnings.simplefilter('error',
  ArtefactPurgedWarning)` makes it an error before any file is fetched.
- New `ArtefactDeletedError` for 410 `deleted` (an admin's permanent
  removal; `tombstone` adds `deleted`, `deleted_by`, `delete_reason`)
  and `ArtefactDeletingError` for 409 `deleting`. `ArtefactPurgedError`
  and `ArtefactPurgingError` stay as aliases of them, and the old words
  `purged` (410) and `purging` (409) of servers before the two-stage
  purge map to the same classes, so existing `except` clauses keep
  working. They are no longer raised for a soft-purged version.
- `list_artefact_purges(state=None, action=None)`: the new `action`
  filter (`soft`, `unpurge`, `hard`; 422 `invalid_action`), and rows
  carry `id` and `action` (requests from before the two-stage purge are
  `hard`).
- Docstrings of `get_artefact`, `get_artefact_versions`,
  `get_artefact_version` and the download methods describe the states
  `live`, `purged`, `deleting`, `deleted`; README updated.

### Tests

- Offline: `search` and `stats` (parameters, `kind` forms and
  validation, DataFrame output, null groups, 422, the 2.48 too-old
  check; 24 tests in `tests/test_search_offline.py`). Checked by hand
  against the dev API (2.47.2 with the unreleased 2.48 routes; that
  build does not filter on `kind` yet).
- Offline: deleted and deleting answers (and the old words), the
  aliases, a soft-purged version returned with `purge`, downloads that
  warn (and fail when the warning is an error), no warning for a live
  version, the `action` filter and `invalid_action` (79 tests in
  `tests/test_artefacts_offline.py`).
- Integration against the branch (f2386ef): a deleted version's 410
  tombstone, a soft-purged version listed, served and downloaded with
  the warning, `action` on `/artefacts/purges` (13 tests).
- Release check on 2026-10-27: 374 offline tests pass. Against the
  anthive4 tree with the 2.48.0 code, the throw-away server suites pass
  (artefacts 13, server 16 with 2 skipped), and the smoke suites on the
  dev API pass apart from the major.minor check, because that build
  still called itself 2.47.2. `search` with `kind` now filters there.

## 0.12.1 (2026-10-20)

Polish for PyPI readers and older servers. `API_TARGET` stays "2.47.0".
Checked against ant-serve 2.47.0 (the anthive4 artefacts branch and the
dev site) and 2.46.4.

### Added

- `ServerTooOldError` (a subclass of `ArtefactError`, with
  `required_version` and `server_version`). A 2.46 server answers the
  artefact and collection routes with FastAPI's bare 404; pyvark now
  raises "this anthive server (REST API 2.46.4) has no artefact store or
  collection listing; it needs anthive REST API 2.47.0+" instead of an
  `ArtefactNotFoundError`. A 404 that carries a status word (every 2.47
  answer) stays an `ArtefactNotFoundError`. Covers `list_artefacts`,
  `get_artefact`, `get_artefact_versions`, `get_artefact_version`,
  `get_artefact_preview`, `download_artefact_file`, `download_artefact`,
  `list_collections`, `list_analysis_collections` and
  `list_artefact_purges`.

### Changed

- `list_analysis_collections()` loses its pre-2.47 fallback and the
  `scan_datasets` argument. Analysis collections exist from 2.47.0 on,
  and on a 2.46 server the fallback could only fail (it read
  `/artefacts`, which is missing there too); such a server now raises
  `ServerTooOldError`.
- Packaging: SPDX license expression `MIT` with `license-files`
  (setuptools 77+), the README declared as Markdown, classifiers for
  Python 3.9 to 3.13 (the offline suite passes on each), maintainers,
  keywords, and project URLs for the GitLab home and source, the
  Codeberg mirror, the Codeberg issue tracker and the changelog (0.12.0
  still pointed everything at Codeberg). `requests>=2.25` stays the only
  required dependency; pandas (`[pandas]`) and the vark credential store
  (`[vark-config]`) are extras. The sdist now carries `CHANGELOG.md`.
- README rewritten for PyPI readers: what pyvark is, supported servers,
  install, a quick start checked against a 2.47 server, and how to sign
  in on Authelia, basic-auth and public sites (HTTP basic on `/api`;
  there are no REST API tokens, MCP tokens only open `/mcp`). Fixed
  examples: the old minimal example used `info["id"]`, which `/info`
  does not return; the module-score recipe used `marginals="hist"` and
  `regline=True`, which the server refuses (now `marginals=True`,
  `regline="global"`, on a dataset with module scoring). No em-dashes
  left in the README.
- `get_plot` docstring: `marginals` is a bool and `regline` is
  `'global'` or `'by_group'`.

### Tests

- `tests/test_artefacts_offline.py`: `ServerTooOldError` on every 2.47
  method against a 2.46 answer, an unreadable `/version`, and a 2.47
  404 with a status word staying `ArtefactNotFoundError` (72 tests).

## 0.12.0 (2026-10-20)

The first PyPI release since 0.7.0. Versions 0.8.0 to 0.11.0 were never
published on PyPI; their changes (entries below) are all part of 0.12.0.

Targets anthive REST API 2.47 (`API_TARGET` "2.47.0"): the artefact
store, read side, and the collection listing. Checked against ant-serve
from the anthive4 branch that carries 2.47.0 (unreleased; `/version`
2.47.0). Nothing is removed or renamed.

### Added (API 2.47.0)

- Artefact store, read-only. An artefact is a versioned, immutable set
  of analysis files of one dataset or one collection; its reference is
  `<group_id>/<scope>/<artefact_id>[@v<N>]`.
  - `list_artefacts(db_id, group_id, kind, q, owner, include_purged,
    limit, cursor, all, *, all_pages=False, format='json')`:
    `GET /artefacts`. `all_pages=True` follows `next_cursor`;
    `format='dataframe'` gives one row per artefact.
  - `get_artefact(ref, version=None)`: the detail (summary, `created`,
    `versions`, the latest live `manifest` with `made_from`, `declared`
    and `recorded`, and `files`), or one version when the reference or
    `version` names one.
  - `get_artefact_versions(ref)`: versions and tombstones.
  - `get_artefact_version(ref, version=None)`: one version (`v<N>` or
    `latest`).
  - `get_artefact_preview(ref, name, version=None)`: the server's WebP
    or text preview.
  - `download_artefact_file(ref, name, dest=None, version=None,
    verify=True)` and `download_artefact(ref, dest, version=None,
    files=None, verify=True, write_manifest=True)`. The version is read
    first, so every file comes from that one version. The 307 to the
    presigned S3 link is followed by hand, without the API credentials
    and without `headers`; the signed URL never appears in a message or
    an exception. Size and sha256 are checked against the manifest
    while streaming into `<file>.part`, which is renamed only once it
    matches (a mismatch removes it and raises
    `ArtefactIntegrityError`). `download_artefact` writes the manifest
    as `manifest.json` (or `_manifest.json` when the artefact has a file
    of that name), as `vark artefacts get` does. File names from the
    manifest are checked (one subfolder at most, no `..`, nothing
    absolute) before anything is written.
  - `list_artefact_purges(state=None)`: `GET /artefacts/purges`, your
    purge requests (admins: everyone's) with `ref`, `version`, `state`,
    `reason`, `requested`, `updated`, `requested_by` and `detail`.
- Collections: `list_collections(kind=None, format='json')` is
  `GET /collections` (`{n_collections, collections}`, each with
  `group_id`, `group`, `title`, `collection_kind`, `access`,
  `n_datasets`, `artefacts_count`, `authors`, `year`).
  `list_analysis_collections()` returns its `kind=analysis` rows. Only
  when a server without the route (404) reports a `/version` older than
  2.47.0 does it fall back to asking `get_group` for the group of every
  visible artefact (`scan_datasets=True` adds the groups of served
  datasets); the fallback rows have the same keys.
  - `parse_artefact_ref(ref)` (static).
- `wait_for_deposit(deposit_id, timeout=1800, poll_interval=15)`: polls
  `get_deposit` until `live`; raises `DepositHeldError` (with
  `held_reasons`) on `held` and `DepositStoppedError` on `failed`,
  `needs_decision`, `rejected`, `withdrawn`, `expired` or `superseded`.
  Works for dataset, DE, artefact and collection deposits made with the
  Go CLI.
- Exceptions (all subclasses of `AnthiveAPIError` and
  `requests.HTTPError`): `ArtefactError` (`status`, `ref`, `file`,
  `retry_after`) with `ArtefactNotFoundError`,
  `ArtefactFileNotFoundError` (404 `file_not_found`, a subclass of
  `ArtefactNotFoundError`; also raised before any download when the
  manifest has no such file),
  `ArtefactNotOnThisSiteError`, `ArtefactPurgedError` (`tombstone`),
  `ArtefactPurgingError`, `ArtefactIntegrityError` (also for a
  client-side checksum mismatch, with `expected_sha256` and
  `actual_sha256`), `ArtefactStorageUnavailableError`,
  `ArtefactRateLimitedError` and `ArtefactDownloadError` (the signed
  link failed, for example after it expired). Other refusals keep the
  server's word in `status`: `invalid_group_id`, `invalid_limit`,
  `invalid_kind`, `invalid_state`, `invalid_cursor`. Deposit answers:
  `DepositNotOwnerError` (403 `not_owner`: a new version of someone
  else's artefact, or a `de_table` / `de_only` deposit by someone who
  may not update the dataset), `DepositQuotaError` (413
  `quota_exceeded`), `DepositHeldError`, `DepositStoppedError`, all
  subclasses of `DatasetDepositError`, so existing `except` clauses keep
  working.

### Not in this release

- Depositing artefacts, creating collections and purging versions:
  pyvark has no deposit write methods (datasets are uploaded with
  `vark datasets upload`), so these stay with the Go CLI
  (`vark artefacts add`, `vark collections create`,
  `vark artefacts purge`). `DepositNotOwnerError` and
  `DepositQuotaError` are raised only by the deposit read routes today
  and are there for a later upload release.

### Changed

- `get_deposit_vocab` docstring: `caller` has `may_deposit_datasets`,
  `may_deposit_artefacts` and `may_create_collections`, and the new
  `artefacts` block repeats the last two (passed through unchanged).
- `download_artefact`: the server now refuses a top-level
  `manifest.json` in deposits (422 `invalid_name`), so the manifest is
  always written as `manifest.json`; `_manifest.json` is kept only for
  an older artefact that has such a file.
- Docstrings from the 2.47 client audit: `get_deposit_vocab` names
  `held_reasons_retired` (reasons a server no longer uses, so older held
  records can still be explained) and says a controlled or missing
  `data_use` is a warning, never a hold; `get_deposit_report` names the
  layer checks' `sample_mode` detail (`sampled`, `sampled_runs`,
  `matrix_exhausted`); the artefact methods name the manifest's
  `previews` list (`[{file, name, size, sha256}]`; `download_artefact`
  does not fetch previews); `get_databases` says reanalyses are listed
  by default (`primary_only=True` drops them) while the counting
  functions exclude them by default (`exclude_secondary=True`). pyvark
  has no dataset search method, so there was nothing else to change.
- `get_group` and `get_database_info` docstrings: the new
  `collection_kind` and `artefacts_count` fields, and the 200 answer of
  an analysis collection without datasets (the fields were already
  passed through).
- Version assertions in the offline tests now expect 2.47.0.

### Tests

- `tests/test_artefacts_offline.py` (mocked HTTP): paths and
  parameters, paging, references, the redirect followed without
  credentials or headers, checksum and size mismatches, unsafe names,
  the manifest name clash, typed errors (`file_not_found`, the new
  error words), `list_collections`, analysis collections with the
  pre-2.47 fallback, `list_artefact_purges`, the vocabulary rights and
  `wait_for_deposit` (64 tests).
- `tests/test_integration_artefacts.py`: a throw-away ant-serve from an
  anthive4 tree (port 18700-18799) with a temporary store built by
  anthive4's own `tests/artefact_helpers.py` and a fake S3 in the test
  process: access per caller, paging, tombstones, previews, local and
  redirected downloads, 502 `integrity_error`, 404 `not_on_this_site`
  and `file_not_found`, `invalid_group_id` / `invalid_limit`,
  `/collections`, `/artefacts/purges` and (with `ANTHIVE_IT_COLLECTION`)
  a dataset artefact (12 tests).

## 0.11.0 (2026-10-19)

The release that includes 0.10.0 and 0.10.1 (neither was uploaded on
their own; their entries below are part of 0.11.0). Targets anthive
REST API 2.46 (`API_TARGET` "2.46.0", which records major.minor) and
works with 2.46.1: the facet 503 `warming_up` answers of 2.46.1 are
retried (0.10.1), and 2.46.1 removes or renames nothing.

### Added (API 2.46.0)

- Read-only dataset deposit methods for depositors and admins:
  `list_deposits(all=False)`, `get_deposit(deposit_id)`,
  `get_deposit_report(deposit_id)`, `get_deposit_vocab()` and
  `get_deposit_group(data_project, basename=None)`. Uploading a dataset
  is `vark datasets upload` (the Go CLI); pyvark has no upload,
  complete, withdraw, approve or reject method. The routes answer 403
  `forbidden` to everyone outside the site's `datasets_upload_groups`.
- `DatasetDepositError` (a subclass of `AnthiveAPIError` and
  `requests.HTTPError`): raised for every refused deposit answer, with
  the body's status word in `status` (`forbidden`, `not_found`,
  `no_report`, `rate_limited`, `disabled`, ...).

### Changed

- `get_health` docstring: a running server with an empty catalogue
  answers 200 with `databases: 0` and `note: "empty catalog"`; a 503
  now means a real failure.
- The 2.45 changes that affect existing methods were already handled
  in 0.10.0: datasets that are not `access: public` need a signed-in
  caller, `/databases/{id}/module-ranks`, `celltype_group` on
  `/donor-variability/top`, `effect_gate_rule` on the module routes.
  The 2.46.1 facet 503 `warming_up` answer is handled by 0.10.1's retry.
- Class docstring names the deposit methods and `vark datasets upload`.
- `list_module_scores` docstring: scores kept only in the scores
  sidecar are listed (API 2.45.0+), with `storage`, `query_table`,
  `query_sql`, `count_by_storage`, `query_tables` and `sidecar_error`;
  it said "obsnum" columns only.
- `analytics_schema` docstring: the `score_sidecar` block and how to
  query the `score_sidecar` view (filter on source, catalog and module;
  several scores with `MAX(score) FILTER (...)` per cell).

### Tests

- `tests/test_deposits_offline.py` (mocked HTTP): paths, `all` and
  `basename` parameters, error mapping, the `/health` note, and that no
  upload method exists.
- `tests/test_smoke.py`: a live deposit check that accepts 403
  `forbidden` / 503 `disabled` for callers outside the upload groups.

## 0.10.1 (part of 0.11.0)

### Added

- Waiting for a warming-up server (anthive REST API 2.46.1+). Right
  after a restart the facet routes may answer 503 `{"status":
  "warming_up", "retry_after": N}` with a `Retry-After` header. Every
  GET and the JSON POSTs now sleep `retry_after` (else the header, at
  least 1 s) and retry, for up to `warmup_max_wait` seconds (new
  constructor argument and attribute, default 180; `0` raises at once).
  Each retry logs a warning on the `vark` logger, and a
  `ServerWarmingUpWarning` is emitted once per wait. When the budget
  runs out the client raises `AnthiveWarmingUpError` (a subclass of
  `AnthiveAPIError` and `requests.HTTPError`, with `retry_after` and
  `waited`). Other 503 answers (uploads switched off, a proxy error)
  are not retried, and POSTs that send a file body are sent once.
- `tests/test_warmup_offline.py` (mocked HTTP and sleep).

`API_TARGET` stays 2.45.0: this release adds no 2.46 routes.

## 0.10.0 (part of 0.11.0)

Targets anthive REST API 2.45.0 (`API_TARGET`; anthive4's
`doc/API_CHANGELOG.md`, "2.45.0"). Every new 2.45.0 route has a method;
responses are passed through unchanged.

### Added (API 2.45.0)

- `get_facet_top_modules(facet, ...)`: `/facets/{facet}/modules/top`,
  gene sets ranked by module replication (`offset`, `effect_gate`,
  `include_not_replicated`, `catalog`, `scope`, `fetch_all`,
  `format='dataframe'`).
- `get_facet_effects_overview(facet, n=10, ...)`:
  `/facets/{facet}/effects/overview`, the facet view in one call.
- `get_geneset_facet_effects(study, experiment, name, ...)`:
  `/genesets/{s}/{e}/{n}/facet-effects`, module replication per facet
  next to the member genes (`facet`, `scope`, `cell_type`,
  `include_units`, `forest`).
- `get_gene_detection(gene)`: `/genes/{gene}/detection`, the data of
  the low-detection pill.
- `get_facet_donor_values(facet, cell_type, gene=|module=, ...)` and
  `get_facet_donor_plot(...)`: `/facets/{facet}/donor-values` and
  `/facets/{facet}/donor-plot.{png|svg|pdf}`, including the `db_id`
  filter. The plot method returns `{bytes, format, caption, mime,
  path}`; the per-cohort effects are only in `caption`. Exactly one of
  `gene` and `module` is checked before the request (`ValueError`).
- Donor variability (exploratory): `get_database_donor_variability`,
  `get_gene_donor_variability`, `get_geneset_donor_variability`,
  `get_donor_variability_top`.
- `get_geneset_rank(study, experiment, name, db_id=None)` and
  `get_module_ranks(db_id)` (`/databases/{id}/module-ranks`): the rank
  of a gene set's mean score among the gene sets of one dataset, with
  `std`.
- `get_de_study_summary(db_id, study_id, padj_max=None)`:
  `/databases/{id}/de/{study}/summary`.
- `forest=` (`full`, `anchors`, `none`; validated against
  `FOREST_DETAIL`) on `get_facet_gene_effects` and
  `get_gene_facet_effects`.
- `get_facet_recurring_genes`: `offset`, `effect_gate`, `strict` and
  `fetch_all` (follows `has_more` and joins the pages); `n_matching`,
  `has_more` and `headline` go to `df.attrs`. `get_facet_top_genes` is
  the same method under the MCP tool's name.
- `get_facet_top_modules` docstring: module rows carry no gene-tier
  keys (`strict`, `r_strong`, `replicated_strong`, `r_treat`,
  `replicated_effect`); the server dropped them instead of sending
  `None`.
- Constants `FOREST_DETAIL`, `DONOR_PLOT_FORMATS`,
  `DONOR_VARIABILITY_RUNGS`, `REMOVED_FACET_ALIASES`.

### Changed (API 2.45.0)

- `TESTED_FACETS` adds `graft_sex` and `host_sex` (xenografts); `sex` is
  human post-mortem only on the server.
- `DEPRECATED_FACET_ALIASES` is empty: the server no longer accepts
  `apoe_carrier` / `ant_apoe_carrier`. The old map moved to
  `REMOVED_FACET_ALIASES`.
- `get_facet_recurring_genes` docstring: `n` goes up to 100000 (was
  "1 to 500"); rows are the replicated genes and the gate is a filter
  (`effect_gate=True`), not a precondition; k counts cohorts at
  `q_value < 0.05` (not `q_treat`); new response fields listed.
- `get_facet_gene_effects` docstring: forest rows, `call`, `nt_label`,
  `gate`, `strict`, `k_over_m`, `cohorts_label`, `detection`,
  `low_detection`, `links`, unit `modality`.
- `get_facet_tests` docstring: `genes.n_up` / `n_down` and `n_q05`,
  `n_up`, `n_down` per `modules` entry.
- `get_version` docstring: `compatible_pyvark`; the fallback shape has
  the key.
- Renamed response fields are documented under their new names:
  `effect_gate_rule` (module routes; the boolean `effect_gate` query
  parameter keeps its name) and `celltype_group` on
  `/donor-variability/top`.

### Security and access (API 2.45.0)

- Class docstring: datasets that are not `access: public` are hidden
  from callers without an identity (missing from listings, the one
  `404 Database '<id>' not found` by id); the server ignores
  `X-Remote-User` / `X-Remote-Groups`.
- `rescan_databases`, `rescan_genesets`, `rescan_module_variability`,
  `rescan_catalogs`, `get_plot_cache_stats`, `clear_plot_cache`,
  `admin_release` and `admin_restore` are documented as admin only
  (403 for other signed-in users).

### Tests

- `tests/test_api245_offline.py` (mocked HTTP) covers every new method,
  the paging helper, argument validation and the docstrings.
- `tests/test_smoke.py` gains a 2.45.0 section (forest rows, paging,
  modules, overview, gene set card, detection, donor values and plot,
  donor variability, ranks, DE summary, the unified 404, the removed
  alias). The 2.44 checks now compare `API_TARGET` with the server's
  major.minor and ask for `effect_gate=True` where they assert the gate.

### Not covered

- Server routes outside the 2.45.0 changes that pyvark has never
  wrapped stay unwrapped: the gene statistics and variance cache admin
  routes, `/admin/api-config`, `/admin/refresh-views`, `/admin/mcp-links`,
  `/me/mcp*`, `/chat*`, `/databases/{id}/curation`, `/pseudobulk`,
  `/source`, `/source.mus`, `/collections/{group}/source` (admin UI
  only) and the notebook routes.
- The relative URLs in a replication entry's `links` are returned as
  given; join them with `base_url` to fetch them.

## 0.9.0 (2026-10-07)

0.9.0 was prepared for API 2.43.0 but never uploaded (PyPI has 0.7.0 as
the latest release, and 0.8.0 was never uploaded either), so the API
2.44.0 work is folded into 0.9.0. Targets anthive REST API 2.44.0
(`API_TARGET`; anthive4's `doc/API_CHANGELOG.md`, "2.44.0"). Responses
are passed through unchanged, so most of this is documentation; the code
changes are the `scope` argument and a few class constants.

### Added (API 2.44.0)

- `scope` argument on `get_facet`, `get_facet_tests_across_datasets`,
  `get_facet_gene_effects`, `get_facet_recurring_genes`,
  `get_gene_facet_effects` and `get_module_variability`. Facets are
  tested, counted and replicated per facet scope (`human_postmortem`,
  `xenograft_human_in_mouse`, `in_vitro`); human and mouse never mix.
  Sent only when given. Responses carry `scope` and `scopes`;
  `get_gene_facet_effects()` without `scope` adds `by_scope`. The
  retired scope `mouse_in_vivo` gives HTTP 400.
  `AnthiveClient.FACET_SCOPES` and `DEFAULT_FACET_SCOPE` list them.
- `TESTED_FACETS` is now the server's nine facets: `sex`, `disease`,
  `apoe4_carrier`, `apoe4_dose`, `braak`, `braak_threshold`, `age`,
  `age_adjusted` and `app_nlgf` (xenograft hosts only).
- `DEPRECATED_FACETS` maps deprecated facets (`region`,
  `author_cluster`, `lesion`, ...) to their replacements;
  `DEPRECATED_FACET_ALIASES` is unchanged (`apoe_carrier`).
- Replication fields documented: `effect_gate_passed`,
  `effect_gate_cohorts`, `n_cohorts_ge_tau`, `effect_gate_tau`,
  `effect_gate_unit`, `median_logFC`, `r_cohorts`, `r_significant`,
  `r_treat`, `replicated_effect`, `r_strong`, `replicated_strong`,
  `k_treat`, `replication_p`, `n_small`, `small_cohort_replicates`;
  `analysis_level` `below_floor`; unit quality fields `lambda_gc`,
  `inflated`, `df_total_median`, `covariates_dropped`,
  `n_sex_checked`, `n_sex_discordant`, `age_top_coded`,
  `design_subset`, `notes`, `small_sample`; gene class flags
  (`gene_flags`); `persists_after_pathology_adjustment` on age rows;
  `strongest_facet`; `n_r_significant`, `n_effect_gate` and
  `n_replicated_effect` on the recurring-genes response (kept in
  `df.attrs` with `format='dataframe'`).
- Facets documented: `ant_age` and its pathology-adjusted twin,
  `ant_app_nlgf`, `ant_host_genotype`, the per-cell-type author cluster
  facets (`ant_mg_author_cluster`, ..., dataset-scoped, no gene tests),
  the `ant_tissue` umbrella with the plain column `tissue_uberon`.
- Dataset fields `facet_scope` and `control_basis` on `get_databases()`
  and `get_database_info()`; `facet_exclude` / `facet_exclude_reason`
  (dataset `.md` fields, not served by `/databases`) explained.

- Plain-language help: `get_help()`, `get_help_topic(topic,
  include_children=True)`, `get_glossary(format='markdown')`,
  `get_glossary_term(term)`, `search_help(q)` and `explain(topic_or_term)`
  (search, then fetch the best topic or term; mirrors the MCP `explain`
  tool). `help_topics` in facet, facet-test and dataset-context
  responses passes through and is named in the docstrings.

- `get_gene_facet_effects()` takes `facet=` (a facet or a list, sent as a
  comma separated list) and `include_units=` (`False` empties `units` in
  every card, about 0.5 MB instead of 5 MB for a gene such as PTPRG).
  Recurring-genes rows add `r_strong`, `replicated_strong` (25 percent
  tier) and, for `age`, `persists_after_pathology_adjustment`; the
  response adds `n_replicated_strong` (also in `df.attrs`). Gene card
  units add `replicate_unit` and `replicate_column`. `facet_exclude`
  and `facet_exclude_reason` are served on `get_databases()`,
  `get_database_info()` and `get_facet_tests()`.

### Changed (API 2.44.0)

- The integration test of the recurring-genes ranking checks the
  current order (`r_value`, then `k`, `agreement`, `median_abs_logFC`).
- `get_library_status()` docstring: non-admins no longer get
  `unresolved_references`, issue texts, `library_dir` or `index.path`
  (issue lists are empty); `n_errors` and `n_warnings` are new.

- Replication semantics changed on the server (field names did not):
  `r_value` and `p_pc` use the ordinary one-sided limma p value, `k`
  counts cohorts at `q_value < 0.05`, `replicated` is `r_value < 0.05`
  (the direction reproduces; the size is judged by `effect_gate_passed`
  and `replicated_effect`). Small cohorts are tested and counted
  (`small_sample`) instead of `descriptive_only`; datasets need 4
  replicates. `FACET_TESTS_CAVEATS` and the docstrings say so.

## 0.9.0 earlier work (prepared for API 2.43.0, 2026-10-05)

Targets anthive REST API 2.43.0 (`API_TARGET`; anthive4's
`doc/API_CHANGELOG.md`, 2026-10-05). Docstrings that said "anthive main
after 2.42.1" now say "REST API 2.43.0+". Responses are passed through unchanged, so most of this is
documentation; the code changes are small.

### Changed

- Facet `apoe_carrier` is now `apoe4_carrier` (column
  `ant_apoe4_carrier`) in `TESTED_FACETS`, docstrings and README. The
  server accepts the old name as a deprecated alias for one release;
  `AnthiveClient.DEPRECATED_FACET_ALIASES` maps old to new.
- Facet engine v2 documented. Replication entries of
  `get_gene_facet_effects()` / `get_facet_gene_effects()` carry
  `r_value`, `p_pc`, `k`, `m`, `replicated`, `r_direction`, `anchors`,
  `overlap_unknown`, `cohorts_overlap_unknown`, `replication_u`,
  `replication_method` and `legacy_badge`. `replicated` means a
  partial-conjunction `r_value < 0.05`; "k of m" is descriptive only
  (`FACET_TESTS_CAVEATS` and the docstrings say so). Units add `anchor`,
  `pooled`, `p_treat`, `q_treat`, `tau_log2`, `analysis_level` and
  `analysis_level_reason`; gene rows add `p_treat`, `q_treat`,
  `tau_log2`; module rows add `passes_effect_gate`.
- `get_facet_recurring_genes()` rows list replicated genes only and add
  `r_value`, `p_pc`, `k`, `m`, `replicated`; the response adds
  `n_replicated` and `n_genes_in_family` (kept in `df.attrs` with
  `format='dataframe'`). The fields `units_up`, `units_down` and
  `max_abs_logFC` no longer exist on the server.
- `get_module_variability()` and `get_gene_variance_by_facet()` are
  documented as per-cell and descriptive (cells are not replicates);
  `signal_strength` of `list_facets()` is deprecated. The module
  variability DataFrame keeps the server's `basis` in `df.attrs`.

### Added

- Dataset fields `replicate_unit`, `replicate_column`,
  `replicate_basis` and `disease_basis` on `get_databases()` (DataFrame
  columns) and `get_database_info()`, and on the facet test summary and
  units.

## 0.8.0 (2026-10-05)

Targets anthive REST API 2.42.1 plus the additions listed under
"Unreleased" in anthive4's `doc/API_CHANGELOG.md` on main of
2026-10-05 (`API_TARGET` is `2.42.1` until the server bumps its
version). Every addition is backward compatible; against older servers
the new methods answer 404 and the new arguments are ignored.

### Added

- Donor-level facet test results (exploratory, donor-level, disease
  contrast provisional; every docstring says how to read
  `descriptive_only`, `counted` / `not_counted_reason` and the
  replication rule). One dataset: `get_facet_tests()` (summary units
  with flags and the `model` object), `get_facet_test_genes()` and
  `get_facet_test_modules()` (all server filters, `format='json'`,
  `'dataframe'` or `'csv'`), `get_facet_test_volcano()` (PNG bytes or a
  file). Across datasets: `get_facet_tests_across_datasets()`
  (`/facets/{name}/tests`), `get_facet_gene_effects()`
  (`/facets/{name}/effects?gene=`, with cell type groups, `cl_id`,
  `labels`, `q_counted`, `n_sibling_strata`),
  `get_facet_recurring_genes()` (`/facets/{name}/effects/top`, ranked
  by k, `agreement`, `median_abs_logFC`), `get_gene_facet_effects()`
  (`/genes/{gene}/facet-effects`) and `get_facet_cohorts()` (the DRAFT
  cohort table).
- `AnthiveClient.TESTED_FACETS` (`sex`, `disease`, `apoe_carrier`,
  `braak`) and `AnthiveClient.FACET_TESTS_CAVEATS`.
- `get_donor_groups()` (`GET /donor-groups`, optional `donor_group`,
  `format='dataframe'` gives one row per group and dataset). Extra
  fields such as distinct donor counts are passed through.
- `get_database_facets()` (`GET /databases/{id}/facets`, `counts`).
- `exclude_secondary` (default `True`, the server default) on
  `get_gene_stats_all()`, `get_module_variability()`, `get_facet()` and
  the facet test views. The client sends it only when `False`.
- `get_facet(mapping=...)` and `list_facets(full=True)` (returns
  `facets_visible` and `definitions_status` next to the rows, which
  carry `label`, `summary`, `defined` and `hidden_by_config`).
- `get_gene_stats_all(format='dataframe')` has an `is_secondary`
  column.
- Docstrings of `get_databases()` / `get_database_info()` describe the
  lineage fields `designation`, `reanalysis_of`, `donor_group` and
  `has_donor_uid`.
- `tests/test_facets_offline.py` (mocked HTTP) and
  `tests/test_integration_facets.py` (a throw-away ant-serve serving
  the real store read-only through a symlink mirror).

### Audit

Every existing method was compared with the routes and parameters of
`bin/api/ant-serve` on anthive4 main. Apart from the
`exclude_secondary` and `mapping` parameters above no mismatch was
found.

## 0.7.0 (2026-10-03)

Targets anthive REST API 2.41.0 (`API_TARGET`).

### Added

- Paper library (API 2.39+). `list_papers()` with the server's filters
  (`role`, `celltype`, `tissue`, `disease`, `method`, `cohort`,
  `organism`, `author`, `year`, `q`), `get_paper()`,
  `get_related_papers()`, `get_paper_page()`, `get_paper_bibtex()`,
  `get_library_bibtex()`, `download_paper_pdf()`, `search_literature()`,
  `get_database_papers()`, `get_database_context()` and
  `get_library_status()`.
- Paper upload (API 2.40+, uploaders only).
  `get_paper_upload_requirements()`, `upload_paper()` (record as dict,
  JSON, `.md` text or a path; PDF as path, bytes or file object;
  `folder`, `role`, `papers_for`, `enrich`, `dry_run`, `update`),
  `upload_papers()` for several papers in a row and
  `paper_items_from_folder()` to pair `name.md` records with their PDFs.
- New exceptions in `vark.exceptions`, all subclasses of
  `requests.HTTPError`. `PaperUploadForbiddenError` (403, the caller is
  not an uploader), `PaperUploadDisabledError` (503, uploads switched
  off), `PaperDuplicateError` (409, with `existing_citekey` and
  `matched_on`), `PaperInvalidError` (422, with `errors` and
  `missing_required`), `PaperTooLargeError` (413) and `PaperNotPDFError`
  (415).
- Dataset files. `list_database_files()`, `download_database_file()`
  (the `.h5ad`) and `download_static_file()`.
- Endpoints the client did not cover yet. `get_obs_summary()`,
  `get_obs_top()`, `get_mus_vocab()`, `list_geneset_studies()`,
  `get_genesets_by_gene()`, `get_module_variability()` and
  `rescan_module_variability()`.
- New optional arguments. `attach_sessions` on `get_plot()` and
  `analytics_query()` (plus `session_id` and `timeout` there),
  `n_control`, `seed` and `subset` on `module_score()`, `top` on
  `get_gene_stats()`, the dataset filters (`organism`, `cell_type`,
  `source`, `access`, `tissue`, `include_remote`, `refresh`) on
  `get_gene_stats_all()`, `organism` / `method` / `study` on
  `list_genesets()`, `per_facet_value_limit` on `get_facet()`,
  `duration_seconds` / `drain_timeout_seconds` on `admin_release()`.
- Credentials from `ANTHIVE_USER` and `ANTHIVE_PASSWORD` when no
  `auth=` is passed (before the vark CLI store; `~/.netrc` still works
  through `requests`).

### Fixed

- `get_gene_stats()` no longer sends `layer=X` by default. The server
  then uses the dataset's own default layer, as it does for every other
  client. Pass `layer='X'` to get the old behaviour.
- `module_score(format='dataframe')` built a frame from the wrong key
  (the server returns no per-cell `cells`). It now returns a one-row
  frame of the summary statistics. The `name` argument was never read
  by the server; it is kept and documented as ignored.
- `analytics_query(limit=...)` was sent but never read by the server;
  it is no longer sent (the argument stays, documented as ignored).
- The README's module-score recipe used a `column` key that the server
  never returned. It now plots `module_score` through
  `attach_sessions=score["session_id"]`.
- `get_layers()` and `get_embeddings()` were documented as returning
  lists; the server returns mappings (key to display name, key to
  info). The return value is unchanged, the documentation is fixed.
- Smoke tests compared API versions as strings, so a 2.41 server was
  treated as older than 2.5 and the group tests were skipped.

### Docs

- README sections on credentials (never a password in code), the paper
  library and uploads, and the integration test.

## 0.6.0 — 2026-09-02

### Added

- Three new methods on `AnthiveClient` that cover the fleet-wide facets
  surface. `list_facets()` calls `GET /facets` and returns the inventory
  of `ant_*` obs columns across every dataset, with type, mixed-type
  flag, dataset count, and recorded signal strength per row.
  `get_facet(name, top_modules=200)` calls `GET /facets/{name}` and
  returns the detail payload for one facet, including per-dataset
  summaries, value distribution, and the top module-variability rows.
  `get_gene_variance_by_facet(db_id, facet, top=50)` calls
  `GET /databases/{db_id}/gene-variance-by-facet` and ranks genes on
  one dataset by between-group variance of their mean expression.
- New `only_facet` kwarg on `AnthiveClient.get_databases`. Pass a
  `{facet_name: [allowed_values]}` dict to filter datasets whose
  `collection` block matches. Rows without a `collection` block or
  without the requested key are dropped. The filter runs client-side
  and composes with `primary_only`.

### Docs

- Documented three response fields on `get_database_info` that callers
  can rely on. A top-level `description` field carries the dataset's
  prose description. The `collection` sub-dict may include a `title`
  key that overrides the group name for display (fall back to `group`
  when absent) and a `date` key with the full `YYYY-MM-DD` publication
  date.

## 0.5.0 — 2026-08-26

### Added — REST API 2.37 `is_secondary`

- **`is_secondary` field** on ``/databases`` list rows and on
  ``/databases/{id}/info`` responses. A value of ``True`` means the
  dataset re-aggregates cells that are already counted in another
  study and should be excluded from meta-analyses. ``False`` marks a
  fully primary study. Older servers that omit the field are handled
  as "primary".
- **`AnthiveClient.get_databases(primary_only=False)`** — new kwarg.
  When ``True`` the client drops rows where ``is_secondary`` is
  truthy. Filtering runs client-side (the server has no dedicated
  query param yet), which keeps the call a single request and works
  against any server that returns the field.

### Changed

- **`AnthiveClient.API_TARGET`** bumped from ``"2.36.0"`` to
  ``"2.37.0"`` — the version this release was last verified against.

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
