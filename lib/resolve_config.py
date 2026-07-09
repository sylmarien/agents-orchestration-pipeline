"""Three-layer configuration resolver for agent-pipeline (design doc §9).

Pure, dependency-free (stdlib + PyYAML only) implementation of:

    resolve(defaults, project_yaml, prompt_delta) -> (resolved, provenance)

Merge semantics:
  - Maps deep-merge key-by-key; a later layer only touches the keys it sets.
  - Scalars and lists replace wholesale (no concatenation), except `gates.add` /
    `gates.remove`, which are unioned as explicit deltas across layers.
  - Every layer is validated against config_schema.json before merging (fail fast on
    unknown keys, wrong types, wrong enum values); the fully resolved config is validated
    once more to catch conditional requirements that span layers (e.g. ticketing.jira).

This module parses only already-typed dicts (JSON/YAML already loaded). Turning natural-language
prompt directives into a typed delta, and parsing pipeline.yaml off disk, are callers' jobs
(load_yaml() below is a thin convenience for the latter).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = _PACKAGE_DIR / "config" / "config_schema.json"
DEFAULT_DEFAULTS_PATH = _PACKAGE_DIR / "config" / "built_in_defaults.yaml"

# Dotted knob paths whose layers are merged as a delta (union) instead of wholesale list
# replacement -- the one exception to "lists replace wholesale" (design doc §9).
_DELTA_PATHS = {"gates.add", "gates.remove"}

_LAYER_LABELS = {
    "defaults": "built_in_defaults",
    "project": "project_config",
    "prompt": "user_prompt",
    "resolved": "resolved config",
}


class ConfigError(Exception):
    """Raised when a config layer (or the resolved config) fails schema validation."""


def load_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level, got {type(data).__name__}")
    return data


def load_schema(path: str | Path = DEFAULT_SCHEMA_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_defaults(path: str | Path = DEFAULT_DEFAULTS_PATH) -> dict:
    return load_yaml(path)


# --------------------------------------------------------------------------------------
# Minimal JSON Schema (draft 2020-12 subset) validator -- covers exactly the constructs
# used by config_schema.json: type, enum, const, properties/additionalProperties, items,
# required, minimum/maximum/exclusiveMinimum, minLength, $ref/$defs, allOf with if/then.
# Kept in-tree rather than depending on the `jsonschema` package so the plugin has no
# non-stdlib runtime dependency beyond PyYAML.
# --------------------------------------------------------------------------------------

_TYPE_CHECKS = {
    "null": lambda v: v is None,
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def _check_type(value: Any, type_spec: Any) -> bool:
    types = type_spec if isinstance(type_spec, list) else [type_spec]
    return any(_TYPE_CHECKS[t](value) for t in types)


def _resolve_ref(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ConfigError(f"unsupported $ref: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _validate_node(instance: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        schema = _resolve_ref(schema["$ref"], root)

    label = path or "<root>"

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{label}: expected constant {schema['const']!r}, got {instance!r}")
        return

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{label}: {instance!r} is not one of {schema['enum']}")
        return

    if "type" in schema and not _check_type(instance, schema["type"]):
        errors.append(f"{label}: expected type {schema['type']}, got {type(instance).__name__} ({instance!r})")
        return

    if isinstance(instance, str) and "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(f"{label}: string shorter than minLength {schema['minLength']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{label}: {instance!r} is below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{label}: {instance!r} is above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{label}: {instance!r} must be greater than {schema['exclusiveMinimum']}")

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{label}: missing required key '{key}'")
        for key, value in instance.items():
            child_path = f"{path}.{key}" if path else key
            if key in properties:
                _validate_node(value, properties[key], root, child_path, errors)
            elif additional is False:
                errors.append(f"{child_path}: unknown key (not permitted by schema)")
            elif isinstance(additional, dict):
                _validate_node(value, additional, root, child_path, errors)
        for sub in schema.get("allOf", []):
            if "if" in sub:
                probe: list[str] = []
                _validate_node(instance, sub["if"], root, path, probe)
                if not probe and "then" in sub:
                    _validate_node(instance, sub["then"], root, path, errors)
            else:
                _validate_node(instance, sub, root, path, errors)
    elif isinstance(instance, list):
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(instance):
                _validate_node(item, items_schema, root, f"{path}[{i}]", errors)


def validate(instance: dict, schema: dict, layer_label: str = "config") -> None:
    """Validate `instance` against `schema`; raise ConfigError with all violations on failure."""
    errors: list[str] = []
    _validate_node(instance, schema, schema, "", errors)
    if errors:
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        raise ConfigError(f"invalid {layer_label}:\n{bullet_list}")


# --------------------------------------------------------------------------------------
# Merge + provenance
# --------------------------------------------------------------------------------------


def _deep_merge(base: Any, overlay: dict, path: str = "") -> Any:
    result = dict(base) if isinstance(base, dict) else {}
    for key, overlay_value in overlay.items():
        child_path = f"{path}.{key}" if path else key
        if child_path in _DELTA_PATHS and isinstance(overlay_value, list):
            existing = result.get(key)
            merged_list = list(existing) if isinstance(existing, list) else []
            for item in overlay_value:
                if item not in merged_list:
                    merged_list.append(item)
            result[key] = merged_list
        elif isinstance(overlay_value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], overlay_value, child_path)
        else:
            result[key] = copy.deepcopy(overlay_value)
    return result


def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in d.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _compute_provenance(defaults: dict, project_yaml: dict, prompt_delta: dict, resolved: dict) -> dict[str, str]:
    layers = [("defaults", defaults), ("project", project_yaml), ("prompt", prompt_delta)]
    flat_layers = [(name, _flatten(layer)) for name, layer in layers]
    provenance: dict[str, str] = {}
    for path in _flatten(resolved):
        if path in _DELTA_PATHS:
            # Only layers that actually contribute elements count -- defaults' empty list is
            # the delta's baseline, not a contribution, so it shouldn't crowd out the layers
            # that did add something.
            contributors = [name for name, flat in flat_layers if flat.get(path)]
            provenance[path] = "+".join(contributors) if contributors else "defaults"
        else:
            touched = [name for name, flat in flat_layers if path in flat]
            provenance[path] = touched[-1] if touched else "defaults"
    return provenance


def resolve(
    defaults: dict,
    project_yaml: dict | None = None,
    prompt_delta: dict | None = None,
    schema: dict | None = None,
) -> tuple[dict, dict[str, str]]:
    """Merge the three configuration layers and return (resolved_config, provenance).

    provenance maps each dotted knob path in `resolved_config` to the layer that produced its
    value ("defaults" | "project" | "prompt"), except the gates.add/gates.remove deltas, whose
    provenance is the "+"-joined set of layers that contributed elements to the union.
    """
    project_yaml = project_yaml or {}
    prompt_delta = prompt_delta or {}
    schema = schema if schema is not None else load_schema()

    validate(defaults, schema, _LAYER_LABELS["defaults"])
    validate(project_yaml, schema, _LAYER_LABELS["project"])
    validate(prompt_delta, schema, _LAYER_LABELS["prompt"])

    merged = _deep_merge(defaults, project_yaml)
    merged = _deep_merge(merged, prompt_delta)

    validate(merged, schema, _LAYER_LABELS["resolved"])

    provenance = _compute_provenance(defaults, project_yaml, prompt_delta, merged)
    return merged, provenance
