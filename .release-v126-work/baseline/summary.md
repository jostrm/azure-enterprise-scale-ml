# Component suites - /home/user/wt-base

HEAD `ebd300db85ab37cdcc96d0c4c552b8d0d4dc8429`, run 2026-11-14T00:31:47Z .. 2026-11-14T00:37:44Z, runner recipe 7.

| suite | test files | tests | passed | failed | errors | skipped | seconds | exit | status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| azurefactory-cli | 36 | 1820 | 1765 | 43 | 0 | 12 | 103.1 | 1 | fail |
| graphify | 4 | 30 | 30 | 0 | 0 | 0 | 9.0 | 0 | pass |
| wizard-api-usage-examples | 3 | 168 | 148 | 0 | 0 | 20 | 16.7 | 0 | pass |
| bicep-automation | 3 | 145 | 145 | 0 | 0 | 0 | 10.4 | 0 | pass |
| esml-v2 | 27 | 952 | 952 | 0 | 0 | 0 | 268.7 | 0 | pass |
| healthmodel | 20 | 557 | 549 | 3 | 0 | 5 | 14.4 | 1 | fail |
| mcp | 18 | 676 | 673 | 3 | 0 | 0 | 34.8 | 1 | fail |
| func-aifactory-lifecycle | 23 | 380 | 380 | 0 | 0 | 0 | 25.5 | 0 | pass |
| func-aifactory-lifecycle-wt-sdk | 23 | 380 | 380 | 0 | 0 | 0 | 25.0 | 0 | pass |
| agent-factory | 28 | 622 | 599 | 4 | 0 | 19 | 28.2 | 1 | fail |
| aifactory-agent | 32 | 1557 | 1527 | 17 | 11 | 2 | 42.0 | 1 | fail |
| voice-sales-py | 8 | 105 | 104 | 1 | 0 | 0 | 31.1 | 1 | fail |
| voice-sales-frontend-js | 5 | 46 | 46 | 0 | 0 | 0 | 0.5 | 0 | pass |
| rag-48 | 24 | 308 | 231 | 15 | 59 | 3 | 13.7 | 1 | fail |
| ml-churn-49 | 10 | 32 | 27 | 4 | 0 | 1 | 29.8 | 1 | fail |
| ml-model-factory | 29 | 1088 | 1031 | 4 | 0 | 53 | 325.0 | 1 | fail |
| mlops-2026-09 | 2 | 51 | 51 | 0 | 0 | 0 | 16.3 | 0 | pass |
| dataops-adf | 1 | 15 | 15 | 0 | 0 | 0 | 4.4 | 0 | pass |
| onion | 1 | 21 | 21 | 0 | 0 | 0 | 0.6 | 0 | pass |
| tutorial-distribution-ps1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0 |  | not-run |
| agent-foundry-legacy | 1 | 0 | 0 | 0 | 0 | 0 | 0.0 |  | not-run |
| automl-scoring-file | 1 | 0 | 0 | 0 | 0 | 0 | 0.0 |  | not-run |
| **total** | 300 | 8953 | 8674 | 94 | 70 | 115 | 999.2 | | |

## Failing, timed-out and not-run suites

### azurefactory-cli - fail
Last pytest line: `43 failed, 1765 passed, 12 skipped in 102.38s (0:01:42)`
- `environment_setup/azurefactory-cli/tests/test_documentation_quickstarts.py::test_images_have_alt_text_and_stay_small[documentation/v2/quickstarts/01-install-esaf.md]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_documentation_quickstarts.py::test_every_rest_route_and_body_field_shown_is_one_the_api_route_takes[environment_setup/install_config_wizard/readme.md]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_plan_ensure_offline_api_free_and_scope_bound` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_ensure_rejects_missing_consent_or_inconsistent_flags[extra0]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_ensure_rejects_missing_consent_or_inconsistent_flags[extra1]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_ensure_rejects_missing_consent_or_inconsistent_flags[extra2]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_ensure_rejects_missing_consent_or_inconsistent_flags[extra3]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_ensure_rejects_missing_consent_or_inconsistent_flags[extra4]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_review_integrity_and_source_changes_block_ensure[digest]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_review_integrity_and_source_changes_block_ensure[reference]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_review_integrity_and_source_changes_block_ensure[scope]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_review_integrity_and_source_changes_block_ensure[review]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_review_integrity_and_source_changes_block_ensure[unknown]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_review_integrity_and_source_changes_block_ensure[secret]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_review_integrity_and_source_changes_block_ensure[source]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_acknowledgment_is_not_automatic_and_artifacts_are_not_overwritten` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_direct_hash_ensure_supported_without_api` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_partial_failure_uses_failure_code_and_preserves_result` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_result_path_errors_block_before_ensure_or_report_reconciliation_after` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_binding_exact_api_receipt_then_separate_confirm` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_candidate_scope_tampering_even_with_recomputed_digest_is_rejected` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_binding_preview_must_acknowledge_exact_candidate[binding]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_binding_preview_must_acknowledge_exact_candidate[factory]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_binding_preview_must_acknowledge_exact_candidate[revision]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_bundle_and_copy_rules_include_all_helpers` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_plan_and_publish_one_consent_exact_scope_and_offline_cost` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_never_invents_approval_or_governance[flags0-approval-required]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_never_invents_approval_or_governance[flags1-blocked]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_cost_and_intent_are_saved_before_mutation` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_preserves_explicit_blob_options[explicit0]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_preserves_explicit_blob_options[explicit1]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_preserves_existing_blob_binding_without_mode_option` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_auto_creation_excludes_dependencies_and_reused_identity_groups[True]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_auto_creation_excludes_dependencies_and_reused_identity_groups[False]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_auto_creation_never_turns_shared_identity_dependency_into_owned_group` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_rejects_register_drift_between_convenience_and_plan` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_respects_explicit_empty_creation_and_rejects_broad_roles` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_catalog_revision_preflight_blocks_before_ensure` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_persists_partial_or_uncertain_failure_without_retry[ensure]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_persists_partial_or_uncertain_failure_without_retry[prepare]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_persists_partial_or_uncertain_failure_without_retry[confirm]` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_blocked_binding_receipt_never_publishes` (failure):  [alone: failed-again]
- `environment_setup/azurefactory-cli/tests/test_enrollment.py::test_wrapper_rejects_changed_binding_preview` (failure):  [alone: failed-again]
- Isolated re-run: 43 reproducible, 0 passed alone (flaky or order dependent)

### healthmodel - fail
Last pytest line: `3 failed, 549 passed, 5 skipped in 13.81s`
- `tests/test_bicep.py::test_main_template_compiles_without_warnings` (failure): assert ["/home/user/...quence '\\/'"] == [] [alone: failed-again]
- `tests/test_catalog.py::test_every_default_true_resource_flag_is_modelled` (failure): AssertionError: assert {'enableAFoun...Service', ...} == {'enableAFoun...Service', ...} [alone: failed-again]
- `tests/test_catalog.py::test_every_enable_flag_is_mapped_or_explained` (failure): AssertionError: assert {'enableAIFac...ersonas', ...} == set() [alone: failed-again]
- Isolated re-run: 3 reproducible, 0 passed alone (flaky or order dependent)

### mcp - fail
Last pytest line: `3 failed, 673 passed in 33.49s`
- `tests/test_backend.py::test_costs_use_real_cost_skill_and_bound_azure_resource_group` (failure): aifactory_mcp.backend.BackendError: The Factory request was rejected by the configured policy or service. [alone: failed-again]
- `tests/test_rollout_scaffold.py::test_native_command_resolves_azure_cli_batch_launcher_without_a_shell` (failure): RuntimeError: An unsupported batch launcher cannot be executed safely. [alone: failed-again]
- `tests/test_runtime.py::test_package_outside_checkout_requires_explicit_repository` (failure): Failed: DID NOT RAISE RuntimeError [alone: failed-again]
- Isolated re-run: 3 reproducible, 0 passed alone (flaky or order dependent)

### agent-factory - fail
Last pytest line: `4 failed, 599 passed, 19 skipped, 929 subtests passed in 27.04s`
- `tests/test_agent_live_voice.py::test_the_customer_configuration_overlays_the_generated_baseline` (failure): ModuleNotFoundError: No module named 'azurefactory' [alone: failed-again]
- `tests/test_agent_live_voice.py::test_the_generated_configuration_is_valid_for_the_applications_own_schema_with_voice_on` (failure): ModuleNotFoundError: No module named 'azurefactory' [alone: failed-again]
- `tests/test_agent_live_voice.py::test_the_command_line_reports_configuration_and_command_errors_in_one_line` (failure): TypeError: test_the_command_line_reports_configuration_and_command_errors_in_one_line.<locals>.<lambda>() got an unexpected keyword argument 'skip_incomplete' [alone: failed-again]
- `tests/test_mcp_gateway.py::IntegrationTests::test_runtime_settings_satisfy_the_mcp_image_settings_model` (failure): ModuleNotFoundError: No module named 'azurefactory' [alone: failed-again]
- Isolated re-run: 4 reproducible, 0 passed alone (flaky or order dependent)

### aifactory-agent - fail
Last pytest line: `17 failed, 1527 passed, 2 skipped, 2 warnings, 11 errors in 40.60s`
- `tests/test_config.py::test_relative_repository_root_is_config_relative` (failure): AssertionError: assert False [alone: failed-again]
- `tests/test_workloads.py::test_real_azureml_strategy_renders_canonical_pipeline_and_returns_running` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_real_model_strategy_unconfigured_inputs_never_submit[compute-workload_runtime_required]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_real_model_strategy_unconfigured_inputs_never_submit[environment-workload_runtime_required]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_real_model_strategy_unconfigured_inputs_never_submit[scenario-workload_selection_invalid]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_real_model_strategy_unconfigured_inputs_never_submit[workspace-workload_target_mismatch]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_real_model_strategy_unconfigured_inputs_never_submit[credentials-secret_in_workload_config]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_invalid_provider_runtime_has_safe_structured_blocker` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_model_never_guesses_output_scope_or_mutable_environment[lake-workload_output_scope_unapproved]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_model_never_guesses_output_scope_or_mutable_environment[latest-workload_runtime_required]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_private_ancestor_filter_is_identical_for_snapshot_and_packaging` (failure): assert not True [alone: failed-again]
- `tests/test_workloads.py::test_actual_aml_renderer_uses_only_immutable_staged_approved_sources` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_rendered_upload_must_exactly_match_approved_code_before_submit[extra]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_rendered_upload_must_exactly_match_approved_code_before_submit[changed]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_rendered_upload_must_exactly_match_approved_code_before_submit[code_path]` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_approved_vision_renderer_normalization_is_verified_without_false_drift` (failure): FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator\\scripts' [alone: failed-again]
- `tests/test_workloads.py::test_provider_code_is_compiled_from_verified_immutable_source_not_late_file_reads` (failure): StopIteration [alone: failed-again]
- `tests/test_graph_packaging.py::test_enabled_graph_packages_only_verified_immutable_snapshot_no_checkout` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_graph_packaging.py::test_enabled_graph_fail_closed_before_creating_bundle[corrupt]` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_graph_packaging.py::test_enabled_graph_fail_closed_before_creating_bundle[partial]` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_graph_packaging.py::test_enabled_graph_fail_closed_before_creating_bundle[mismatched]` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_graph_packaging.py::test_enabled_graph_fail_closed_before_creating_bundle[unpinned]` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_graph_packaging.py::test_moving_graph_root_must_be_fresh_but_fixed_snapshot_is_immutable` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_graph_packaging.py::test_broad_corpus_packaging_excludes_graph_and_test_material` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_skill_packaging.py::test_unpinned_canonical_template_is_bundled_with_the_checkouts_own_hash` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_skill_packaging.py::test_pinned_default_cost_template_is_in_cloud_bundle` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_skill_packaging.py::test_changed_default_cost_template_cannot_be_packaged` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- `tests/test_skill_packaging.py::test_only_approved_workload_source_entries_are_packaged` (error): failed on setup with "FileNotFoundError: [Errno 2] No such file or directory: '/home/user/wt-base/usecase_code/40-agent-factory/40-aifactory-agent/..\\..\\../environment_setup/aifactory/variables.json'" [alone: failed-again]
- Isolated re-run: 28 reproducible, 0 passed alone (flaky or order dependent)

### voice-sales-py - fail
Last pytest line: `1 failed, 104 passed, 3 warnings, 112 subtests passed in 29.87s`
- `tests/test_artifacts.py::ArtifactTests::test_primary_manifest_is_satisfied_by_reproducible_lock` (failure): importlib.metadata.PackageNotFoundError: No package metadata was found for pywin32 [alone: failed-again]
- Isolated re-run: 1 reproducible, 0 passed alone (flaky or order dependent)

### rag-48 - fail
Last pytest line: `25 failed, 232 passed, 3 skipped, 59 errors, 245 subtests passed in 12.50s`
- `tests/test_chunks.py::ChunkTests::test_bad_arrays_offsets_lengths_and_text_fail` (sub-test failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_chunks.py::ChunkTests::test_exclusively_record_boundary_cuts_do_not_prove_requirement` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_chunks.py::ChunkTests::test_gap_and_unicode_unit_confusion_fail` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_chunks.py::ChunkTests::test_incomplete_tail_and_missing_parent_or_bad_source_fail` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_chunks.py::ChunkTests::test_offline_fixture_exact_unicode_reconstruction_and_envelopes` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_chunks.py::ChunkTests::test_offline_normalized_excel_fixture_and_malformed_rows` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_chunks.py::ChunkTests::test_small_source_and_oversized_chunk_fail` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_search.py::ClientTests::test_runtime_real_verifier_with_offline_synthetic_unicode_arrays` (failure): AssertionError: Tokenizer downloads are prohibited in tests [alone: failed-again]
- `tests/test_sync_cli.py::SyncCliTests::test_content_then_permission_only_then_no_change_preserves_immutable_inputs` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_sync_cli.py::SyncCliTests::test_force_renew_is_explicitly_available_for_lifecycle_repair` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_sync_cli.py::SyncCliTests::test_notification_during_delta_never_commits_old_candidate` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_sync_cli.py::SyncCliTests::test_reconcile_rejects_unapproved_candidate_before_mutations` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_sync_cli.py::SyncCliTests::test_restored_source_after_quarantine_forces_acl_repair` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_sync_cli.py::SyncCliTests::test_source_deletion_stages_quarantine_not_a_partial_dataset` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_sync_cli.py::SyncCliTests::test_unrepresentable_permissions_quarantine_without_guessing_public_access` (failure): requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Failed to resolve 'opena [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_existing_output_refused_without_modification` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_image_docx_is_original_drawing_and_has_no_answer_in_document_text` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_independent_expected_decimal_totals_and_isolation` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_invalid_arguments_fail_without_publication` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_publication_shape_hashes_counts_and_token_budgets` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_reproducible_artifacts_and_separate_seed` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_six_library_layout_and_separate_overlap_fixture` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_dataset.py::DatasetTests::test_whole_workbook_rows_match_authoritative_jsonl` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_caller_cannot_override_content_derived_version` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_candidate_reproducible_and_existing_output_immutable` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_existing_loader_and_immutable_deployment_plan_accept_candidate` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_formula_workbook_fails_without_artifacts` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_missing_deleted_foreign_or_unsupported_source_never_publishes` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_mixed_versions_wrong_schema_bad_arithmetic_duplicate_rows_and_small_inputs` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_permission_only_change_keeps_input_hashes_and_version` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_version_changes_for_content_not_permissions_or_signed_url` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_graph_publication.py::GraphPublicationTests::test_whole_sources_derived_version_lineage_and_identical_copies` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_both_source_activity_without_both_references_is_not_evidence` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_changed_rows_fail_before_any_model_or_cloud_request` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_cli_has_no_implicit_mutation_or_paid_calls` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_cli_routes_full_text_control_without_retrieval_agent_invocation` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_configure_routes_by_partition_not_truncated_resource_name` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_empty_retrieval_cannot_count_as_a_successful_probe` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_failed_embedding_is_not_cached` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_full_text_control_fresh_runs_keep_separate_artifacts` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_full_text_control_propagates_model_failure_without_retry` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_full_text_control_rechecks_actual_payload_before_model_call` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_full_text_control_rejects_changed_agent_or_model_binding` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_full_text_control_requires_paid_and_corpus_approval` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_full_text_control_retains_incomplete_and_unexpected_tool_responses` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_full_text_control_sends_exact_live_text_without_tools_or_oracle` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_inference_and_writes_require_approval_before_network` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_knowledge_probe_uses_both_sources_and_no_permission_bypass_headers` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_native_ask_retains_raw_response_and_scoring_metadata` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_native_configuration_uses_two_scoped_indexers_and_never_pushes_documents` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_native_whole_table_preserves_every_source_byte_and_needs_no_operator_upload` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_partial_upload_can_resume_only_missing_exact_documents` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_real_document_readback_must_match_exact_expected_text` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_synthetic_project_corpus_requires_explicit_approval` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_two_sources_one_knowledge_base_no_local_function_tool` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_verify_checks_owned_sources_and_base_before_using_them` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_retrieval_experiment.py::RetrievalExperimentTests::test_whole_rows_cover_all_sources_without_text_split_or_totals` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_checker_cli_is_offline_and_refuses_data_or_input_overwrite` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_code_fenced_examples_and_unsupported_rows_do_not_count` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_correct_total_mentioned_in_prose_is_not_a_valid_audit` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_duplicate_and_contradictory_totals_are_rejected` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_duplicate_total_is_not_labelled_correct` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_full_audit_and_exact_totals_pass` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_known_header_variations_and_column_order_are_supported` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_malformed_raw_output_cannot_crash_or_pass` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_mcp_errors_fail_even_when_answer_matches` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_missing_metadata_failed_status_and_tools_do_not_pass` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_missing_or_duplicate_group_cannot_pass` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_oracle_mismatch_and_changed_authoritative_rows_fail` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_raw_responses_output_is_supported_without_hidden_reasoning_text` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_recorded_source_binding_must_match_fixture` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_unknown_source_or_range_and_oversized_group_fail` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_wrong_group_amount_is_reported_independently_of_correct_totals` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- `tests/test_sum_evaluation.py::SumEvaluationTests::test_wrong_money_count_or_currency_fails` (error): failed on setup with "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/cl100k_base.tiktoken (Caused by NameResolutionError("HTTPSConnection(host='openaipublic.blob.core.windows.net', port=443): Fa [alone: failed-again]
- Isolated re-run: 74 reproducible, 0 passed alone (flaky or order dependent)

### ml-churn-49 - fail
Last pytest line: `4 failed, 27 passed, 1 skipped, 13 warnings, 9 subtests passed in 28.08s`
- `tests/test_configuration.py::ConfigurationTests::test_init_config_binds_the_reviewed_scope_and_common_lake` (failure): AssertionError: False is not true [alone: failed-again]
- `tests/test_runtime.py::RuntimeTests::test_02_create_usecase_writes_the_m49_copy_and_publishes_synthetic_data` (failure): ValueError: Other generated factory files are stale or edited; run `python -m ml_model_factory usecase-examples` and review them first: usecase-type/batch/classification/azure-automl/azureml-pipeline-with-automl-step/churn-automl-pipeline.ipynb, usecase-type/batch/classification/azure-automl/azureml [alone: failed-again]
- `tests/test_runtime.py::RuntimeTests::test_03_training_registers_m49_once_and_resumes_from_receipts` (failure): ValueError: Create the use case first: synthetic data version aif49-synth-v1 is not published to the shared lake yet (create_usecase_from_template). [alone: failed-again]
- `tests/test_runtime.py::RuntimeTests::test_04_churn_inference_uploads_unlabeled_gold_once_and_reads_lake_predictions` (failure): ValueError: Train 49-agent-training-ml-churn-prediction in the approved plan before scoring it. [alone: failed-again]
- Isolated re-run: 4 reproducible, 0 passed alone (flaky or order dependent)

### ml-model-factory - fail
Last pytest line: `4 failed, 1031 passed, 53 skipped, 9716 warnings, 83 subtests passed in 321.44s (0:05:21)`
- `accelerator/tests/test_consumer_examples.py::test_synthetic_consumer_copy_renders_one_notebook_that_runs_dry` (failure): AssertionError: assert ['usecase-typ...l.ipynb', ...] == ['usecase-typ...ne/readme.md'] [alone: failed-again]
- `accelerator/tests/test_inference.py::test_vision_requests_carry_base64_images_and_reviewed_labels` (failure): ModuleNotFoundError: No module named 'PIL' [alone: failed-again]
- `accelerator/tests/test_monitoring.py::test_real_image_summary_shift` (failure): ModuleNotFoundError: No module named 'PIL' [alone: failed-again]
- `accelerator/tests/test_usecases.py::test_generated_notebooks_and_readmes_match_the_catalog` (failure): AssertionError: Run: python -m ml_model_factory usecase-examples --write [alone: failed-again]
- Isolated re-run: 4 reproducible, 0 passed alone (flaky or order dependent)

### tutorial-distribution-ps1 - not-run
Reason: Windows-only: Test-Distribution.ps1 drives scripts/Publish-TutorialApp.ps1, which requires Windows path semantics ($OutputRoot.StartsWith($root + '\'), regex '\\(artifacts|staging|private)'), subst.exe, pwsh.exe and Authenticode. Tried on Linux with pwsh 7.4.6 (offline, no parameters): it stops at the first Publish call with 'OutputRoot must be a child of this distribution directory'. Needs Windows 11 + PowerShell 7.4 (and, for the optional parts, the ESAIF.TutorialApp source and Inno Setup). --run-windows-only forces the attempt.

### agent-foundry-legacy - not-run
Reason: agent_01_rag_test.py is not a test: it has no test function or TestCase; it is a live sample script (DefaultAzureCredential, creates an AI Search index and a Foundry agent). Needs Azure login and deployed AI Foundry + AI Search; forbidden offline.

### automl-scoring-file - not-run
Reason: scoring_file_test.py is not a test: it is an Azure AutoML scoring script (init()/run()) for the 'test' environment, with no test function. It imports azureml.automl.core / inference_schema (Azure ML SDK v1 AutoML runtime) and needs a registered model file.

## Commands and environments

### azurefactory-cli (`environment_setup/azurefactory-cli`)
- Repo's own command: python -m pytest environment_setup/azurefactory-cli/tests/<files> -q  (deploy-docs.yml, repo root); readme: pip install -e .
- Executed (cwd `<worktree>/.`): `/home/user/tools/cienv.sh /home/user/venvs/azurefactory-cli/bin -- env PYTHONPATH=<worktree>/environment_setup/azurefactory-cli/src /home/user/venvs/azurefactory-cli/bin/python -m pytest environment_setup/azurefactory-cli/tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/azurefactory-cli/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/environment_setup/azurefactory-cli/src`
- venv `/home/user/venvs/azurefactory-cli`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/azurefactory-cli`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10 mkdocs-material setuptools wheel`
- Last summary line: `43 failed, 1765 passed, 12 skipped in 102.38s (0:01:42)`
- Skip reasons: Git Bash is unavailable; Optional canonical source contract validation; Optional canonical source roundtrip
- Note: Package has no dependencies; azurefactory comes from <worktree>/src (tests/conftest.py + PYTHONPATH).

### graphify (`environment_setup/graphify`)
- Repo's own command: no documented test command; environment per documentation/architecture/contracts/dual-graph-lifecycle.md (uv venv --python 3.12; pip install -r requirements.lock.txt), repo root
- Executed (cwd `<worktree>/.`): `/home/user/tools/cienv.sh /home/user/venvs/graphify/bin -- /home/user/venvs/graphify/bin/python -m pytest environment_setup/graphify/tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/graphify/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/graphify`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/graphify`
  - `uv pip install --python <venv>/bin/python -r <worktree>/environment_setup/graphify/requirements.txt -c <worktree>/environment_setup/graphify/requirements.lock.txt  [FALLBACK: alternative 2; earlier alternatives failed]`
- Last summary line: `30 passed in 8.35s`

### wizard-api-usage-examples (`environment_setup/install_config_wizard/api-usage-examples`)
- Repo's own command: python -m pytest .\tests ..\..\azurefactory-cli\tests\test_{cli,client,reviews,quickstart_examples}.py -q --basetemp .local\pytest-work  (readme, from this folder)
- Executed (cwd `<worktree>/environment_setup/install_config_wizard/api-usage-examples`): `/home/user/tools/cienv.sh /home/user/venvs/wizard-api-usage-examples/bin -- env PYTHONPATH=<worktree>/environment_setup/azurefactory-cli/src /home/user/venvs/wizard-api-usage-examples/bin/python -m pytest ./tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/wizard-api-usage-examples/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/environment_setup/azurefactory-cli/src`
- venv `/home/user/venvs/wizard-api-usage-examples`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/wizard-api-usage-examples`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10`
- Last summary line: `148 passed, 20 skipped in 16.22s`
- Skip reasons: Optional authoritative model validation; Optional master-source contract validation
- Note: Deviation: the four azurefactory-cli files of the readme command run in suite azurefactory-cli, and --basetemp .local/pytest-work is dropped so that nothing is written into the worktree.

### bicep-automation (`environment_setup/aifactory/bicep/copy_to_local_settings/automation`)
- Repo's own command: no documented command; tests import sibling modules, so they run from the automation folder
- Executed (cwd `<worktree>/environment_setup/aifactory/bicep/copy_to_local_settings/automation`): `/home/user/tools/cienv.sh /home/user/venvs/bicep-automation/bin -- /home/user/venvs/bicep-automation/bin/python -m pytest . -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/bicep-automation/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/bicep-automation`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/bicep-automation`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10`
- Last summary line: `145 passed in 9.83s`

### esml-v2 (`esml-v2`)
- Repo's own command: python -m pytest from esml-v2 ([tool.pytest.ini_options] testpaths=tests, pythonpath=., ../usecase_code/50-ml-model-factory/accelerator/src)
- Executed (cwd `<worktree>/esml-v2`): `/home/user/tools/cienv.sh /home/user/venvs/esml-v2/bin -- env PYTHONPATH=<worktree>/esml-v2:<worktree>/usecase_code/50-ml-model-factory/accelerator/src /home/user/venvs/esml-v2/bin/python -m pytest -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/esml-v2/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/esml-v2:/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator/src`
- venv `/home/user/venvs/esml-v2`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/esml-v2`
  - `uv pip install --python <venv>/bin/python -r <worktree>/esml-v2/pyproject.toml --extra train --extra storage --extra dev`
  - `uv pip install --python <venv>/bin/python six`
  - `uv pip install --python <venv>/bin/python Pillow>=11,<13`
  - `uv pip install --python <venv>/bin/python setuptools>=77 wheel`
- Last summary line: `952 passed, 51483 warnings in 263.73s (0:04:23)`
- Note: PYTHONPATH = what an installed azure-esml-sdk provides (azure_esml + bundled ml_model_factory), taken from the worktree: one test starts `python -m azure_esml.domain_layer.runtime` as a subprocess, which does not see pytest's own pythonpath setting.

### healthmodel (`healthmodel`)
- Repo's own command: cd healthmodel; python -m pytest  (readme section 14; addopts=-q, pythonpath=src,tests; live tests opt in with AIF_HEALTHMODEL_LIVE=1)
- Executed (cwd `<worktree>/healthmodel`): `/home/user/tools/cienv.sh /home/user/venvs/healthmodel/bin -- /home/user/venvs/healthmodel/bin/python -m pytest --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/healthmodel/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/healthmodel`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/healthmodel`
  - `uv pip install --python <venv>/bin/python -r <worktree>/healthmodel/pyproject.toml --extra test`
- Last summary line: `3 failed, 549 passed, 5 skipped in 13.81s`
- Skip reasons: could not import 'jsonschema': No module named 'jsonschema'; set AIF_HEALTHMODEL_LIVE=1 and AIF_HEALTHMODEL_ID to run live tests; write test is opt-in

### mcp (`mcp`)
- Repo's own command: & $Python -m pytest -q from mcp (readme); install: pip install -r ../usecase_code/40-agent-factory/40-aifactory-agent/requirements.txt -e ../environment_setup/azurefactory-cli -e .[dev]
- Executed (cwd `<worktree>/mcp`): `/home/user/tools/cienv.sh /home/user/venvs/mcp/bin -- env PYTHONPATH=<worktree>/mcp/src:<worktree>/environment_setup/azurefactory-cli/src /home/user/venvs/mcp/bin/python -m pytest -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/mcp/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/mcp/src:/home/user/wt-base/environment_setup/azurefactory-cli/src`
- venv `/home/user/venvs/mcp`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/mcp`
  - `uv pip install --python <venv>/bin/python -r <worktree>/mcp/deploy/requirements.linux.lock.txt`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10`
- Last summary line: `3 failed, 673 passed in 33.49s`

### func-aifactory-lifecycle (`usecase_code/10-azure-function/12_func_aifactory_lifecycle`)
- Repo's own command: python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt (README); pytest from the folder
- Executed (cwd `<worktree>/usecase_code/10-azure-function/12_func_aifactory_lifecycle`): `/home/user/tools/cienv.sh /home/user/venvs/func-aifactory-lifecycle/bin -- /home/user/venvs/func-aifactory-lifecycle/bin/python -m pytest tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/func-aifactory-lifecycle/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/func-aifactory-lifecycle`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/func-aifactory-lifecycle`
  - `install_func_requirements_pinned_sdk_sparse()  # requirements-dev.txt; the git-pinned azurefactory-cli is built from a shallow, sparse checkout of that commit.`
- Last summary line: `380 passed in 24.98s`
- Note: As the component declares it: the azurefactory SDK is the commit pinned in requirements.txt, fetched from GitHub at venv build time, NOT the worktree's SDK (tests/conftest.py prefers an installed SDK).

### func-aifactory-lifecycle-wt-sdk (`usecase_code/10-azure-function/12_func_aifactory_lifecycle`)
- Repo's own command: variant of func-aifactory-lifecycle: tests/conftest.py falls back to the SDK of the accelerator checkout when azurefactory is not installed
- Executed (cwd `<worktree>/usecase_code/10-azure-function/12_func_aifactory_lifecycle`): `/home/user/tools/cienv.sh /home/user/venvs/func-aifactory-lifecycle-wt-sdk/bin -- /home/user/venvs/func-aifactory-lifecycle-wt-sdk/bin/python -m pytest tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/func-aifactory-lifecycle-wt-sdk/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/func-aifactory-lifecycle-wt-sdk`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/func-aifactory-lifecycle-wt-sdk`
  - `install_func_requirements_without_sdk()  # requirements-dev.txt minus the azurefactory-cli line (the SDK then comes from the worktree).`
- Last summary line: `380 passed in 24.52s`
- Note: Same tests, but the azurefactory SDK comes from <worktree>/environment_setup/azurefactory-cli/src (conftest fallback), so SDK changes of the worktree are exercised.

### agent-factory (`usecase_code/40-agent-factory`)
- Repo's own command: .\.venv\Scripts\python.exe -m unittest discover -s tests  from 40-agent-factory, Python 3.13 (tests/readme.md)
- Executed (cwd `<worktree>/usecase_code/40-agent-factory`): `/home/user/tools/cienv.sh /home/user/venvs/agent-factory/bin -- /home/user/venvs/agent-factory/bin/python -m pytest tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/agent-factory/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/agent-factory`, Python 3.13, built
  - `uv venv --seed --python 3.13 /home/user/venvs/agent-factory`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/40-agent-factory/requirements.txt`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10 PyYAML`
- Last summary line: `4 failed, 599 passed, 19 skipped, 929 subtests passed in 27.04s`
- Skip reasons: Optional: install example requirements in an isolated venv.; example requirements not installed: No module named 'dotenv'
- Note: Documented operator environment only. Three pytest-style tests import 40-aifactory-agent and therefore need its runtime (azurefactory SDK, httpx, ...), which requirements.txt does not install; the two environments must not be merged according to the agent readme.

### aifactory-agent (`usecase_code/40-agent-factory/40-aifactory-agent`)
- Repo's own command: .\.venv\Scripts\python.exe -m pytest -q tests  from 40-aifactory-agent, Python 3.12 (readme); install: pip install -r requirements.lock.txt; pip install -e ..\..\..\environment_setup\azurefactory-cli
- Executed (cwd `<worktree>/usecase_code/40-agent-factory/40-aifactory-agent`): `/home/user/tools/cienv.sh /home/user/venvs/aifactory-agent/bin -- env PYTHONPATH=<worktree>/environment_setup/azurefactory-cli/src /home/user/venvs/aifactory-agent/bin/python -m pytest tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/aifactory-agent/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/environment_setup/azurefactory-cli/src`
- venv `/home/user/venvs/aifactory-agent`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/aifactory-agent`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/40-agent-factory/40-aifactory-agent/requirements.lock.txt`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10`
- Last summary line: `17 failed, 1527 passed, 2 skipped, 2 warnings, 11 errors in 40.60s`
- Skip reasons: Windows reparse-point regression

### voice-sales-py (`usecase_code/40-agent-factory/40-foundry-voice-sales--from-fabric`)
- Repo's own command: Start-FoundryVoiceSales.ps1 -Action Test: python -m unittest discover -s tests -p test_*.py (Python 3.13, pip install -r requirements.lock.txt), then node --test tests/frontend*.test.js
- Executed (cwd `<worktree>/usecase_code/40-agent-factory/40-foundry-voice-sales--from-fabric`): `/home/user/tools/cienv.sh /home/user/venvs/voice-sales-py/bin -- /home/user/venvs/voice-sales-py/bin/python -m pytest tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/voice-sales-py/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/voice-sales-py`, Python 3.13, built
  - `uv venv --seed --python 3.13 /home/user/venvs/voice-sales-py`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/40-agent-factory/40-foundry-voice-sales--from-fabric/requirements.txt -c <worktree>/usecase_code/40-agent-factory/40-foundry-voice-sales--from-fabric/requirements.lock.txt  [FALLBACK: alternative 2; earlier alternatives failed]`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10`
- Last summary line: `1 failed, 104 passed, 3 warnings, 112 subtests passed in 29.87s`
- New paths in the worktree after the run: `?? .offline-bicep-work-fcbfc8f87d4a4abcb1ef6122ebe37b1e/`

### voice-sales-frontend-js (`usecase_code/40-agent-factory/40-foundry-voice-sales--from-fabric`)
- Repo's own command: npm test = node --test tests/frontend*.test.js (package.json; Node 22, no npm dependencies)
- Executed (cwd `<worktree>/usecase_code/40-agent-factory/40-foundry-voice-sales--from-fabric`): `/home/user/tools/cienv.sh -- /opt/node22/bin/node --test --test-reporter=spec --test-reporter-destination=stdout --test-reporter=junit --test-reporter-destination=/home/user/results/base/components/voice-sales-frontend-js/junit.xml tests/frontend-api.test.js tests/frontend-audio.test.js tests/frontend-branding.test.js tests/frontend-render.test.js tests/frontend-voice.test.js`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- Last summary line: `tests 46, pass 46, fail 0, cancelled 0, skipped 0, todo 0`

### rag-48 (`usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2`)
- Repo's own command: & $Python -m unittest discover -s tests  from the folder, Python 3.13, TIKTOKEN_CACHE_DIR=.venv\tiktoken-cache (readme); tests/service and tests/live are unittest classes that skip unless AIF48_SERVICE_TESTS / AIF48_GRAPH_SERVICE_TESTS / AIF48_LIVE_EVALUATIONS+AIF48_ALLOW_PAID are set
- Executed (cwd `<worktree>/usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2`): `/home/user/tools/cienv.sh /home/user/venvs/rag-48/bin -- env TIKTOKEN_CACHE_DIR=/home/user/venvs/.cache/tiktoken-cache /home/user/venvs/rag-48/bin/python -m pytest tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/rag-48/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `TIKTOKEN_CACHE_DIR=/home/user/venvs/.cache/tiktoken-cache`
- venv `/home/user/venvs/rag-48`, Python 3.13, built
  - `uv venv --seed --python 3.13 /home/user/venvs/rag-48`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/40-agent-factory/48-rag-with-splitted-tables-acl-adlsgen2/requirements.txt`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10`
- Last summary line: `25 failed, 232 passed, 3 skipped, 59 errors, 245 subtests passed in 12.50s`
- Skip reasons: Deployed-agent evaluations require explicit paid-call opt-in.; Real Azure service tests are opt-in.; Real Graph source reads require explicit scope-bound approval.
- New paths in the worktree after the run: `?? .lifecycle-offline-390a3423-d957-4a0c-a77c-72ebc6bedd7b/`
- Note: tiktoken needs the cl100k_base encoding file. It is read from TIKTOKEN_CACHE_DIR (<venvs>/.cache/tiktoken-cache, file name 9b5ad71b2ce5302211f9c61530b329a4922fc6a4 = sha1 of https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken) or downloaded from that URL on first use; the runner never downloads it.

### ml-churn-49 (`usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction`)
- Repo's own command: pip install -r requirements.txt "..\..\..\esml-v2[train,storage,dev]"; python -m unittest discover -s tests  (readme); tests/live skips unless AIF49_LIVE=1 and AIF49_CONFIG
- Executed (cwd `<worktree>/usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction`): `/home/user/tools/cienv.sh /home/user/venvs/ml-churn-49/bin -- env PYTHONPATH=<worktree>/esml-v2:<worktree>/usecase_code/50-ml-model-factory/accelerator/src /home/user/venvs/ml-churn-49/bin/python -m pytest tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/ml-churn-49/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/esml-v2:/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator/src`
- venv `/home/user/venvs/ml-churn-49`, Python 3.13, built
  - `uv venv --seed --python 3.13 /home/user/venvs/ml-churn-49`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/40-agent-factory/49-agent-training-ml-churn-prediction/requirements.txt`
  - `uv pip install --python <venv>/bin/python -r <worktree>/esml-v2/pyproject.toml --extra train --extra storage --extra dev`
  - `uv pip install --python <venv>/bin/python six`
- Last summary line: `4 failed, 27 passed, 1 skipped, 13 warnings, 9 subtests passed in 28.08s`
- Skip reasons: Set AIF49_LIVE=1 and AIF49_CONFIG=<consumer config.json> for read-only live checks
- Note: The readme installs the built ESML SDK (bundles ml_model_factory). The runner puts <worktree>/esml-v2 and <worktree>/usecase_code/50-ml-model-factory/accelerator/src on PYTHONPATH instead (same sources).

### ml-model-factory (`usecase_code/50-ml-model-factory`)
- Repo's own command: python -m pip install -e ".[train,azure,dev]"; python -m pytest  from 50-ml-model-factory (readme); pytest config: testpaths=accelerator/tests, pythonpath=accelerator/src,accelerator
- Executed (cwd `<worktree>/usecase_code/50-ml-model-factory`): `/home/user/tools/cienv.sh /home/user/venvs/ml-model-factory/bin -- env PYTHONPATH=<worktree>/usecase_code/50-ml-model-factory/accelerator/src /home/user/venvs/ml-model-factory/bin/python -m pytest -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/ml-model-factory/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator/src`
- venv `/home/user/venvs/ml-model-factory`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/ml-model-factory`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/50-ml-model-factory/pyproject.toml --extra train --extra azure --extra dev --extra kaggle`
  - `uv pip install --python <venv>/bin/python six`
  - `uv pip install --python <venv>/bin/python setuptools>=75 wheel`
- Last summary line: `4 failed, 1031 passed, 53 skipped, 9716 warnings, 83 subtests passed in 321.44s (0:05:21)`
- Skip reasons: could not import 'PIL.Image': No module named 'PIL'; could not import 'torch': No module named 'torch'; could not import 'torchmetrics': No module named 'torchmetrics'
- Note: PYTHONPATH = the folder an editable install exposes (accelerator/src of the worktree): tests start `python -m ml_model_factory` as a subprocess, which does not see pytest's own pythonpath setting. The `vision` extra (torch, torchvision, torchmetrics, pycocotools, Pillow) is not installed: the vision tests skip through the repo's own importorskip('PIL.Image'). Installing Pillow alone would turn those skips into failures ('Vision training requires the declared [train,vision] extras').

### mlops-2026-09 (`copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09`)
- Repo's own command: model-factory .venv python: -m unittest discover -s <template>\tests -v (ado/github ml-factory.yml); documentation/v2/30-39/36-dataops.md runs it with pytest from the model-factory root
- Executed (cwd `<worktree>/usecase_code/50-ml-model-factory`): `/home/user/tools/cienv.sh /home/user/venvs/mlops-2026-09/bin -- env PYTHONPATH=<worktree>/usecase_code/50-ml-model-factory/accelerator/src:<worktree>/usecase_code/50-ml-model-factory/accelerator /home/user/venvs/mlops-2026-09/bin/python -m pytest ../../copy_my_subfolders_to_my_grandparent/mlops/03_mlops_2026-09/tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/mlops-2026-09/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator/src:/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator`
- venv `/home/user/venvs/mlops-2026-09`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/mlops-2026-09`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/50-ml-model-factory/pyproject.toml --extra train --extra azure --extra dev --extra kaggle`
  - `uv pip install --python <venv>/bin/python six`
  - `uv pip install --python <venv>/bin/python setuptools>=75 wheel`
- Last summary line: `51 passed, 40 subtests passed in 15.46s`

### dataops-adf (`copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory`)
- Repo's own command: python -m unittest discover -s "$templates\tests" -v (azure-datafactory/readme.md); documentation/v2/30-39/36-dataops.md runs it with pytest from the model-factory root
- Executed (cwd `<worktree>/usecase_code/50-ml-model-factory`): `/home/user/tools/cienv.sh /home/user/venvs/dataops-adf/bin -- env PYTHONPATH=<worktree>/usecase_code/50-ml-model-factory/accelerator/src:<worktree>/usecase_code/50-ml-model-factory/accelerator /home/user/venvs/dataops-adf/bin/python -m pytest ../../copy_my_subfolders_to_my_grandparent/dataops/azure-datafactory/tests -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/dataops-adf/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `PYTHONPATH=/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator/src:/home/user/wt-base/usecase_code/50-ml-model-factory/accelerator`
- venv `/home/user/venvs/dataops-adf`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/dataops-adf`
  - `uv pip install --python <venv>/bin/python -r <worktree>/usecase_code/50-ml-model-factory/pyproject.toml --extra train --extra azure --extra dev --extra kaggle`
  - `uv pip install --python <venv>/bin/python six`
  - `uv pip install --python <venv>/bin/python setuptools>=75 wheel`
- Last summary line: `15 passed, 12 subtests passed in 3.59s`

### onion (`documentation/v2/10-19/images/onion`)
- Repo's own command: python -m unittest test_onion.py from the onion folder (documentation/v2/10-19/10-factory-onion-architecture-v2.md)
- Executed (cwd `<worktree>/documentation/v2/10-19/images/onion`): `/home/user/tools/cienv.sh /home/user/venvs/onion/bin -- /home/user/venvs/onion/bin/python -m pytest test_onion.py -q --tb=short -p no:cacheprovider --junitxml=/home/user/results/base/components/onion/junit.xml`
- Test environment: `/home/user/tools/cienv.sh <venv bin> --` (env -i, CI-like); suite variables passed inside: `none`
- venv `/home/user/venvs/onion`, Python 3.12, built
  - `uv venv --seed --python 3.12 /home/user/venvs/onion`
  - `uv pip install --python <venv>/bin/python pytest>=8,<10`
- Last summary line: `21 passed in 0.13s`

### tutorial-distribution-ps1 (`environment_setup/install_tutorial_guide`)
- Repo's own command: .\tests\Test-Distribution.ps1 [-SourceRoot <ESAIF.TutorialApp source>] [-ExercisePackaging] (README.packaging-draft.md); run without parameters: the app source is not in this repository

### agent-foundry-legacy (`usecase_code/20-agent-foundry/_legacy`)

### automl-scoring-file (`copy_my_subfolders_to_my_grandparent/settings/project_specific/model/dev_test_prod/train/automl`)

`git status --porcelain` after the run: empty
