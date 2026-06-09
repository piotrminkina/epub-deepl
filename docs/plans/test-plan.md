# Test Plan — epub-deepl-prepare

**Status:** Draft v1
**Related:** `prd.md` (US-001…US-017, SM-1…SM-6), `tech-stack.md`, `tech-spec.md`

---

## 1. Overview and Goals

The test suite validates two properties simultaneously:

1. **Functional correctness** — every user story has at least one test that
   exercises its acceptance criteria.
2. **Structural fidelity** — round-trip transformations preserve EPUB
   structure at byte level for everything not explicitly translated.

The suite is layered: fast unit tests for individual algorithms, integration
tests for end-to-end CLI behaviour, and corpus tests against real-world
EPUBs in `/tmp/nowe`.

**Coverage target:** ≥ 85% statement coverage across `src/`, with 100%
coverage on `epub/validator.py` and `epub/writer.py` (the highest-risk
modules).

---

## 2. Test Pyramid

```
                ┌──────────────────────────┐
                │   Manual: epubcheck      │   ← out-of-band, user-run
                ├──────────────────────────┤
                │   Integration (corpus)   │   ← /tmp/nowe books, slow
                ├──────────────────────────┤
                │   Integration (CLI)      │   ← argparse → exit code
                ├──────────────────────────┤
                │   Integration (synth)    │   ← synthetic minimal EPUB
                ├──────────────────────────┤
                │   Unit                   │   ← per-module, fast
                └──────────────────────────┘
```

| Layer | Test count target | Avg duration |
|---|---|---|
| Unit | ~50 tests | < 5 s total |
| Integration (synth) | ~25 tests | < 10 s total |
| Integration (CLI) | ~15 tests | < 15 s total |
| Integration (corpus) | ~15 tests (~4 books × ~3 scenarios) | < 60 s total |

Total: ~105 tests, < 90 s wall-clock with `pytest-xdist`.

---

## 3. Tooling and Layout

### Framework

- **`pytest` ≥ 8** with `pytest-cov` and `pytest-xdist`
- Naming: `test_<subject>.py` (pytest standard).
- Layout: `tests/unit/` and `tests/integration/` (matching tech-spec §2).

### Fixtures (`tests/conftest.py`)

- `corpus_dir`: session-scoped `Path` to `/tmp/nowe`; skips integration
  corpus tests if directory missing or contains no `.epub` files.
- `corpus_epubs`: parametrized fixture yielding each `.epub` file in
  corpus, with a clear `id` (book filename) for test report readability.
- `synth_epub_factory`: function-scoped factory that builds a minimal
  in-memory EPUB 2.0 ZIP from declarative parameters
  (`{xhtmls: [...], opf_metadata: {...}, ncx_navpoints: [...]}`).
- `tmp_epub`: function-scoped temp file path for write tests.

### Synthetic fixture builder

The factory in `tests/fixtures/minimal.py` constructs a valid EPUB 2.0
ZIP entirely in memory:

```python
def build_minimal_epub(
    titles=("Test Book",),
    descriptions=("Test description",),
    subjects=("test", "fiction"),
    language="en",
    creators=("Anonymous",),
    xhtmls=None,          # list of (href, body_html, [(heading_id, heading_text), ...])
    nav_map=None,         # list of (label, src_href_with_fragment)
    extra_files=None,     # dict[zip_path] -> bytes (CSS, images)
) -> bytes:
    """Return raw EPUB bytes."""
```

This factory is the foundation of all unit and synth-integration tests
— it produces a known-good baseline that we can mutate to inject specific
edge cases.

### Markers

- `@pytest.mark.unit` — default; fast.
- `@pytest.mark.integration` — uses synthetic EPUB.
- `@pytest.mark.corpus` — uses `/tmp/nowe`; runnable only when corpus is
  present; deselected by default in `pyproject.toml` to keep `pytest`
  invocation fast unless `pytest -m corpus` or `pytest -m ''` is used.

---

## 4. User Story Coverage Matrix

Every PRD acceptance criterion maps to at least one test case. The
mapping is non-redundant: a single test may verify criteria from multiple
stories, but every criterion must be explicitly asserted somewhere.

| US | Test module | Test function(s) | Layer |
|---|---|---|---|
| US-001 | `integration/test_cli.py` | `test_prepare_emits_html_file`, `test_prepare_html_has_section_per_spine_item`, `test_prepare_html_head_contains_title_and_description`, `test_prepare_html_nav_block_carries_ncx_data` | Integration (synth) |
| US-002 | `integration/test_cli.py` | `test_restore_emits_epub_file`, `test_restored_body_replaces_input_body`, `test_restored_opf_has_translated_metadata`, `test_restored_zip_mimetype_first_stored` | Integration (synth) |
| US-003 | `unit/test_validator.py` | `test_validate_rejects_drm_protected_epub` | Unit |
| US-004 | `unit/test_validator.py` | `test_validate_rejects_manifest_with_missing_file`, `test_validate_lists_all_missing_files` | Unit |
| US-005 | `unit/test_validator.py` | `test_validate_rejects_spine_with_unresolved_idref` | Unit |
| US-006 | `integration/test_roundtrip.py` | `test_roundtrip_without_translation_is_content_identical[corpus]` (parametrized across `/tmp/nowe`), `test_roundtrip_without_translation_synth_minimal`, `test_roundtrip_without_translation_synth_with_nested_ncx`, `test_roundtrip_without_translation_synth_with_mathml` | Integration (synth + corpus) |
| US-007 | `integration/test_cli.py` | `test_restored_opf_has_translated_metadata` (shared with US-002), `test_restored_metadata_subject_count_preserved` | Integration |
| US-008 | `unit/test_anchor_resolution.py` | `test_resolve_label_with_fragment`, `test_resolve_label_without_fragment_uses_first_heading`, `test_resolve_label_no_fragment_no_heading_falls_back_to_flat_label`, `test_resolve_label_per_file_scoping_prevents_id_collisions`, `test_resolve_label_normalizes_whitespace` | Unit |
| US-009 | `unit/test_opf.py` | `test_opf_set_language_replaces_first_dc_language`, `test_opf_set_language_removes_extras_when_multiple_present` | Unit |
| US-010 | `unit/test_opf.py` | `test_opf_preserves_non_translated_fields_byte_identical[creator]`, `test_opf_preserves_non_translated_fields_byte_identical[publisher]`, `test_opf_preserves_non_translated_fields_byte_identical[identifier]`, `test_opf_preserves_non_translated_fields_byte_identical[date]`, `test_opf_preserves_non_translated_fields_byte_identical[rights]`, `test_opf_preserves_opf_namespaced_attributes` | Unit |
| US-011 | `integration/test_roundtrip.py` | `test_mathml_receives_translate_no_in_prepare`, `test_mathml_byte_identical_after_restore` | Integration (synth) |
| US-012 | `integration/test_cli.py` | `test_ruby_annotations_emit_warning_to_stderr`, `test_ruby_does_not_affect_exit_code` | Integration (synth) |
| US-013 | `integration/test_roundtrip.py` | `test_manifest_element_byte_identical_after_roundtrip`, `test_spine_element_byte_identical_after_roundtrip` | Integration |
| US-014 | `integration/test_cli.py` | `test_default_output_naming_prepare`, `test_default_output_naming_restore`, `test_output_flag_overrides_default`, `test_existing_output_without_force_fails_fast`, `test_existing_output_with_force_overwrites` | Integration (CLI) |
| US-015 | `integration/test_cli.py` | `test_no_args_shows_usage_with_both_subcommands`, `test_prepare_help_lists_all_flags`, `test_restore_help_lists_all_flags` | Integration (CLI) |
| US-016 | `integration/test_roundtrip.py` | (verified manually — documented test recipe) | Manual |
| US-017 | N/A | (PRD compliance only; no functional test) | N/A |

---

## 5. Success Metric Coverage

| SM | Verification | Automated? | Test reference |
|---|---|---|---|
| SM-1 | Round-trip integrity (no translation) on full corpus | Yes | `test_roundtrip_without_translation_is_content_identical[corpus]` |
| SM-2 | Translation completeness | Partial; structural integrity automated, translation completeness verified by `simulated_translation` fixture (deterministic regex replacement) and manual sampling on real DeepL output | `test_simulated_translation_completeness` |
| SM-3 | TOC ↔ heading consistency (byte-equal, normalized whitespace) | Yes | `test_navlabel_matches_heading_text_after_simulated_translation` |
| SM-4 | EPUB validity via `epubcheck` | Manual | Documented recipe in `tests/integration/README.md`; CI integration deferred |
| SM-5 | DeepL quota economy (1 doc per book) | Manual | Documented as user-observable property; no test |
| SM-6 | CLI turnaround < 60 s | Yes | `test_cli_turnaround_per_book[corpus]` with `pytest-benchmark` or simple `time.monotonic()` wrapper |

### Simulated translation strategies (two-tier fixture)

For automated tests that verify "post-translation" behaviour without
invoking DeepL, two fixtures are used in combination. Together they
close the gap raised by the devils-advocate review (C-4 and I-4).

**Tier 1: `simulated_translation` (friendly).** Prefixes every
translatable text node in the merged HTML with `«PL»`. Verifies that
`restore` finds, extracts, and applies translations to every expected
location; that anchor resolution pulls `«PL»`-prefixed text; and that
non-translated fields do not pick up the marker.

**Tier 2: `adversarial_translation` (hostile).** Simulates the worst
plausible DeepL behaviour. Applies, in random combinations per test
run (seeded for reproducibility):

- Strips one randomly-chosen `data-*` attribute from a `<section>` (R-8
  primary failure mode).
- Reorders all attributes alphabetically on every element.
- Collapses runs of whitespace into single spaces, including in
  `<pre>` blocks where it must NOT happen.
- Re-encodes some HTML entities to their NCR equivalents (`&mdash;` →
  `&#8212;`) and vice versa.
- Strips all HTML comments.
- Wraps the entire document in a `<div class="deepl-output">` (DeepL
  has been observed adding wrapper elements).
- Replaces text containing the prefix in the `simulated_translation`
  output with intentionally split element boundaries (one paragraph
  becomes two consecutive paragraphs).

The adversarial fixture's contract: restore must either **succeed
correctly** OR **fail with a precise, user-actionable error message
naming the exact section that triggered the failure** — never crash
with an opaque traceback, never silently corrupt output.

Together, the two-tier strategy ensures that the simulated layer
exercises both the happy path (friendly fixture) and the worst-case
DeepL deviation (adversarial fixture). SM-7 from the PRD is verified
exclusively via the adversarial fixture.

---

## 6. Unit Test Specifications

### 6.1 `tests/unit/test_opf.py`

- `test_parse_extracts_all_dc_titles_in_order`
- `test_parse_extracts_descriptions_subjects_creators`
- `test_parse_preserves_opf_namespaced_meta_extensions`
- `test_set_language_replaces_first_dc_language`
- `test_set_language_removes_extras_when_multiple`
- `test_apply_translated_metadata_count_mismatch_raises`
- `test_apply_translated_metadata_preserves_non_translated_byte_identical`
- `test_opf_serialization_preserves_xml_declaration`
- `test_opf_serialization_preserves_extension_namespaces` (Calibre, Apple)

### 6.2 `tests/unit/test_ncx.py`

- `test_parse_flat_navmap`
- `test_parse_nested_navmap_depth_3`
- `test_parse_preserves_play_order`
- `test_serialize_replaces_navlabel_text_only`
- `test_serialize_preserves_dtb_meta_uid`
- `test_serialize_preserves_attribute_ordering`

### 6.3 `tests/unit/test_anchor_resolution.py`

- `test_resolve_label_with_fragment`
- `test_resolve_label_with_fragment_resolves_to_correct_id`
- `test_resolve_label_with_fragment_returns_normalized_whitespace`
- `test_resolve_label_without_fragment_uses_first_heading`
- `test_resolve_label_h2_used_when_no_h1`
- `test_resolve_label_h3_used_when_no_h1_h2`
- `test_resolve_label_no_heading_falls_back_to_flat_label`
- `test_resolve_label_missing_fragment_walks_to_heading_ancestor`
- `test_resolve_label_missing_fragment_no_heading_falls_back_to_flat_label`
- `test_resolve_label_id_collision_across_files_scoped_per_file`
  *(critical — mitigates R-4)*
- `test_resolve_label_src_with_no_target_file_raises_internal_error`

### 6.4 `tests/unit/test_zip_packaging.py`

These tests are also re-run on every roundtrip integration output
(see §7.2 `test_zip_packaging_invariants_hold_after_roundtrip`) to
close the gap identified by devils-advocate C-1: SM-1's unzipped-diff
check is blind to ZIP-level violations.

- `test_mimetype_is_first_entry`
- `test_mimetype_is_stored_compression`
- `test_mimetype_has_no_extra_field`
- `test_mimetype_byte_content_exact`
- `test_mimetype_general_purpose_flag_zero`
  *(critical — older epubcheck regression vector)*
- `test_other_entries_are_deflated`
- `test_zip_can_be_reopened_and_read_back`
- `test_zip_testzip_returns_none` (no CRC errors)

### 6.5 `tests/unit/test_validator.py`

- `test_validate_accepts_minimal_synthetic_epub`
- `test_validate_rejects_non_zip_file`
- `test_validate_rejects_missing_mimetype`
- `test_validate_rejects_wrong_mimetype_content`
- `test_validate_rejects_missing_container_xml`
- `test_validate_rejects_unparseable_opf`
- `test_validate_rejects_drm_protected_epub`
- `test_validate_rejects_manifest_with_missing_file`
- `test_validate_lists_all_missing_files_in_error`
- `test_validate_rejects_spine_with_unresolved_idref`
- `test_validate_rejects_missing_ncx`
- `test_validate_rejects_unparseable_ncx`
- `test_validate_translated_html_missing_sections`
- `test_validate_translated_html_unknown_sections`
- `test_validate_translated_html_title_count_mismatch`

### 6.6 `tests/unit/test_xhtml.py`

- `test_extract_body_inner_returns_html5_string`
- `test_extract_body_inner_preserves_inline_namespaces`
- `test_replace_body_preserves_root_attributes`
- `test_replace_body_preserves_head_unchanged`
- `test_replace_body_handles_empty_body`

### 6.7 `tests/unit/test_safe_parser.py`

- `test_parser_blocks_external_entity_reference`
- `test_parser_blocks_dtd_loading`
- `test_parser_blocks_network_access`
- `test_parser_rejects_huge_tree`

### 6.8 `tests/unit/test_bcp47.py`

Well-formedness check (per BCP 47 grammar; not registry lookup) and
primary-subtag extraction. Powers the US-009 lang resolver.

- `test_is_well_formed_accepts_valid_tags` (parametrized: `pl`, `EN`,
  `en-US`, `en-us`, `pt-BR`, `zh-Hant`, `zh-Hant-TW`, `en-US-x-private`,
  `i-klingon`, `x-private`, `a`)
- `test_is_well_formed_rejects_invalid` (parametrized: empty, whitespace,
  trailing/leading space, internal space, underscore separator,
  leading/trailing hyphen, empty subtag, digit-leading primary, subtag
  > 8 chars, slash)
- `test_is_well_formed_rejects_non_string`
- `test_primary_subtag` (parametrized: case folding, region stripped,
  empty)
- `test_primary_subtag_non_string_returns_empty`

---

## 7. Integration Test Specifications

### 7.1 `tests/integration/test_cli.py`

Uses subprocess invocation (`python -m epub_deepl_prepare ...`) or
the `cli.main()` entry point with captured `sys.argv` — preferred for
faster runs.

- `test_no_args_shows_usage_with_both_subcommands`
- `test_prepare_help_lists_all_flags`
- `test_restore_help_lists_all_flags`
- `test_prepare_emits_html_file`
- `test_prepare_html_has_section_per_spine_item`
- `test_prepare_html_head_contains_title_and_description`
- `test_prepare_html_nav_block_carries_ncx_data`
- `test_prepare_exit_code_0_on_success`
- `test_prepare_exit_code_1_on_drm`
- `test_prepare_exit_code_1_on_missing_file`
- `test_prepare_writes_no_output_on_validation_failure`
- `test_restore_emits_epub_file`
- `test_restore_exit_code_0_on_success`
- `test_restore_exit_code_1_on_translated_html_mismatch`
- `test_default_output_naming_prepare`
- `test_default_output_naming_restore`
- `test_output_flag_overrides_default`
- `test_existing_output_without_force_fails_fast`
- `test_existing_output_with_force_overwrites`
- `test_ruby_annotations_emit_warning_to_stderr`
- `test_ruby_does_not_affect_exit_code`
- `test_verbose_flag_emits_per_file_progress`
- `test_no_output_on_stdout_in_normal_run`
- **US-009 lang resolution:**
  - `test_lang_auto_detected_from_translated_html`
  - `test_lang_explicit_flag_overrides_detected_with_warning`
  - `test_lang_region_subtag_passed_through_to_opf` (`pt-BR` → `<dc:language>pt-BR</dc:language>`)
  - `test_lang_missing_in_html_and_no_flag_raises`
  - `test_lang_whitespace_only_in_html_treated_as_missing`
  - `test_lang_malformed_explicit_flag_rejected`
  - `test_lang_drift_warning_when_primary_subtag_unchanged` (source `en`, target `en-GB` → WARN)
  - `test_lang_no_drift_warning_when_primary_subtag_changes` (source `en`, target `pl` → silent)

### 7.2 `tests/integration/test_roundtrip.py`

- `test_roundtrip_without_translation_synth_minimal`
- `test_roundtrip_without_translation_synth_with_nested_ncx`
- `test_roundtrip_without_translation_synth_with_mathml`
- `test_roundtrip_without_translation_synth_with_ruby`
- `test_roundtrip_without_translation_synth_with_extension_namespaces`
- `test_roundtrip_without_translation_is_content_identical[corpus]`
  *(parametrized over `/tmp/nowe/*.epub`)*
- `test_zip_packaging_invariants_hold_after_roundtrip[corpus]`
  *(critical — closes C-1: asserts mimetype-first, STORED, flag_bits=0,
   no extras, DEFLATED tail, on every roundtrip output)*
- `test_simulated_translation_completeness[corpus]`
- `test_navlabel_matches_heading_text_after_simulated_translation[corpus]`
- `test_manifest_element_canonical_xml_identical_after_roundtrip[corpus]`
- `test_spine_element_canonical_xml_identical_after_roundtrip[corpus]`
- `test_mathml_receives_translate_no_in_prepare`
- `test_mathml_canonical_xml_identical_after_restore`
- `test_cli_turnaround_per_book[corpus]` *(SM-6)*
- `test_restored_opf_dc_language_set_to_target`
- `test_restored_opf_language_und_fallback_when_missing` *(US-019)*
- `test_restored_metadata_subject_count_preserved`
- `test_input_equals_output_path_rejected[prepare]` *(US-018)*
- `test_input_equals_output_path_rejected[restore]` *(US-018)*
- `test_input_equals_output_path_force_does_not_bypass` *(US-018)*
- `test_non_xhtml_spine_item_rejected` *(US-020)*
- `test_adversarial_translation_strips_data_attribute_surfaces_precise_error` *(SM-7)*
- `test_adversarial_translation_collapses_pre_whitespace_either_succeeds_or_fails_precisely` *(SM-7)*
- `test_adversarial_translation_attribute_reorder_still_succeeds` *(SM-7)*
- `test_adversarial_translation_random_seeded_combinations[seeds]` *(SM-7)*

---

## 8. Test Data Strategy

### Synthetic minimal EPUB

The default factory produces:

- 1 OPF with 2 titles, 1 description, 2 subjects, 1 creator, 1 publisher,
  1 date, 1 identifier, language `en`.
- 3 XHTML files (chapters): `ch01.xhtml`, `ch02.xhtml`, `ch03.xhtml`,
  each with 1 `<h1 id="...">` heading and 1 paragraph.
- NCX with 3 `<navPoint>` entries pointing to each chapter's heading id.
- 1 CSS stylesheet to verify pass-through of non-XHTML manifest items.

### Edge-case synthetic EPUBs

Generated on demand via factory parameters:

| Edge case | Factory invocation |
|---|---|
| Nested NCX (depth 3) | `nav_map=[("Part 1", "ch01.xhtml#p1", [("Ch 1", "ch01.xhtml#c1", []), ("Ch 2", "ch01.xhtml#c2", [])])]` |
| MathML content | XHTML body includes `<math xmlns="…"><mrow>…</mrow></math>` |
| Ruby annotations | XHTML body includes `<ruby>漢<rt>kan</rt></ruby>` |
| Calibre meta extensions | OPF includes `<meta name="calibre:series" content="..."/>` |
| Multiple `<dc:language>` | OPF `language=["en", "de"]` (factory extension) |
| ID collision across files | Both `ch01.xhtml` and `ch02.xhtml` have `<h2 id="intro">` |
| Empty XHTML body | One chapter body is `""` |
| Empty `<dc:description>` | `descriptions=()` |
| Path traversal attempt | `extra_files={"../etc/passwd": b"x"}` — must be rejected by validator |

### Corpus

`/tmp/nowe/`:

- `Build_a_Large_Language_Model_(From_Scrat.epub` (technical, dense)
- `Build_a_Reasoning_Model_(From_Scratch)_v8.epub` (technical, dense)
- `Messenger, Shannon - Keeper of the Lost Cities 04 - Neverseen.epub` (novel, long)
- `Test Yourself on Sebastian Raschka's Build a Large Language Model (From Scratch) - Sebastian Raschka.epub` (workbook)

Diverse: 2 technical, 1 novel, 1 workbook. All EPUB 2.0 + NCX (verified).

Corpus tests skip with a clear message if `/tmp/nowe` is absent or empty,
so the suite remains runnable on any machine without the user's local
test data.

---

## 9. Out-of-Band Verification

These checks are not part of the automated suite but are documented as
required pre-release manual steps:

1. **`epubcheck` on round-trip output** for each corpus book:
   ```bash
   epubcheck output/<book>.translated.epub
   ```
2. **Reader rendering check** in at least one EPUB reader (Apple Books
   or Calibre's E-book viewer) for one corpus book per release.
3. **Real DeepL upload** for one corpus book per release, verifying R-8
   (data-* survives translation) on actual DeepL servers, not just
   simulated.

These are documented in `tests/integration/README.md` with exact
commands and expected outcomes.

---

## 10. Coverage and CI Wiring

### Coverage configuration

In `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["src/epub_deepl_prepare"]
branch = true

[tool.coverage.report]
fail_under = 85
show_missing = true
exclude_lines = ["pragma: no cover", "raise NotImplementedError", "if TYPE_CHECKING:"]

[tool.pytest.ini_options]
addopts = "-ra -q --strict-markers -m 'not corpus'"
markers = [
  "unit: fast, no I/O beyond temp files",
  "integration: synthetic EPUB end-to-end",
  "corpus: requires /tmp/nowe; opt-in",
]
```

### Per-module coverage floors

| Module | Floor |
|---|---|
| `epub/validator.py` | 100% |
| `epub/writer.py` | 100% |
| `epub/ncx.py` | 95% |
| `epub/opf.py` | 95% |
| `merge/builder.py` | 90% |
| `restore/parser.py` | 90% |
| `restore/applier.py` | 90% |
| `cli.py` | 85% |

### CI

Out of MVP scope (per tech-stack.md §6). Local pre-commit hook documented:

```yaml
- repo: local
  hooks:
    - id: pytest-fast
      name: pytest (unit + synth integration)
      entry: pytest -m 'not corpus'
      language: system
      pass_filenames: false
```

---

## 11. Test Implementation Order

Match the implementation order in tasks #9–#11. Tests are written
**alongside** code in each implementation slice — no test-after.

1. **Slice 1 (parser + validator):** unit tests 6.1, 6.2, 6.5, 6.6, 6.7.
2. **Slice 2 (merge/builder):** add CLI integration tests for `prepare`.
3. **Slice 3 (restore/parser):** add restore CLI tests.
4. **Slice 4 (writer + ZIP):** unit test 6.4, then full round-trip
   integration on synthetic EPUBs.
5. **Slice 5 (corpus integration):** parametrized corpus tests; final
   roundtrip-integrity verification.

Each slice's tests must pass before the next slice begins.

---

## 12. Known Test Gaps and Acknowledged Risks

| Gap | Rationale |
|---|---|
| No automated `epubcheck` invocation | Java runtime in test path; cost > benefit for MVP; documented manual step |
| No real DeepL round-trip in automated suite | Non-deterministic, network-bound, quota-limited; simulated_translation fixture is the automated proxy |
| No test for very large EPUBs (> 200 MB) | Outside PRD scope; no corpus to exercise; would only test memory ceiling already documented |
| No GUI / reader compatibility tests | No GUI; reader compatibility verified by passing `epubcheck` |
| No internationalisation tests beyond Latin/CJK in synth fixtures | Real corpus already covers English; PRD does not constrain other source languages |
