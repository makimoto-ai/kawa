"""Generate API reference sections from docs/openapi.json.

A line of its own such as

    ::: openapi POST /v1/transcriptions

is replaced with that operation's heading, summary, description, parameters,
request body, response body and status codes, as plain Markdown. Handwritten
text goes under it. The build fails on an operation the spec doesn't have,
and warns (failing strict builds) when the spec has one no page renders.

Run this file directly for a self-check.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from mkdocs.exceptions import PluginError

log = logging.getLogger(f"mkdocs.hooks.{__name__}")

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
DIRECTIVE = re.compile(r"^::: openapi ([A-Za-z]+) (\S+)[ \t]*$", re.MULTILINE)
MAX_DEPTH = 4

_spec: dict = {}
_rendered: set[tuple[str, str]] = set()


def on_pre_build(config, **kwargs):
    global _spec
    _spec = json.loads((Path(config["docs_dir"]) / "openapi.json").read_text(encoding="utf-8"))
    _rendered.clear()


def on_page_markdown(markdown, page, **kwargs):
    def expand(m):
        method, path = m[1].lower(), m[2]
        if method not in _spec.get("paths", {}).get(path, {}):
            raise PluginError(f"{page.file.src_uri}: {m[0]}: no such operation in openapi.json.")
        _rendered.add((method, path))
        return render(_spec, method, path)
    return DIRECTIVE.sub(expand, markdown)


def on_env(env, **kwargs):
    # Runs once every page's Markdown has been processed.
    for path, item in _spec.get("paths", {}).items():
        for method in HTTP_METHODS:
            if method in item and (method, path) not in _rendered:
                log.warning(f"{method.upper()} {path} is in openapi.json but no page renders it.")
    return env


def render(spec: dict, method: str, path: str) -> str:
    op = spec["paths"][path][method]
    ref = lambda node: resolve(spec, node)
    out = [f"## `{method.upper()} {path}`"]
    if summary := op.get("summary", "").strip():
        out.append(f"*{summary if summary.endswith('.') else summary + '.'}*")
    if description := op.get("description", "").strip():
        out.append(description)

    params = [ref(p) for p in spec["paths"][path].get("parameters", []) + op.get("parameters", [])]
    for where in ("path", "query"):
        rows = [[f"`{p['name']}`", type_of(spec, p.get("schema", {})), "Yes" if p.get("required") else "No",
                 describe(spec, p.get("schema", {}), p.get("description"))]
                for p in params if p.get("in") == where]
        if rows:
            out.append(f"### {where.title()} Parameters\n\n" + table(["Parameter", "Type", "Required", "Description"], rows))

    for media_type, media in ref(op.get("requestBody", {})).get("content", {}).items():
        schema = merged(spec, media.get("schema", {}))
        text = f"### Request Body (`{media_type}`)"
        if schema.get("description"):
            text += "\n\n" + schema["description"].strip()
        out.append(text + fields(spec, schema, required=True))

    for status, response in op.get("responses", {}).items():
        schema = (ref(response).get("content", {}).get("application/json") or {}).get("schema")
        if str(status).startswith("2") and schema:
            out.append(f"### Response Body (`{status}`)" + fields(spec, schema))

    rows = [[f"`{status}`", cell(ref(r).get("description", ""))] for status, r in op.get("responses", {}).items()]
    if rows:
        out.append("### Status Codes\n\n" + table(["Status", "Meaning"], rows))
    return "\n\n".join(out)


def fields(spec: dict, schema: dict, required: bool = False) -> str:
    """A table of the schema's fields, then one per oneOf/anyOf variant."""
    rows, variants = flatten(spec, schema, "", 0, required)
    headers = ["Field", "Type"] + (["Required"] if required else []) + ["Description"]
    text = "\n\n" + table(headers, rows) if rows else ""
    for field, variant in variants:
        text += f"\n\n`{field}` as `{variant.get('$ref', '#/object').rsplit('/', 1)[-1]}`:" + fields(spec, variant, required)
    return text


def flatten(spec, schema, prefix, depth, required):
    """Rows named `a`, `a.b` and `a[].b`, plus (field, variant) pairs for oneOf/anyOf fields."""
    schema = merged(spec, schema)
    if schema.get("type") == "array" and not prefix:
        return flatten(spec, schema.get("items", {}), "[]", depth, required)
    rows, variants = [], []
    for name, prop in schema.get("properties", {}).items():
        field, resolved = f"{prefix}.{name}" if prefix else name, merged(spec, prop)
        rows.append([f"`{field}`", type_of(spec, prop)]
                    + (["Yes" if name in schema.get("required", []) else "No"] if required else [])
                    + [describe(spec, prop, prop.get("description"))])
        if depth >= MAX_DEPTH:
            continue
        if choices := resolved.get("oneOf") or resolved.get("anyOf"):
            variants += [(field, choice) for choice in choices]
            continue
        child, child_prefix = resolved, field
        if resolved.get("type") == "array":
            child, child_prefix = merged(spec, resolved.get("items", {})), f"{field}[]"
        if child.get("properties"):
            sub_rows, sub_variants = flatten(spec, child, child_prefix, depth + 1, required)
            rows += sub_rows
            variants += sub_variants
    return rows, variants


def resolve(spec: dict, node, seen: frozenset = frozenset()):
    if not isinstance(node, dict) or "$ref" not in node:
        return node
    ref = node["$ref"]
    if not ref.startswith("#/") or ref in seen:
        raise PluginError(f"openapi.json: unsupported or circular $ref {ref}.")
    target = spec
    for part in ref[2:].split("/"):
        target = target.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(target, dict) else None
        if target is None:
            raise PluginError(f"openapi.json: unresolved $ref {ref}.")
    # Keys beside a $ref (such as a local description) win over the target's.
    return {**resolve(spec, target, seen | {ref}), **{k: v for k, v in node.items() if k != "$ref"}}


def merged(spec: dict, schema: dict) -> dict:
    """Resolve a schema and fold allOf parts into one object."""
    schema = resolve(spec, schema)
    out = {k: v for k, v in schema.items() if k != "allOf"}
    for part in (merged(spec, s) for s in schema.get("allOf", [])):
        out["properties"] = {**part.get("properties", {}), **out.get("properties", {})}
        out["required"] = out.get("required", []) + part.get("required", [])
        out = {**part, **out}
    return out


def type_of(spec: dict, schema: dict) -> str:
    s = merged(spec, schema)
    if choices := s.get("oneOf") or s.get("anyOf"):
        text = "one of " + ", ".join(f"`{c.get('$ref', '#/object').rsplit('/', 1)[-1]}`" for c in choices)
    elif s.get("type") == "array":
        text = f"array of {type_of(spec, s.get('items', {}))}"
    elif isinstance(s.get("additionalProperties"), dict) and not s.get("properties"):
        text = f"map of {type_of(spec, s['additionalProperties'])}"
    else:
        text = s.get("type", "any") + (f" ({s['format']})" if s.get("format") else "")
    return text + (", nullable" if s.get("nullable") else "")


def describe(spec: dict, schema: dict, description: str | None) -> str:
    s = merged(spec, schema)
    text = (description or s.get("description") or "").strip()
    extras = []
    if s.get("enum") and not all(f"`{v}`" in text for v in s["enum"]):
        extras.append("One of " + ", ".join(f"`{v}`" for v in s["enum"]) + ".")
    if "default" in s and "default" not in text.lower():
        extras.append(f"Default `{json.dumps(s['default'])}`.")
    example = s.get("example")
    if example is not None and not isinstance(example, (dict, list)):
        value = example if isinstance(example, str) else json.dumps(example)
        if f"`{value}`" not in text:
            extras.append(f"Example: `{value}`.")
    return cell(" ".join([text] + extras))


def cell(text: str) -> str:
    return re.sub(r"\s*\n\s*", " ", text).replace("|", "\\|").strip()


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [headers, ["---"] * len(headers)] + rows
    return "\n".join("| " + " | ".join(line) + " |" for line in lines)


if __name__ == "__main__":
    spec = {
        "paths": {"/jobs/{id}": {"get": {
            "summary": "Get a job",
            "parameters": [{"$ref": "#/components/parameters/Id"}],
            "responses": {
                "200": {"description": "The job.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Job"}}}},
                "404": {"description": "No such job (`JOB_NOT_FOUND`)."},
            },
        }}},
        "components": {
            "parameters": {"Id": {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}},
            "schemas": {
                "Job": {"type": "object", "properties": {
                    "status": {"type": "string", "enum": ["queued", "done"]},
                    "items": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string", "nullable": True}}}},
                    "result": {"oneOf": [{"$ref": "#/components/schemas/Summary"}]},
                }},
                "Summary": {"type": "object", "properties": {"topic": {"type": "string", "description": "A | label."}}},
            },
        },
    }
    md = render(spec, "get", "/jobs/{id}")
    for expected in ("## `GET /jobs/{id}`", "*Get a job.*", "| `id` | string (uuid) | Yes |",
                     "One of `queued`, `done`.", "| `items[].text` | string, nullable |",
                     "`result` as `Summary`:", "A \\| label.", "| `404` | No such job (`JOB_NOT_FOUND`). |"):
        assert expected in md, f"missing: {expected}\n\n{md}"
    print("openapi_reference self-check passed.")
