# Docs includes

Fragments pulled into pages with `pymdownx.snippets` (`--8<-- "<file>"`). This
folder is listed in `exclude_docs`, so nothing here is published on its own.

## Postman collection links

`getting-started.md`, `service/api-reference.md` and the root `README.md` link
to the reference collection in the public `makimoto-kawa-api` workspace as
plain Markdown links; keep them in step:

https://www.postman.com/makimoto-ai/makimoto-kawa-api/collection/9muqmgc/makimoto-transcription-api

Readers fork from that page. Forks pull updates from the published
collection and are counted on its *Forks* tab, so the link only changes if the
collection or workspace is replaced.

The pages tell readers to set the `raw_api_key` **collection variable**, which
the generated collection defines (empty) alongside `api_url`. Renaming it
means updating `getting-started.md`, `service/api-reference.md` and the root
README. Never give it a value in the published collection: every fork receives
it.

A *Makimoto Kawa* environment (`api_url`, secret `raw_api_key`, `job_id`) also
sits in the workspace. The docs do not depend on it.
