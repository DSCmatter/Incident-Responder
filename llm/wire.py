"""One schema, both dialects, no 400s.

Pydantic emits `$defs`/`$ref` and nullable unions as `anyOf`. Gemini's documented
schema subset has neither, and free OpenAI-compatible servers are inconsistent
about both, so every tool schema is normalised here before it reaches a body.
Inlining is still valid JSON Schema, so nothing is lost where a backend would
have accepted the original.

Anything that cannot be flattened raises instead of shipping a body the backend
will reject on the call that matters.
"""

from __future__ import annotations

from typing import Any

from llm.turn import Json

_MAX_DEPTH = 32


class UnrepresentableSchema(ValueError):
    """A schema construct no configured backend accepts."""


def portable_schema(schema: Json) -> Json:
    defs = _definitions(schema)
    return _normalise(schema, defs, depth=0)


def _definitions(schema: Json) -> dict[str, Json]:
    merged: dict[str, Json] = {}
    for key in ("$defs", "definitions"):
        found = schema.get(key)
        if isinstance(found, dict):
            merged.update(found)
    return merged


def _normalise(node: Any, defs: dict[str, Json], *, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        raise UnrepresentableSchema("schema nests deeper than a backend can inline")
    if isinstance(node, list):
        return [_normalise(item, defs, depth=depth + 1) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        target = _resolve(node["$ref"], defs)
        return _normalise(target, defs, depth=depth + 1)

    for unsupported in ("oneOf", "allOf", "not", "if", "then", "else"):
        if unsupported in node:
            raise UnrepresentableSchema(f"{unsupported} has no portable equivalent")

    if "anyOf" in node:
        return _normalise_union(node, defs, depth=depth)

    result: Json = {}
    for key, value in node.items():
        if key in {"$defs", "definitions", "title", "default", "additionalProperties"}:
            continue
        if key in {"properties"} and isinstance(value, dict):
            result[key] = {
                name: _normalise(child, defs, depth=depth + 1) for name, child in value.items()
            }
        elif key in {"items", "additionalItems"}:
            result[key] = _normalise(value, defs, depth=depth + 1)
        elif key == "enum":
            result[key] = list(value)
        else:
            result[key] = value
    return result


def _normalise_union(node: Json, defs: dict[str, Json], *, depth: int) -> Json:
    branches = [_normalise(branch, defs, depth=depth + 1) for branch in node["anyOf"]]
    nullable = any(branch == {"type": "null"} for branch in branches)
    concrete = [branch for branch in branches if branch != {"type": "null"}]
    if len(concrete) != 1:
        raise UnrepresentableSchema("anyOf with two concrete branches has no portable equivalent")
    merged: Json = dict(concrete[0])
    if nullable:
        merged["nullable"] = True
    for key, value in node.items():
        if key not in {"anyOf", "title", "default"}:
            merged.setdefault(key, value)
    return merged


def _resolve(reference: str, defs: dict[str, Json]) -> Json:
    prefix = "#/$defs/"
    if not reference.startswith(prefix):
        raise UnrepresentableSchema(f"only local $defs references are portable, got {reference!r}")
    name = reference[len(prefix) :]
    try:
        return defs[name]
    except KeyError:
        raise UnrepresentableSchema(
            f"$ref points at a definition that is not there: {name!r}"
        ) from None
