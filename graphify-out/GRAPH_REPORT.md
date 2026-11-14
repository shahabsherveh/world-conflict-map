# Graph Report - workspace  (2026-11-13)

## Corpus Check
- 102 files · ~76,684 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 5, .lock 2, .ini 1)

## Summary
- 1114 nodes · 2362 edges · 57 communities (39 shown, 18 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 176 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- API Routes
- Briefing Script
- GDELT Ingest
- Config & Model Download
- Docs & Specs
- Extraction Adapters
- Event Grouping
- CI Workflow
- DB Engine & Queries
- Extraction Tests
- Map Smoke Test
- Grouping Tests
- Raw Event Store
- UV Python Action
- Browser CDP Tests
- Zero-Shot Classifier
- Location Geocoding
- Deploy Workflow
- Pipeline Run & Models
- API Tests
- Host Scripts
- Ingestion Audit
- Docker Compose
- Filter & Classifier Tests
- DB Helpers & Repair Scripts
- Model Download Tests
- Alembic Migrations
- Lockfile Tests
- API Validation Tests
- Process Raw Script
- Map Rendering
- App Main & Health
- Detail Panel JS
- State JS
- Dependabot Config
- Persist & Retry
- Conflict List JS
- Corroboration Tests
- Query Count Tests
- Install Runner
- Data Dir Script
- Venv Script
- Pipeline Entrypoint
- Health Check
- Pipeline Check
- Health Watch
- Install Hooks
- Lock Deps
- Headline Fallback Test
- Headline Order Test
- Coordinate Pairing Test
- No-Country Grouping Test
- Unlocated Grouping Test
- Root Package

## God Nodes (most connected - your core abstractions)
1. `ConflictEvent` - 79 edges
2. `Conflict` - 63 edges
3. `make_session()` - 42 edges
4. `run()` - 38 edges
5. `group_events()` - 36 edges
6. `RawEvent` - 32 edges
7. `utcnow()` - 28 edges
8. `IngestionRun` - 26 edges
9. `GDELTClient` - 24 edges
10. `seed()` - 24 edges

## Surprising Connections (you probably didn't know these)
- `test_post_event_rejects_missing_conflict()` --uses--> `ConflictEvent`  [INFERRED]
  tests/test_api.py → app/models.py
- `slug_to_text headline` --semantically_similar_to--> `Zero-shot NLI model`  [INFERRED] [semantically similar]
  tasks/optional-items.md → docs/SPEC-extraction.md
- `test_run_reports_a_download_that_never_succeeded()` --uses--> `GDELTClient`  [INFERRED]
  tests/test_extraction.py → app/ingest/gdelt.py
- `test_run_reports_a_partly_corrupt_cached_day()` --uses--> `GDELTClient`  [INFERRED]
  tests/test_extraction.py → app/ingest/gdelt.py
- `client()` --uses--> `Base`  [INFERRED]
  tests/test_api.py → app/models.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **One-way build order chain** — docs_spec_storage_storage_module, docs_spec_ingestion_ingestion_module, docs_spec_extraction_extraction_module, docs_spec_api_api_module, docs_spec_ui_ui_module [EXTRACTED 1.00]
- **Daily pipeline: fetch → filter → persist → group** — docs_spec_ingestion_gdelt, docs_spec_ingestion_ingestion_module, docs_spec_extraction_extraction_module, docs_spec_extraction_root_code_filter, docs_spec_extraction_zero_shot_nli_model, docs_spec_storage_raw_event, docs_spec_extraction_grouping_rule, docs_spec_storage_conflict [EXTRACTED 1.00]
- **Data honesty invariants (null-not-zero, counts-not-verification, no re-geocoding)** — docs_spec_api_corroboration, docs_spec_extraction_confidence_score, docs_spec_ui_no_location_conflicts, docs_spec_storage_edit_log [INFERRED 0.75]

## Communities (57 total, 18 thin omitted)

### Community 0 - "API Routes"
Cohesion: 0.06
Nodes (36): _apply_patch(), create_conflict(), create_event(), _event_out(), _events_out(), get_conflict(), get_event(), _headline() (+28 more)

### Community 1 - "Briefing Script"
Cohesion: 0.08
Nodes (33): Conflict, _corroboration(), _count(), database_path(), _display_name(), Event, _event_line(), load_conflicts() (+25 more)

### Community 2 - "GDELT Ingest"
Cohesion: 0.08
Nodes (23): GDELTClient, parse_export_zip(), read_day_from_dir(), dedupe_new(), parse_export_tsv(), make_row(), ok_response(), test_dedupe_new() (+15 more)

### Community 3 - "Config & Model Download"
Cohesion: 0.06
Nodes (19): load_config(), _loaded_config(), main(), cache_root(), has_weights(), incomplete_blobs(), main(), snapshot_dir() (+11 more)

### Community 4 - "Docs & Specs"
Cohesion: 0.07
Nodes (44): AGENTS.md — agent rules, Capability map, Case study, CI/CD design, CI gates, Docker stack, GCM_DATA_ROOT, GCM_HF_HOME (+36 more)

### Community 5 - "Extraction Adapters"
Cohesion: 0.09
Nodes (22): BaseSourceAdapter, EventDraft, _confidence(), _count(), GDELTAdapter, _map_event_type(), _summary(), _to_float() (+14 more)

### Community 6 - "Event Grouping"
Cohesion: 0.11
Nodes (21): _anchor(), city_of(), _country_matches(), _last_event_dates(), _matches(), _place_matches(), regroup_all(), _same_place() (+13 more)

### Community 7 - "CI Workflow"
Cohesion: 0.06
Nodes (38): concurrency, cancel-in-progress, group, defaults, run, env, GCM_DATABASE_URL, PIP_DISABLE_PIP_VERSION_CHECK (+30 more)

### Community 8 - "DB Engine & Queries"
Cohesion: 0.08
Nodes (19): database_url(), get_engine(), make_engine(), make_session_factory(), run_migrations_offline(), run_migrations_online(), conflicts_active_in_range(), events_in_range() (+11 more)

### Community 9 - "Extraction Tests"
Cohesion: 0.11
Nodes (19): run(), day_runs(), make_session(), phase_runs(), test_run_marks_a_healthy_filtered_run_as_not_degraded(), test_run_raw_only_stores_without_processing(), test_run_reads_local_files(), test_run_records_a_grouping_failure_outside_the_day_rows() (+11 more)

### Community 10 - "Map Smoke Test"
Cohesion: 0.08
Nodes (32): jsdom, CACHE, cachePath(), CDN, check(), daysAgo(), expectedMarkers(), expectedNoLocation() (+24 more)

### Community 11 - "Grouping Tests"
Cohesion: 0.09
Nodes (19): group_events(), _ev(), test_group_events_does_not_claim_manual_events(), test_group_events_does_not_merge_distant_cities_in_one_country(), test_group_events_gap_is_measured_from_the_last_event_not_the_start(), test_group_events_keeps_a_quiet_week_inside_one_conflict(), test_group_events_keeps_an_anchorless_conflict_to_its_own_place(), test_group_events_keeps_one_conflict_per_theatre_with_autoflush_off() (+11 more)

### Community 12 - "Raw Event Store"
Cohesion: 0.15
Nodes (15): mark_raw_events(), _parse_event_date(), _payload(), pending_raw_events(), pending_raw_source_days(), prune_raw_events(), raw_payload(), store_raw_events() (+7 more)

### Community 13 - "UV Python Action"
Cohesion: 0.06
Nodes (30): description, PYTHON_VERSION, REQUIREMENTS, UV_VERSION, VENV, inputs, python-version, requirements (+22 more)

### Community 14 - "Browser CDP Tests"
Cohesion: 0.08
Nodes (9): Cdp, jsErrors, mapZoom(), nearestDot(), openEventAt(), Page, sleep(), tiles (+1 more)

### Community 15 - "Zero-Shot Classifier"
Cohesion: 0.09
Nodes (11): BinaryClassifier, SingleTextClassifier, warn_if_model_cache_is_local(), ZeroShotConflictClassifier, load_articles(), main(), metrics(), FakePipeline (+3 more)

### Community 16 - "Location Geocoding"
Cohesion: 0.12
Nodes (14): Geocoder, haversine_km(), NominatimGeocoder, _norm(), resolve_coordinates(), split_place(), StubGeocoder, test_haversine_reasonable() (+6 more)

### Community 17 - "Deploy Workflow"
Cohesion: 0.07
Nodes (28): concurrency, cancel-in-progress, group, environment, if, name, runs-on, steps (+20 more)

### Community 18 - "Pipeline Run & Models"
Cohesion: 0.12
Nodes (7): cache_note(), download_note(), merge_notes(), events_for_conflict(), latest_event(), latest_successful_ingestion_run(), recent_ingestion_runs()

### Community 19 - "API Tests"
Cohesion: 0.08
Nodes (7): get_db(), test_ingestion_runs_exposes_failure_and_degradation(), test_ingestion_runs_exposes_phase_rows(), test_ingestion_runs_returns_newest_first_and_honors_limit(), test_list_conflicts_includes_eventless_manual_conflict(), test_openapi_document_names_every_operation(), test_post_event_rejects_missing_conflict()

### Community 20 - "Host Scripts"
Cohesion: 0.12
Nodes (15): check-deps.sh script, GCM_DATABASE_URL, ci-check.sh script, step(), db_stats(), fail(), log(), cutover-data.sh script (+7 more)

### Community 21 - "Ingestion Audit"
Cohesion: 0.14
Nodes (10): pipeline_phase(), settle_stale_runs(), IngestionRun, utcnow(), main(), test_pipeline_health_does_not_count_failed_or_running_runs_as_fresh(), test_pipeline_health_fresh_after_a_recent_success(), test_pipeline_health_ignores_raw_only_runs() (+2 more)

### Community 22 - "Docker Compose"
Cohesion: 0.11
Nodes (20): context, network, GCM_DATABASE_URL, name, build, entrypoint, environment, image (+12 more)

### Community 23 - "Filter & Classifier Tests"
Cohesion: 0.16
Nodes (9): filter_by_zero_shot(), BatchStubClassifier, make_draft(), StubClassifier, test_filter_batches_and_dedupes_slugs(), test_filter_by_zero_shot_keeps_conflicts_and_no_url(), test_filter_by_zero_shot_reads_trailing_slash_urls(), test_filter_keeps_an_event_whose_url_has_no_slug() (+1 more)

### Community 24 - "DB Helpers & Repair Scripts"
Cohesion: 0.16
Nodes (4): execute_dml(), get_session(), main(), main()

### Community 25 - "Model Download Tests"
Cohesion: 0.16
Nodes (9): _load_module(), model_cache(), snapshot(), test_check_mode_exit_zero_with_weights(), test_check_mode_exits_nonzero_without_weights(), test_config_only_is_not_enough(), test_incomplete_blobs_are_reported(), test_pytorch_bin_counts_as_complete() (+1 more)

### Community 26 - "Alembic Migrations"
Cohesion: 0.18
Nodes (5): upgrade(), upgrade(), upgrade(), upgrade(), upgrade()

### Community 27 - "Lockfile Tests"
Cohesion: 0.16
Nodes (7): _entries(), _locked(), _requirements(), test_every_top_level_requirement_is_locked_and_satisfied(), test_gate_tools_are_not_in_the_runtime_lock(), test_lock_pins_every_package_and_carries_its_hash(), test_lock_pins_the_cpu_torch_build_and_declares_its_index()

### Community 28 - "API Validation Tests"
Cohesion: 0.12
Nodes (14): seed(), test_conflict_date_order_is_validated(), test_conflict_detail_includes_events(), test_event_headline_derived_from_source_url(), test_event_source_url_must_be_http(), test_event_text_fields_are_bounded_like_their_columns(), test_list_conflicts_filters_by_range(), test_patch_conflict_logs_edit() (+6 more)

### Community 29 - "Process Raw Script"
Cohesion: 0.15
Nodes (8): describe_exception(), load_classifier(), resolve_target_days(), main(), parse_args(), test_describe_exception_truncates_a_huge_message(), test_resolve_target_days_explicit_range(), test_resolve_target_days_last_week()

### Community 30 - "Map Rendering"
Cohesion: 0.17
Nodes (12): clusterHeat(), esc(), eventMarker(), fmtDate(), heatColor(), HOME_VIEW, intensityClass(), map (+4 more)

### Community 32 - "Detail Panel JS"
Cohesion: 0.33
Nodes (11): addEvent(), corroborationBadge(), eventPopup(), newConflict(), renderConflictDetail(), renderEditPanel(), renderEventEditForm(), saveEdit() (+3 more)

### Community 33 - "State JS"
Cohesion: 0.20
Nodes (7): api, defaultDates(), rangeConflicts, rangeEvents, setDateInputs(), showNotice(), startCoordinatePick()

### Community 34 - "Dependabot Config"
Cohesion: 0.17
Nodes (11): prefix, dependency-name, interval, updates, commit-message, directory, ignore, open-pull-requests-limit (+3 more)

### Community 35 - "Persist & Retry"
Cohesion: 0.29
Nodes (4): persist_drafts(), process_pending_raw_events(), retry_stranded_raw_days(), existing_source_event_ids()

### Community 36 - "Conflict List JS"
Cohesion: 0.36
Nodes (8): conflictItem(), loadConflicts(), paintConflictList(), paintNoLocationList(), renderConflictList(), setLocationFor(), settlePendingReveal(), updateRange()

### Community 37 - "Corroboration Tests"
Cohesion: 0.22
Nodes (4): add_raw_payload(), test_event_endpoints_expose_corroboration_counts(), test_many_articles_from_one_outlet_is_not_well_corroborated(), test_unparsable_payload_counts_are_zero()

### Community 38 - "Query Count Tests"
Cohesion: 0.29
Nodes (3): query_counter(), test_conflict_detail_query_count_is_bounded(), test_conflict_list_query_count_is_bounded()

### Community 39 - "Install Runner"
Cohesion: 0.60
Nodes (5): as_root(), fail(), log(), install-runner.sh script, usage()

## Ambiguous Edges - Review These
- `Confidence score` → `Briefing generator`  [AMBIGUOUS]
  tasks/todo.md · relation: conceptually_related_to

## Knowledge Gaps
- **10 isolated node(s):** `global-conflict-map`, `HF_HOME`, `GCM_DATABASE_URL`, `Optional items`, `CAMEO root-code filter` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 449 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ConflictEvent` connect `Event Grouping` to `API Routes`, `Briefing Script`, `Persist & Retry`, `Corroboration Tests`, `Query Count Tests`, `Extraction Adapters`, `DB Engine & Queries`, `Extraction Tests`, `Grouping Tests`, `Pipeline Run & Models`, `API Tests`, `Coordinate Pairing Test`, `Unlocated Grouping Test`, `No-Country Grouping Test`, `Filter & Classifier Tests`, `DB Helpers & Repair Scripts`, `API Validation Tests`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `ConflictEvent` (e.g. with `create_event()` and `_event_out()`) actually correct?**
  _`ConflictEvent` has 49 INFERRED edges - model-reasoned connections that need verification._
- **What connects `global-conflict-map`, `HF_HOME`, `GCM_DATABASE_URL` to the rest of the system?**
  _10 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `API Routes` be split into smaller, more focused modules?**
  _Cohesion score 0.05561105561105561 - nodes in this community are weakly interconnected._
- **Why does `Conflict` connect `Event Grouping` to `API Routes`, `Briefing Script`, `DB Engine & Queries`, `Extraction Tests`, `Grouping Tests`, `Pipeline Run & Models`, `API Tests`, `No-Country Grouping Test`, `Unlocated Grouping Test`, `Filter & Classifier Tests`, `DB Helpers & Repair Scripts`, `API Validation Tests`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 33 inferred relationships involving `Conflict` (e.g. with `create_conflict()` and `create_event()`) actually correct?**
  _`Conflict` has 33 INFERRED edges - model-reasoned connections that need verification._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `Confidence score` and `Briefing generator`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._