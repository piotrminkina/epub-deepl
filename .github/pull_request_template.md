<!--
Thanks for the contribution. A few things before you submit:

  1. Read CONTRIBUTING.md for the development setup and quality gates.
  2. Each commit should be atomic — one indivisible design decision.
     The litmus test: if a reviewer checks out the previous commit,
     does the tree still build / lint / type-check / pass tests?
  3. Run the full quality gate locally:
       ruff check src tests
       ruff format --check src tests
       mypy --strict src/epub_deepl_prepare
       pytest -m 'not corpus or corpus'
     CI will run the same plus the epubcheck job on synthetic fixtures.
  4. For structural changes (OPF / NCX / writer logic), include or update
     the manual epubcheck recipe in your PR description.
-->

## Summary

<!-- One short paragraph: what this PR changes and why. -->

## Type of change

<!-- Check exactly one. -->

- [ ] Bug fix (no contract change)
- [ ] New feature (new capability; may extend PRD / tech-spec)
- [ ] Refactor (no behaviour change)
- [ ] Documentation (docs / ADRs / lessons-learned only)
- [ ] CI / tooling (workflows, devcontainer, dependency bumps)
- [ ] Other:

## Quality gates

- [ ] `ruff check src tests` clean
- [ ] `ruff format --check src tests` clean
- [ ] `mypy --strict src/epub_deepl_prepare` clean
- [ ] `pytest -m 'not corpus'` green
- [ ] If touching restore / writer / OPF / NCX: ran `epubcheck` on a
      round-tripped corpus or synthetic EPUB; result documented below.

## Manual verification (when relevant)

<!--
Paste the epubcheck IN vs OUT diff for at least one EPUB you
round-tripped. Skip if the change is purely documentation or CI.
-->

## Documentation impact

- [ ] PRD updated (US / SM changes)
- [ ] tech-spec updated (architecture / algorithm changes)
- [ ] test-plan updated (new tests / coverage changes)
- [ ] lessons-learned updated (new gotcha or DeepL observation)
- [ ] ADR added (new architectural decision)
- [ ] No docs impact
