#!/usr/bin/env python3
"""Detect breaking changes between two OpenAPI description files.

Scope
-----
Implements the breaking-change list documented for these descriptions:

  1. An operationId name has been changed or removed.
  2. A URL parameter name has been changed.
  3. An operation has been removed from the description.
  4. A `required: true` has been added to the requestBody.
  5. A parameter has been added to the required list for a requestBody.
  6. A field has been removed from a response body.
  7. A field type has changed in a response body.
  8. A field has been removed from the required list in a response body.

Plus two structural cases that make the above unrepresentable:

  9. A schema definition has been removed from `components/schemas`.
 10. An enum value has been removed.

Comparison model
----------------
The descriptions are `$ref`-heavy, so a comparison that only looks at the
top level of `components/schemas` misses most of the surface. This module
instead walks the document:

* Local `$ref` pointers (`#/components/...`) are resolved before comparing,
  including refs inside `parameters`, `responses` and `requestBody`.
* Comparison recurses through `properties`, `items` (arrays, including the
  3.1 tuple form), `additionalProperties`, `allOf`/`oneOf`/`anyOf`, and
  operation parameter schemas. Parameters declared on the path item are
  included, with an operation-level parameter of the same name and location
  taking precedence, as the specification requires.
* `allOf` members are merged into an effective schema so that inherited
  properties and `required` entries participate in the comparison.
* Inline schemas are covered because the walk starts from every operation's
  parameters, request body and 2xx responses rather than from
  `components/schemas`.
* JSON media types are tracked on both sides of an operation, so dropping
  JSON support from a request body or a response is reported, as is removing
  a request body outright.
* Traversal is memoised on the identity of the *resolved* base and head nodes
  plus the direction, so a widely shared schema is compared once instead of
  once per reference site, and recursive schemas terminate.

Direction matters, and line-based diffing gets it wrong. For a *request*
body, *adding* to `required` is breaking; for a *response* body, *removing*
from `required` is breaking. The walk therefore carries a direction and
applies the asymmetric rules: a removed property, a removed `required` entry
and any change to a declared `type`, including dropping the declaration
altogether, are breaking on a response, while a newly required property, a
removed union member and a narrowed `type` are breaking on a request.
Parameters are compared with the request rules, including a newly added
required parameter; webhook payloads with the response rules, because
consumers receive them.

Known limits (deliberately not claimed as covered): external/file `$ref`
targets are compared by pointer string only; `not`, `discriminator`,
`patternProperties`, `nullable`, `format`, `default` and numeric/length
constraint tightening are not evaluated; only 2xx responses and JSON media
types are compared, so a non-JSON media type or a 4xx/5xx shape change is
invisible; parameter serialisation (`style`, `explode`) is not compared; and
`oneOf`/`anyOf` members are matched by `$ref` target or `title` when
available and by position otherwise, so a reordered anonymous union can
produce imprecise locations. A finding is reported at the first location it
is reached from, not at every location that shares the schema.

A general-purpose differ was preferred but does not fit: the widely used
Go/Java differs target OpenAPI 3.0 only, while this repository must also
compare 3.1 descriptions, and the Python dependency set here is
hash-pinned.

Exit status is 0 unless the inputs cannot be read; findings go to stdout as
JSON and the caller decides policy.
"""

import argparse
import json
import sys

import yaml

try:
    from yaml import CSafeLoader as Loader
except ImportError:  # pragma: no cover - libyaml is present on ubuntu-latest
    from yaml import SafeLoader as Loader

METHODS = ('get', 'put', 'post', 'delete', 'patch', 'options', 'head', 'trace')

# Findings are advisory output posted to a pull request. Past some volume the
# list stops being reviewable, and an unbounded list on a pathological diff
# would dominate the job log.
MAX_FINDINGS = 250


def load(path):
    with open(path, encoding='utf-8') as handle:
        return yaml.load(handle, Loader=Loader)


def _pointer(doc, ref):
    """Resolve a local JSON pointer such as `#/components/schemas/repo`."""
    node = doc
    for token in ref[2:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(node, dict):
            if token not in node:
                return None
            node = node[token]
        elif isinstance(node, list):
            try:
                node = node[int(token)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return node


class Comparator:
    """Walks a base and a head description in parallel collecting findings."""

    def __init__(self, base, head):
        self.base = base
        self.head = head
        self.findings = []
        self._seen_findings = set()
        self._visited = set()
        self._effective = {}

    # -- helpers ---------------------------------------------------------

    def report(self, rule, detail):
        key = (rule, detail)
        if key in self._seen_findings:
            return
        self._seen_findings.add(key)
        if len(self.findings) < MAX_FINDINGS:
            self.findings.append({'rule': rule, 'detail': detail})

    def resolve(self, doc, node):
        """Follow local `$ref` chains.

        Returns `(node, ref)` where `ref` is the last pointer followed, or
        `(None, ref)` when a local pointer does not resolve.
        """
        ref = None
        seen = set()
        while isinstance(node, dict) and isinstance(node.get('$ref'), str):
            ref = node['$ref']
            if not ref.startswith('#/'):
                # External target: not loaded, so treat it as opaque and let
                # the caller compare pointer strings.
                return node, ref
            if ref in seen:
                return None, ref
            seen.add(ref)
            node = _pointer(doc, ref)
            if node is None:
                return None, ref
        return node, ref

    def effective(self, doc, schema):
        """Merge `allOf` members into a single comparable schema view."""
        if not isinstance(schema, dict) or 'allOf' not in schema:
            return schema if isinstance(schema, dict) else {}

        cached = self._effective.get(id(schema))
        if cached is not None:
            return cached

        merged = {k: v for k, v in schema.items() if k != 'allOf'}
        # Seed the cache before recursing so a self-referential `allOf`
        # terminates instead of recursing forever.
        self._effective[id(schema)] = merged

        props = dict(merged.get('properties') or {})
        required = list(merged.get('required') or [])

        members = schema['allOf']
        for member in members if isinstance(members, list) else []:
            resolved, _ = self.resolve(doc, member)
            if not isinstance(resolved, dict):
                continue
            resolved = self.effective(doc, resolved)
            for key, value in resolved.items():
                if key == 'properties' and isinstance(value, dict):
                    props.update(value)
                elif key == 'required' and isinstance(value, list):
                    required.extend(value)
                elif key not in merged:
                    merged[key] = value

        if props:
            merged['properties'] = props
        if required:
            merged['required'] = required
        return merged

    @staticmethod
    def types(schema):
        declared = schema.get('type')
        if isinstance(declared, str):
            return {declared}
        if isinstance(declared, list):
            return {t for t in declared if isinstance(t, str)}
        return set()

    @staticmethod
    def enum_values(schema):
        values = schema.get('enum')
        if not isinstance(values, list):
            return set()
        return {json.dumps(v, sort_keys=True) for v in values}

    def variant_key(self, doc, member, index):
        """Stable identity for a `oneOf`/`anyOf` member."""
        resolved, ref = self.resolve(doc, member)
        if ref:
            return ref
        if isinstance(resolved, dict) and isinstance(resolved.get('title'), str):
            return f'title:{resolved["title"]}'
        return f'index:{index}'

    def variants(self, doc, schema, keyword):
        members = schema.get(keyword)
        if not isinstance(members, list):
            return {}
        out = {}
        for index, member in enumerate(members):
            out.setdefault(self.variant_key(doc, member, index), member)
        return out

    # -- schema comparison -----------------------------------------------

    def compare_schema(self, base, head, where, direction):
        base_ref = head_ref = None
        if isinstance(base, dict):
            base, base_ref = self.resolve(self.base, base)
        if isinstance(head, dict):
            head, head_ref = self.resolve(self.head, head)

        # Memoise on the *resolved* nodes. Every `$ref` to the same target
        # resolves to the same object, so a widely shared schema is compared
        # once instead of once per reference site, and recursive schemas
        # terminate.
        key = (id(base), id(head), direction)
        if key in self._visited:
            return
        self._visited.add(key)

        if base_ref and not base_ref.startswith('#/'):
            # Both sides are external pointers; only the target can be compared.
            if base_ref != head_ref:
                self.report(
                    'external-ref-changed',
                    f'{where}: {base_ref} -> {head_ref or "removed"}',
                )
            return

        if not isinstance(base, dict):
            return
        if not isinstance(head, dict):
            self.report(
                'schema-removed',
                f'{where}: {base_ref or "schema"} no longer resolves',
            )
            return

        base = self.effective(self.base, base)
        head = self.effective(self.head, head)

        self._compare_types(base, head, where, direction)
        self._compare_enum(base, head, where)
        self._compare_required(base, head, where, direction)
        self._compare_properties(base, head, where, direction)
        self._compare_items(base, head, where, direction)
        self._compare_additional(base, head, where, direction)
        self._compare_unions(base, head, where, direction)

    def _compare_types(self, base, head, where, direction):
        base_types, head_types = self.types(base), self.types(head)
        if not base_types:
            return
        if not head_types:
            # Dropping the declaration widens what may be sent, which a
            # request producer survives, but it removes the guarantee a
            # response consumer was written against.
            if direction == 'response':
                self.report(
                    'type-declaration-removed',
                    f'{where}: declared type {sorted(base_types)} was removed',
                )
            return
        # A response consumer breaks on any type change, including a widened
        # set it was never written to handle. A request producer only breaks
        # when a type it was sending is no longer accepted.
        changed = (
            base_types != head_types
            if direction == 'response'
            else bool(base_types - head_types)
        )
        if changed:
            self.report(
                'field-type-changed',
                f'{where}: type {sorted(base_types)} -> {sorted(head_types)}',
            )

    def _compare_enum(self, base, head, where):
        dropped = self.enum_values(base) - self.enum_values(head)
        if dropped:
            values = [json.loads(value) for value in sorted(dropped)]
            self.report(
                'enum-value-removed',
                f'{where}: enum value(s) removed: {values}',
            )

    def _compare_required(self, base, head, where, direction):
        base_required = {r for r in (base.get('required') or []) if isinstance(r, str)}
        head_required = {r for r in (head.get('required') or []) if isinstance(r, str)}
        if direction == 'request':
            added = head_required - base_required
            if added:
                self.report(
                    'requestbody-required-added',
                    f'{where}: newly required field(s): {sorted(added)}',
                )
        else:
            dropped = base_required - head_required
            if dropped:
                self.report(
                    'response-required-removed',
                    f'{where}: no longer guaranteed: {sorted(dropped)}',
                )

    def _compare_properties(self, base, head, where, direction):
        base_props = base.get('properties')
        head_props = head.get('properties')
        if not isinstance(base_props, dict):
            return
        if not isinstance(head_props, dict):
            head_props = {}

        if direction == 'response':
            for name in sorted(set(base_props) - set(head_props)):
                self.report(
                    'response-field-removed',
                    f'{where}.{name} was removed',
                )

        for name in sorted(set(base_props) & set(head_props)):
            self.compare_schema(
                base_props[name], head_props[name], f'{where}.{name}', direction
            )

    def _compare_items(self, base, head, where, direction):
        base_items, head_items = base.get('items'), head.get('items')
        if base_items is None:
            return
        if head_items is None:
            self.report('array-items-removed', f'{where}: item schema was removed')
            return
        if isinstance(base_items, dict) and isinstance(head_items, dict):
            self.compare_schema(base_items, head_items, f'{where}[]', direction)
        elif isinstance(base_items, list) and isinstance(head_items, list):
            if len(head_items) < len(base_items):
                self.report(
                    'tuple-items-removed',
                    f'{where}: positional item(s) {len(base_items)} -> {len(head_items)}',
                )
            for index, (base_item, head_item) in enumerate(zip(base_items, head_items)):
                self.compare_schema(base_item, head_item, f'{where}[{index}]', direction)
        elif isinstance(base_items, (dict, list)):
            self.report(
                'array-items-changed',
                f'{where}: item schema changed shape',
            )

    def _compare_additional(self, base, head, where, direction):
        base_extra = base.get('additionalProperties')
        head_extra = head.get('additionalProperties')

        # Absent means "allowed", so absent -> false is a narrowing too.
        if head_extra is False and base_extra is not False:
            self.report(
                'additional-properties-restricted',
                f'{where}: additionalProperties narrowed to false',
            )

        if isinstance(base_extra, dict) and isinstance(head_extra, dict):
            self.compare_schema(base_extra, head_extra, f'{where}.*', direction)

    def _compare_unions(self, base, head, where, direction):
        for keyword in ('oneOf', 'anyOf'):
            base_variants = self.variants(self.base, base, keyword)
            head_variants = self.variants(self.head, head, keyword)
            if not base_variants:
                continue

            if direction == 'request':
                # A client that sent one of the removed shapes now fails.
                for key in sorted(set(base_variants) - set(head_variants)):
                    self.report(
                        'request-variant-removed',
                        f'{where}: {keyword} no longer accepts {key}',
                    )

            for key in sorted(set(base_variants) & set(head_variants)):
                self.compare_schema(
                    base_variants[key],
                    head_variants[key],
                    f'{where}({keyword}:{key})',
                    direction,
                )

    # -- document comparison ---------------------------------------------

    def parameters(self, doc, op, shared=()):
        """Resolved parameters for an operation, keyed by `(in, name)`.

        Path-item parameters apply to every operation under that path, and an
        operation-level parameter with the same name and location overrides
        the shared one, so the shared list is applied first.
        """
        out = {}
        for param in list(shared or []) + list(op.get('parameters') or []):
            resolved, _ = self.resolve(doc, param)
            if isinstance(resolved, dict) and resolved.get('name'):
                out[(resolved.get('in'), resolved['name'])] = resolved
        return out

    def json_schemas(self, doc, container):
        """JSON media-type schemas of a requestBody/response, by media type."""
        resolved, _ = self.resolve(doc, container)
        if not isinstance(resolved, dict):
            return {}, {}
        content = resolved.get('content')
        if not isinstance(content, dict):
            return resolved, {}
        schemas = {
            media: spec['schema']
            for media, spec in content.items()
            if 'json' in media and isinstance(spec, dict) and isinstance(spec.get('schema'), dict)
        }
        return resolved, schemas

    def compare_operation(
        self,
        base_op,
        head_op,
        label,
        request_direction='request',
        base_shared=(),
        head_shared=(),
    ):
        base_id, head_id = base_op.get('operationId'), head_op.get('operationId')
        if base_id and not head_id:
            # Generators derive client method names from `operationId`, so
            # dropping one renames the generated method just as a change does.
            self.report(
                'operationid-removed',
                f'{label}: operationId {base_id!r} was removed',
            )
        elif base_id and head_id and base_id != head_id:
            self.report(
                'operationid-changed',
                f'{label}: operationId {base_id!r} -> {head_id!r}',
            )

        base_params = self.parameters(self.base, base_op, base_shared)
        head_params = self.parameters(self.head, head_op, head_shared)
        removed_path_params = sorted(
            name for (loc, name) in set(base_params) - set(head_params) if loc == 'path'
        )
        if removed_path_params:
            self.report(
                'url-parameter-renamed',
                f'{label}: path parameter(s) gone: {removed_path_params}',
            )

        added_required_params = sorted(
            (str(loc), name)
            for (loc, name) in set(head_params) - set(base_params)
            # Path parameters are excluded: they are required by definition,
            # a rename is already reported as `url-parameter-renamed`, and a
            # genuinely new one changes the path template, which surfaces as a
            # removed operation instead.
            if loc != 'path' and head_params[(loc, name)].get('required')
        )
        for location, name in added_required_params:
            # An existing caller cannot satisfy a requirement it has never
            # heard of, so this is as breaking as making a parameter required.
            self.report(
                'parameter-added-required',
                f'{label}: new required {location} parameter {name!r}',
            )

        for key in sorted(
            set(base_params) & set(head_params), key=lambda k: (str(k[0]), k[1])
        ):
            location, name = key
            base_param, head_param = base_params[key], head_params[key]
            if head_param.get('required') and not base_param.get('required'):
                self.report(
                    'parameter-now-required',
                    f'{label}: {location} parameter {name!r} became required',
                )
            if isinstance(base_param.get('schema'), dict) and isinstance(
                head_param.get('schema'), dict
            ):
                # A parameter is something the caller sends, so request rules
                # apply: a narrowed type or a dropped enum value breaks it.
                self.compare_schema(
                    base_param['schema'],
                    head_param['schema'],
                    f'{label} {location} parameter {name}',
                    'request',
                )

        base_body, base_body_schemas = self.json_schemas(self.base, base_op.get('requestBody'))
        head_body, head_body_schemas = self.json_schemas(self.head, head_op.get('requestBody'))
        base_has_body = isinstance(base_body, dict) and bool(base_body)
        head_has_body = isinstance(head_body, dict) and bool(head_body)
        if base_has_body and not head_has_body:
            # The operation no longer accepts a body at all, so callers that
            # send one may now be rejected.
            self.report(
                'request-body-removed',
                f'{label}: requestBody was removed',
            )
        elif head_has_body and head_body.get('required'):
            if not base_has_body:
                # Introducing a required body imposes the same new obligation
                # on every existing caller as making an optional one required.
                self.report(
                    'requestbody-now-required',
                    f'{label}: a required requestBody was added',
                )
            elif not base_body.get('required'):
                self.report(
                    'requestbody-now-required',
                    f'{label}: requestBody became required',
                )
        if base_has_body and head_has_body:
            # Mirrors the response side: a caller that submits JSON breaks
            # when that media type stops being accepted.
            for media in sorted(set(base_body_schemas) - set(head_body_schemas)):
                self.report(
                    'request-media-type-removed',
                    f'{label} request body: {media} was removed',
                )
        for media in sorted(set(base_body_schemas) & set(head_body_schemas)):
            self.compare_schema(
                base_body_schemas[media],
                head_body_schemas[media],
                f'{label} request body',
                request_direction,
            )

        base_responses = base_op.get('responses')
        head_responses = head_op.get('responses')
        if not isinstance(base_responses, dict) or not isinstance(head_responses, dict):
            return
        # Status codes are strings in OpenAPI but YAML may yield integers, so
        # compare them in one normalised form.
        head_responses = {str(code): value for code, value in head_responses.items()}
        for code, base_response in sorted(
            (str(code), value) for code, value in base_responses.items()
        ):
            if not code.startswith('2'):
                continue
            if code not in head_responses:
                self.report(
                    'response-status-removed',
                    f'{label}: {code} response was removed',
                )
                continue
            _, base_schemas = self.json_schemas(self.base, base_response)
            _, head_schemas = self.json_schemas(self.head, head_responses[code])
            for media in sorted(set(base_schemas) - set(head_schemas)):
                self.report(
                    'response-media-type-removed',
                    f'{label} {code} response: {media} was removed',
                )
            for media in sorted(set(base_schemas) & set(head_schemas)):
                self.compare_schema(
                    base_schemas[media],
                    head_schemas[media],
                    f'{label} {code} response',
                    'response',
                )

    def compare_paths(self):
        base_ops, head_ops = operations(self.base), operations(self.head)
        base_shared = shared_parameters(self.base)
        head_shared = shared_parameters(self.head)
        for key in sorted(base_ops):
            path, method = key
            label = f'{method.upper()} {path}'
            if key not in head_ops:
                self.report('operation-removed', f'{label} was removed')
                continue
            self.compare_operation(
                base_ops[key],
                head_ops[key],
                label,
                base_shared=base_shared.get(path, ()),
                head_shared=head_shared.get(path, ()),
            )

    def compare_webhooks(self):
        """Walk `webhooks` (3.1) and `x-webhooks` (3.0) payload schemas.

        A webhook payload is delivered to the consumer, so its request body
        is compared with the response rules.
        """
        for container in ('webhooks', 'x-webhooks'):
            base_hooks = self.base.get(container)
            if not isinstance(base_hooks, dict):
                continue
            head_hooks = self.head.get(container)
            if not isinstance(head_hooks, dict):
                # Dropping the container removes every webhook in it, so it is
                # treated as empty rather than skipped.
                head_hooks = {}
            for name in sorted(base_hooks):
                base_item, _ = self.resolve(self.base, base_hooks[name])
                head_item, _ = self.resolve(self.head, head_hooks.get(name))
                if not isinstance(base_item, dict):
                    continue
                if not isinstance(head_item, dict):
                    self.report('webhook-removed', f'webhook {name!r} was removed')
                    continue
                for method in METHODS:
                    base_op, head_op = base_item.get(method), head_item.get(method)
                    if not isinstance(base_op, dict):
                        continue
                    if not isinstance(head_op, dict):
                        self.report(
                            'webhook-operation-removed',
                            f'webhook {name}: {method.upper()} was removed',
                        )
                        continue
                    self.compare_operation(
                        base_op,
                        head_op,
                        f'webhook {name}',
                        request_direction='response',
                        base_shared=base_item.get('parameters') or (),
                        head_shared=head_item.get('parameters') or (),
                    )

    def compare_components(self):
        """Report `components/schemas` removals (rule 9).

        Content comparison happens through the operation and webhook walk,
        which reaches these schemas via their `$ref`s.
        """
        base_schemas = (self.base.get('components') or {}).get('schemas') or {}
        head_schemas = (self.head.get('components') or {}).get('schemas') or {}
        if not isinstance(base_schemas, dict) or not isinstance(head_schemas, dict):
            return
        for name in sorted(set(base_schemas) - set(head_schemas)):
            self.report('schema-removed', f'schema {name!r} was removed')

    def run(self):
        self.compare_paths()
        self.compare_webhooks()
        self.compare_components()
        return self.findings


def operations(doc):
    """Map `(path, method)` -> operation object."""
    out = {}
    paths = doc.get('paths')
    for path, item in (paths if isinstance(paths, dict) else {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method in METHODS and isinstance(op, dict):
                out[(path, method)] = op
    return out


def shared_parameters(doc):
    """Map `path` -> the path item's own `parameters` list.

    These apply to every operation under the path unless the operation
    declares a parameter with the same name and location.
    """
    out = {}
    paths = doc.get('paths')
    for path, item in (paths if isinstance(paths, dict) else {}).items():
        if isinstance(item, dict) and isinstance(item.get('parameters'), list):
            out[path] = item['parameters']
    return out


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


def compare(base, head):
    findings = Comparator(base, head).run()
    return {
        'findings': findings,
        'truncated': len(findings) >= MAX_FINDINGS,
        'summary': summarize(base, head),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('base', help='baseline description (YAML or JSON)')
    parser.add_argument('head', help='candidate description (YAML or JSON)')
    args = parser.parse_args(argv)

    result = compare(load(args.base), load(args.head))
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
