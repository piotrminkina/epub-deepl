# tests/corpus/

Real-world EPUB fixtures for corpus integration tests. Files dropped
here are picked up automatically by tests marked `@pytest.mark.corpus`.

## What's bundled

| File | Source | Size | Genre | Notes |
|---|---|---|---|---|
| `alice-pg11.epub` | [Project Gutenberg #11](https://www.gutenberg.org/ebooks/11) | ~137 KB | classic fiction | Public domain. EPUB 2.0 + NCX. |

One bundled book is enough to prove the tool round-trips against a real
publisher pipeline (in this case Project Gutenberg's standard EPUB
generation). Synthetic edge-case EPUBs (non-ASCII content, embedded
MathML, ruby annotations, multi-language metadata) are factory-built
on-demand by `tests/fixtures/minimal.py` per test — no separate file
needed.

## Add your own

Drop additional EPUBs into this directory. The corpus fixture in
`tests/conftest.py` parametrizes over every `*.epub` it finds here.
Run:

```bash
pytest -m corpus -v
```

The tool targets EPUB **2.0** with NCX-based navigation; EPUB 3 with
`nav.xhtml` is currently out of scope and will be rejected by the
validator.

## Use a different corpus directory

Override the default with the `EPUB_DEEPL_CORPUS` environment variable:

```bash
EPUB_DEEPL_CORPUS=/path/to/your/ebook/library pytest -m corpus
```

Useful if you keep a larger personal library outside the repo and
don't want to bundle it (file-size, copyright, or just keeping the
repo lean).

## License notes

- `alice-pg11.epub` — public domain in the United States. Project
  Gutenberg's license terms (which apply to the *Project Gutenberg
  header*, not the book content) are at
  <https://www.gutenberg.org/policy/license.html>.
- Do **not** add DRM-protected EPUBs. The validator rejects them
  and they cannot be legally redistributed under our MIT license.
- Do **not** add EPUBs whose copyright is unclear. Public-domain
  (pre-1929 in the US; varies elsewhere), CC0, CC-BY, or
  explicit-permission books only.
