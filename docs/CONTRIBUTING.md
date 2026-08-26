# Contributing to the Documentation

*Last updated: 2026-08-26*

This covers the documentation site specifically. For contributing to Kawa, see [CONTRIBUTING.md](https://github.com/makimoto-ai/kawa/blob/main/CONTRIBUTING.md) at the repository root.

## Where Documentation Lives

| Section | Path | Authoritative repository |
| --- | --- | --- |
| Home, Getting Started | `docs/index.md`, `docs/getting-started.md` | This repository (`kawa`) |
| How It Works | `docs/concepts/` | This repository |
| Service (API, authentication) | `docs/service/` | This repository |
| SDKs | `docs/sdks/<name>/` | The corresponding SDK's own repository |

Service documentation, including the pipeline concepts and the API reference, is authored directly in this repository's `docs/` directory, on `main`. 

Change it the same way you'd change any other file here: a pull request against `main`.

!!! note "SDK documentation is imported, not written here"
    If you're changing SDK-facing content, that change belongs in the SDK's own repository, not here. This repository only aggregates and displays it.

    The Python SDK's docs come from [makimoto-ai/makimoto-python](https://github.com/makimoto-ai/makimoto-python), pinned to a release tag in `.github/workflows/documentation.yml`.

## Previewing locally

```bash
pip install -r docs/requirements.txt
mkdocs serve
```

Open the URL it prints (typically `http://127.0.0.1:8000/kawa/`, matching the `site_url` in `mkdocs.yml`). The server watches `docs/` and `mkdocs.yml`
and reloads on save.

## Diagnosing a failed documentation build

Both the PR check and the deploy step run:

```bash
mkdocs build --strict
```

`--strict` turns warnings, most commonly a broken internal link or a `nav` entry in `mkdocs.yml` pointing at a file that doesn't exist, into build failures. Reproduce it locally with the command above; the error message names the offending file and link. 

A build that fails before that step (dependency install, YAML parsing) usually means a syntax error in `mkdocs.yml` or `docs/requirements.txt`; check the failed run's log under the repository's **Actions** tab for the exact step and error.

## Review

Documentation pull requests go through the same review process as any other change to this repository; see [CONTRIBUTING.md](https://github.com/makimoto-ai/kawa/blob/main/CONTRIBUTING.md).