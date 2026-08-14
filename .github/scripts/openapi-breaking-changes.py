#!/usr/bin/env python3
"""Detect breaking changes between two OpenAPI description files.

Implements the project's documented breaking-change list:

  1. An operationId name has been changed.
  2. A URL parameter name has been changed.
  3. An operation has been removed from the description.
  4. A `required: true` has been added to the requestBody.
  5. A parameter has been added to the required list for a requestBody.
  6. A field has been removed from a response body.
  7. A field type has changed in a response body.
  8. A field has been removed from the required list in a response body.

Plus two structural cases that make the above unrepresentable:
  9. A schema definition has been removed from components/schemas.
 10. An enum value has been removed.

Note the asymmetry that line-based diffing gets wrong: for a *request* body,
*adding* to `required` is breaking; for a *response* body, *removing* from
`required` is breaking. Both are additive/subtractive in opposite directions,
so they cannot be detected by scanning removed diff lines alone.

Exit status is always 0; findings go to stdout as JSON. The caller decides
policy.
"""

import json
import sys

import yaml

try:
    from yaml import CSafeLoader as Loader
except ImportError:  # pragma: no cover - libyaml is present on ubuntu-latest
    from yaml import SafeLoader as Loader

METHODS = ('get', 'put', 'post', 'delete', 'patch', 'options', 'head', 'trace')


def load(path):
    with open(path, encoding='utf-8') as handle:
        return yaml.load(handle, Loader=Loader)


def operations(doc):
    """Map (path, method) -> operation object."""
    out = {}
    for path, item in (doc.get('paths') or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method in METHODS and isinstance(op, dict):
                out[(path, method)] = op
    return out


def path_params(op):
    return {
        p.get('name')
        for p in (op.get('parameters') or [])
        if isinstance(p, dict) and p.get('in') == 'path'
    }


def request_body(op):
    body = op.get('requestBody')
    return body if isinstance(body, dict) else {}


def json_schema(container):
    """Pull the application/json schema out of a requestBody/response."""
    content = container.get('content')
    if not isinstance(content, dict):
        return {}
    for media, spec in content.items():
        if 'json' in media and isinstance(spec, dict):
            schema = spec.get('schema')
            return schema if isinstance(schema, dict) else {}
    return {}


def enum_values(schema):
    values = schema.get('enum')
    return set(map(str, values)) if isinstance(values, list) else set()


def compare_operations(base, head, findings):
    base_ops, head_ops = operations(base), operations(head)

    for key, op in base_ops.items():
        path, method = key
        label = f'{method.upper()} {path}'

        if key not in head_ops:
            findings.append({
                'rule': 'operation-removed',
                'detail': f'{label} was removed',
            })
            continue

        new = head_ops[key]

        old_id, new_id = op.get('operationId'), new.get('operationId')
        if old_id and new_id and old_id != new_id:
            findings.append({
                'rule': 'operationid-changed',
                'detail': f'{label}: operationId {old_id!r} -> {new_id!r}',
            })

        removed_params = path_params(op) - path_params(new)
        if removed_params:
            findings.append({
                'rule': 'url-parameter-renamed',
                'detail': f'{label}: path parameter(s) gone: {sorted(removed_params)}',
            })

        old_body, new_body = request_body(op), request_body(new)
        if new_body.get('required') and not old_body.get('required'):
            findings.append({
                'rule': 'requestbody-now-required',
                'detail': f'{label}: requestBody became required',
            })

        added_required = set(json_schema(new_body).get('required') or []) - \
            set(json_schema(old_body).get('required') or [])
        if added_required:
            findings.append({
                'rule': 'requestbody-required-added',
                'detail': f'{label}: new required request field(s): {sorted(added_required)}',
            })


def compare_schemas(base, head, findings):
    """Compare components/schemas.

    Responses overwhelmingly `$ref` into components/schemas in the
    non-dereferenced description, so comparing schemas covers "field removed
    from a response body" and "field type changed" without resolving refs.
    """
    base_schemas = (base.get('components') or {}).get('schemas') or {}
    head_schemas = (head.get('components') or {}).get('schemas') or {}

    for name, old in base_schemas.items():
        if not isinstance(old, dict):
            continue

        new = head_schemas.get(name)
        if new is None:
            findings.append({
                'rule': 'schema-removed',
                'detail': f'schema {name!r} was removed',
            })
            continue
        if not isinstance(new, dict):
            continue

        old_props = old.get('properties') or {}
        new_props = new.get('properties') or {}

        for prop in set(old_props) - set(new_props):
            findings.append({
                'rule': 'response-field-removed',
                'detail': f'{name}.{prop} was removed',
            })

        for prop in set(old_props) & set(new_props):
            old_p, new_p = old_props[prop], new_props[prop]
            if not isinstance(old_p, dict) or not isinstance(new_p, dict):
                continue

            old_t, new_t = old_p.get('type'), new_p.get('type')
            if old_t and new_t and old_t != new_t:
                findings.append({
                    'rule': 'response-field-type-changed',
                    'detail': f'{name}.{prop}: type {old_t!r} -> {new_t!r}',
                })

            dropped = enum_values(old_p) - enum_values(new_p)
            if dropped:
                findings.append({
                    'rule': 'enum-value-removed',
                    'detail': f'{name}.{prop}: enum value(s) removed: {sorted(dropped)}',
                })

        # For a response body, losing a guarantee is the breaking direction.
        dropped_required = set(old.get('required') or []) - set(new.get('required') or [])
        if dropped_required:
            findings.append({
                'rule': 'response-required-removed',
                'detail': f'{name}: no longer guaranteed: {sorted(dropped_required)}',
            })

        dropped = enum_values(old) - enum_values(new)
        if dropped:
            findings.append({
                'rule': 'enum-value-removed',
                'detail': f'schema {name}: enum value(s) removed: {sorted(dropped)}',
            })


def summarize(base, head):
    """Non-breaking additions, used for the informational PR summary."""
    base_ops, head_ops = operations(base), operations(head)
    added = [f'{m.upper()} {p}' for (p, m) in set(head_ops) - set(base_ops)]

    base_schemas = set((base.get('components') or {}).get('schemas') or {})
    head_schemas = set((head.get('components') or {}).get('schemas') or {})

    return {
        'added_operations': sorted(added),
        'added_schemas': sorted(head_schemas - base_schemas),
        'total_operations': len(head_ops),
        'total_schemas': len(head_schemas),
    }


def main():
    if len(sys.argv) != 3:
        print('usage: openapi-breaking-changes.py BASE.yaml HEAD.yaml', file=sys.stderr)
        return 2

    base, head = load(sys.argv[1]), load(sys.argv[2])

    findings = []
    compare_operations(base, head, findings)
    compare_schemas(base, head, findings)

    json.dump({'findings': findings, 'summary': summarize(base, head)}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
