#!/usr/bin/env python3
"""Tests for openapi_breaking_changes.

Run with: python3 -m unittest discover -s .github/scripts
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openapi_breaking_changes as obc  # noqa: E402


def doc(paths=None, schemas=None, **extra):
    out = {'openapi': '3.0.3', 'paths': paths or {}}
    if schemas is not None:
        out['components'] = {'schemas': schemas}
    out.update(extra)
    return out


def get_op(schema, method='get', path='/thing'):
    """A document with one operation returning `schema` as a 200 body."""
    return doc(paths={
        path: {
            method: {
                'operationId': 'thing/get',
                'responses': {
                    '200': {
                        'description': 'ok',
                        'content': {'application/json': {'schema': schema}},
                    }
                },
            }
        }
    })


def post_op(schema, required=False, path='/thing'):
    """A document with one operation accepting `schema` as a request body."""
    return doc(paths={
        path: {
            'post': {
                'operationId': 'thing/create',
                'requestBody': {
                    'required': required,
                    'content': {'application/json': {'schema': schema}},
                },
                'responses': {'201': {'description': 'created'}},
            }
        }
    })


def rules(base, head):
    return sorted(f['rule'] for f in obc.compare(base, head)['findings'])


def details(base, head, rule):
    return [f['detail'] for f in obc.compare(base, head)['findings'] if f['rule'] == rule]


class NoChangeTest(unittest.TestCase):
    def test_identical_documents_are_clean(self):
        base = get_op({'type': 'object', 'properties': {'id': {'type': 'integer'}}})
        self.assertEqual(rules(base, copy.deepcopy(base)), [])

    def test_additions_are_not_breaking(self):
        base = get_op({'type': 'object', 'properties': {'id': {'type': 'integer'}}})
        head = get_op({
            'type': 'object',
            'properties': {'id': {'type': 'integer'}, 'name': {'type': 'string'}},
        })
        head['paths']['/added'] = {'get': {'operationId': 'a/b', 'responses': {}}}
        self.assertEqual(rules(base, head), [])


class OperationTest(unittest.TestCase):
    def test_operation_removed(self):
        base = get_op({'type': 'object'})
        self.assertEqual(rules(base, doc()), ['operation-removed'])

    def test_operationid_changed(self):
        base = get_op({'type': 'object'})
        head = copy.deepcopy(base)
        head['paths']['/thing']['get']['operationId'] = 'thing/fetch'
        self.assertEqual(rules(base, head), ['operationid-changed'])

    def test_path_parameter_renamed_behind_a_ref(self):
        base = doc(paths={
            '/repos/{owner}': {
                'get': {
                    'operationId': 'repos/get',
                    'parameters': [{'$ref': '#/components/parameters/owner'}],
                    'responses': {},
                }
            }
        })
        base['components'] = {
            'parameters': {'owner': {'name': 'owner', 'in': 'path', 'required': True}}
        }
        head = copy.deepcopy(base)
        head['components']['parameters']['owner']['name'] = 'org'
        self.assertEqual(rules(base, head), ['url-parameter-renamed'])
        self.assertIn('owner', details(base, head, 'url-parameter-renamed')[0])

    def test_query_parameter_removal_is_not_reported(self):
        base = doc(paths={
            '/thing': {
                'get': {
                    'operationId': 'thing/get',
                    'parameters': [{'name': 'per_page', 'in': 'query'}],
                    'responses': {},
                }
            }
        })
        head = copy.deepcopy(base)
        head['paths']['/thing']['get']['parameters'] = []
        self.assertEqual(rules(base, head), [])

    def _param_docs(self, base_param, head_param):
        def build(param):
            return doc(paths={'/thing': {'get': {
                'operationId': 'thing/get',
                'parameters': [param],
                'responses': {},
            }}})

        return build(base_param), build(head_param)

    def test_parameter_became_required(self):
        base, head = self._param_docs(
            {'name': 'state', 'in': 'query', 'schema': {'type': 'string'}},
            {'name': 'state', 'in': 'query', 'required': True,
             'schema': {'type': 'string'}},
        )
        self.assertEqual(rules(base, head), ['parameter-now-required'])

    def test_parameter_enum_value_removed(self):
        base, head = self._param_docs(
            {'name': 'state', 'in': 'query',
             'schema': {'type': 'string', 'enum': ['open', 'closed', 'all']}},
            {'name': 'state', 'in': 'query',
             'schema': {'type': 'string', 'enum': ['open', 'closed']}},
        )
        self.assertEqual(rules(base, head), ['enum-value-removed'])

    def test_parameter_schema_widening_is_not_breaking(self):
        base, head = self._param_docs(
            {'name': 'id', 'in': 'query', 'schema': {'type': 'integer'}},
            {'name': 'id', 'in': 'query', 'schema': {'type': ['integer', 'string']}},
        )
        self.assertEqual(rules(base, head), [])

    def test_success_status_removed(self):
        base = doc(paths={'/thing': {'get': {
            'operationId': 'thing/get',
            'responses': {'200': {'description': 'ok'}, '204': {'description': 'empty'}},
        }}})
        head = doc(paths={'/thing': {'get': {
            'operationId': 'thing/get',
            'responses': {'200': {'description': 'ok'}},
        }}})
        self.assertEqual(rules(base, head), ['response-status-removed'])

    def test_error_status_removal_is_not_reported(self):
        base = doc(paths={'/thing': {'get': {
            'operationId': 'thing/get',
            'responses': {'200': {'description': 'ok'}, '404': {'description': 'gone'}},
        }}})
        head = doc(paths={'/thing': {'get': {
            'operationId': 'thing/get',
            'responses': {'200': {'description': 'ok'}},
        }}})
        self.assertEqual(rules(base, head), [])

    def test_integer_status_keys_are_normalised(self):
        base = doc(paths={'/thing': {'get': {
            'operationId': 'thing/get',
            'responses': {200: {'description': 'ok'}},
        }}})
        head = doc(paths={'/thing': {'get': {
            'operationId': 'thing/get',
            'responses': {'200': {'description': 'ok'}},
        }}})
        self.assertEqual(rules(base, head), [])

    def test_json_media_type_removed(self):
        base = get_op({'type': 'object'})
        head = copy.deepcopy(base)
        content = head['paths']['/thing']['get']['responses']['200']['content']
        content['text/plain'] = content.pop('application/json')
        self.assertEqual(rules(base, head), ['response-media-type-removed'])


class RequestDirectionTest(unittest.TestCase):
    def test_request_body_became_required(self):
        base = post_op({'type': 'object'}, required=False)
        head = post_op({'type': 'object'}, required=True)
        self.assertEqual(rules(base, head), ['requestbody-now-required'])

    def test_request_body_removed_entirely(self):
        base = post_op({'type': 'object'}, required=True)
        head = copy.deepcopy(base)
        del head['paths']['/thing']['post']['requestBody']
        self.assertEqual(rules(base, head), ['request-body-removed'])

    def test_optional_request_body_removed_is_still_reported(self):
        base = post_op({'type': 'object'}, required=False)
        head = copy.deepcopy(base)
        del head['paths']['/thing']['post']['requestBody']
        self.assertEqual(rules(base, head), ['request-body-removed'])

    def test_request_json_media_type_removed(self):
        base = post_op({'type': 'object'})
        head = copy.deepcopy(base)
        content = head['paths']['/thing']['post']['requestBody']['content']
        content['multipart/form-data'] = content.pop('application/json')
        self.assertEqual(rules(base, head), ['request-media-type-removed'])
        self.assertEqual(
            details(base, head, 'request-media-type-removed'),
            ['POST /thing request body: application/json was removed'],
        )

    def test_added_request_media_type_is_not_breaking(self):
        base = post_op({'type': 'object'})
        head = copy.deepcopy(base)
        head['paths']['/thing']['post']['requestBody']['content']['application/vnd.v3+json'] = {
            'schema': {'type': 'object'}
        }
        self.assertEqual(rules(base, head), [])

    def test_adding_a_request_body_is_not_breaking(self):
        head = post_op({'type': 'object'}, required=False)
        base = copy.deepcopy(head)
        del base['paths']['/thing']['post']['requestBody']
        self.assertEqual(rules(base, head), [])

    def test_newly_required_request_field(self):
        schema = {'type': 'object', 'properties': {'name': {'type': 'string'}}}
        head_schema = dict(schema, required=['name'])
        self.assertEqual(
            rules(post_op(schema), post_op(head_schema)),
            ['requestbody-required-added'],
        )

    def test_dropping_a_required_request_field_is_not_breaking(self):
        schema = {'type': 'object', 'properties': {'name': {'type': 'string'}}}
        self.assertEqual(
            rules(post_op(dict(schema, required=['name'])), post_op(schema)),
            [],
        )

    def test_removing_a_request_property_is_not_breaking(self):
        base = post_op({
            'type': 'object',
            'properties': {'name': {'type': 'string'}, 'note': {'type': 'string'}},
        })
        head = post_op({'type': 'object', 'properties': {'name': {'type': 'string'}}})
        self.assertEqual(rules(base, head), [])

    def test_widening_a_request_type_is_not_breaking(self):
        base = post_op({'type': 'object', 'properties': {'id': {'type': 'integer'}}})
        head = post_op({
            'type': 'object',
            'properties': {'id': {'type': ['integer', 'string']}},
        })
        self.assertEqual(rules(base, head), [])

    def test_narrowing_a_request_type_is_breaking(self):
        base = post_op({
            'type': 'object',
            'properties': {'id': {'type': ['integer', 'string']}},
        })
        head = post_op({'type': 'object', 'properties': {'id': {'type': 'integer'}}})
        self.assertEqual(rules(base, head), ['field-type-changed'])


class ResponseDirectionTest(unittest.TestCase):
    def test_response_field_removed(self):
        base = get_op({
            'type': 'object',
            'properties': {'id': {'type': 'integer'}, 'name': {'type': 'string'}},
        })
        head = get_op({'type': 'object', 'properties': {'id': {'type': 'integer'}}})
        self.assertEqual(rules(base, head), ['response-field-removed'])

    def test_response_required_removed(self):
        schema = {'type': 'object', 'properties': {'id': {'type': 'integer'}}}
        base = get_op(dict(schema, required=['id']))
        self.assertEqual(rules(base, get_op(schema)), ['response-required-removed'])

    def test_adding_a_response_required_field_is_not_breaking(self):
        schema = {'type': 'object', 'properties': {'id': {'type': 'integer'}}}
        self.assertEqual(rules(get_op(schema), get_op(dict(schema, required=['id']))), [])

    def test_response_type_change_in_either_direction(self):
        base = get_op({'type': 'object', 'properties': {'id': {'type': 'integer'}}})
        head = get_op({
            'type': 'object',
            'properties': {'id': {'type': ['integer', 'null']}},
        })
        self.assertEqual(rules(base, head), ['field-type-changed'])


class NestedTest(unittest.TestCase):
    """The previous shallow comparison missed everything in this class."""

    def test_nested_inline_object(self):
        base = get_op({
            'type': 'object',
            'properties': {
                'owner': {
                    'type': 'object',
                    'properties': {'login': {'type': 'string'}, 'id': {'type': 'integer'}},
                }
            },
        })
        head = copy.deepcopy(base)
        del head['paths']['/thing']['get']['responses']['200']['content'][
            'application/json']['schema']['properties']['owner']['properties']['login']
        self.assertEqual(rules(base, head), ['response-field-removed'])
        self.assertIn('.owner.login', details(base, head, 'response-field-removed')[0])

    def test_three_levels_deep(self):
        def build(leaf):
            return get_op({
                'type': 'object',
                'properties': {
                    'a': {
                        'type': 'object',
                        'properties': {
                            'b': {'type': 'object', 'properties': {'c': leaf}},
                        },
                    }
                },
            })

        self.assertEqual(
            rules(build({'type': 'string'}), build({'type': 'integer'})),
            ['field-type-changed'],
        )

    def test_array_items(self):
        base = get_op({
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {'id': {'type': 'integer'}, 'name': {'type': 'string'}},
            },
        })
        head = get_op({
            'type': 'array',
            'items': {'type': 'object', 'properties': {'id': {'type': 'integer'}}},
        })
        self.assertEqual(rules(base, head), ['response-field-removed'])
        self.assertIn('[].name', details(base, head, 'response-field-removed')[0])

    def test_array_of_arrays(self):
        base = get_op({
            'type': 'array',
            'items': {'type': 'array', 'items': {'type': 'string'}},
        })
        head = get_op({
            'type': 'array',
            'items': {'type': 'array', 'items': {'type': 'integer'}},
        })
        self.assertEqual(rules(base, head), ['field-type-changed'])

    def test_additional_properties_schema(self):
        base = get_op({
            'type': 'object',
            'additionalProperties': {
                'type': 'object',
                'properties': {'id': {'type': 'integer'}},
            },
        })
        head = get_op({'type': 'object', 'additionalProperties': {'type': 'object'}})
        self.assertEqual(rules(base, head), ['response-field-removed'])

    def test_additional_properties_narrowed_to_false(self):
        base = get_op({'type': 'object', 'additionalProperties': True})
        head = get_op({'type': 'object', 'additionalProperties': False})
        self.assertEqual(rules(base, head), ['additional-properties-restricted'])

    def test_additional_properties_absent_then_false(self):
        base = get_op({'type': 'object', 'properties': {}})
        head = get_op({'type': 'object', 'properties': {}, 'additionalProperties': False})
        self.assertEqual(rules(base, head), ['additional-properties-restricted'])

    def test_additional_properties_widened_is_not_breaking(self):
        base = get_op({'type': 'object', 'additionalProperties': False})
        head = get_op({'type': 'object', 'additionalProperties': True})
        self.assertEqual(rules(base, head), [])

    def test_tuple_item_removed(self):
        base = get_op({
            'type': 'array',
            'items': [{'type': 'string'}, {'type': 'integer'}],
        })
        head = get_op({'type': 'array', 'items': [{'type': 'string'}]})
        self.assertEqual(rules(base, head), ['tuple-items-removed'])

    def test_tuple_item_type_changed(self):
        base = get_op({
            'type': 'array',
            'items': [{'type': 'string'}, {'type': 'integer'}],
        })
        head = get_op({
            'type': 'array',
            'items': [{'type': 'string'}, {'type': 'boolean'}],
        })
        self.assertEqual(rules(base, head), ['field-type-changed'])

    def test_item_schema_removed(self):
        base = get_op({'type': 'array', 'items': {'type': 'string'}})
        head = get_op({'type': 'array'})
        self.assertEqual(rules(base, head), ['array-items-removed'])

    def test_item_schema_shape_changed(self):
        base = get_op({'type': 'array', 'items': [{'type': 'string'}]})
        head = get_op({'type': 'array', 'items': {'type': 'string'}})
        self.assertEqual(rules(base, head), ['array-items-changed'])


class ReferenceTest(unittest.TestCase):
    def _ref_docs(self, base_schema, head_schema):
        base = get_op({'$ref': '#/components/schemas/thing'})
        base['components'] = {'schemas': {'thing': base_schema}}
        head = get_op({'$ref': '#/components/schemas/thing'})
        head['components'] = {'schemas': {'thing': head_schema}}
        return base, head

    def test_field_removed_behind_a_ref(self):
        base, head = self._ref_docs(
            {'type': 'object', 'properties': {'id': {'type': 'integer'}, 'x': {'type': 'string'}}},
            {'type': 'object', 'properties': {'id': {'type': 'integer'}}},
        )
        self.assertEqual(rules(base, head), ['response-field-removed'])

    def test_ref_chain_is_followed(self):
        base = get_op({'$ref': '#/components/schemas/alias'})
        base['components'] = {'schemas': {
            'alias': {'$ref': '#/components/schemas/thing'},
            'thing': {'type': 'object', 'properties': {'id': {'type': 'integer'}}},
        }}
        head = copy.deepcopy(base)
        head['components']['schemas']['thing']['properties']['id']['type'] = 'string'
        self.assertEqual(rules(base, head), ['field-type-changed'])

    def test_response_object_ref_is_followed(self):
        base = doc(paths={'/thing': {'get': {
            'operationId': 'thing/get',
            'responses': {'200': {'$ref': '#/components/responses/thing'}},
        }}})
        base['components'] = {'responses': {'thing': {
            'description': 'ok',
            'content': {'application/json': {'schema': {
                'type': 'object',
                'properties': {'id': {'type': 'integer'}, 'x': {'type': 'string'}},
            }}},
        }}}
        head = copy.deepcopy(base)
        del head['components']['responses']['thing']['content'][
            'application/json']['schema']['properties']['x']
        self.assertEqual(rules(base, head), ['response-field-removed'])

    def test_removed_component_schema(self):
        base = get_op({'$ref': '#/components/schemas/thing'})
        base['components'] = {'schemas': {'thing': {'type': 'object'}}}
        head = get_op({'$ref': '#/components/schemas/thing'})
        head['components'] = {'schemas': {}}
        self.assertEqual(rules(base, head), ['schema-removed', 'schema-removed'])

    def test_unreferenced_component_removal_is_reported(self):
        base = doc(schemas={'orphan': {'type': 'object'}})
        head = doc(schemas={})
        self.assertEqual(rules(base, head), ['schema-removed'])

    def test_recursive_schema_terminates(self):
        def build(leaf_type):
            document = get_op({'$ref': '#/components/schemas/node'})
            document['components'] = {'schemas': {'node': {
                'type': 'object',
                'properties': {
                    'value': {'type': leaf_type},
                    'parent': {'$ref': '#/components/schemas/node'},
                    'children': {
                        'type': 'array',
                        'items': {'$ref': '#/components/schemas/node'},
                    },
                },
            }}}
            return document

        self.assertEqual(rules(build('string'), build('integer')), ['field-type-changed'])

    def test_self_referential_ref_does_not_hang(self):
        base = get_op({'$ref': '#/components/schemas/loop'})
        base['components'] = {'schemas': {'loop': {'$ref': '#/components/schemas/loop'}}}
        self.assertEqual(rules(base, copy.deepcopy(base)), [])


class CompositionTest(unittest.TestCase):
    def test_allof_member_field_removed(self):
        base = get_op({'allOf': [
            {'type': 'object', 'properties': {'id': {'type': 'integer'}}},
            {'type': 'object', 'properties': {'name': {'type': 'string'}}},
        ]})
        head = get_op({'allOf': [
            {'type': 'object', 'properties': {'id': {'type': 'integer'}}},
        ]})
        self.assertEqual(rules(base, head), ['response-field-removed'])

    def test_allof_via_ref_field_type_changed(self):
        base = get_op({'allOf': [
            {'$ref': '#/components/schemas/base'},
            {'type': 'object', 'properties': {'extra': {'type': 'string'}}},
        ]})
        base['components'] = {'schemas': {'base': {
            'type': 'object', 'properties': {'id': {'type': 'integer'}},
        }}}
        head = copy.deepcopy(base)
        head['components']['schemas']['base']['properties']['id']['type'] = 'string'
        self.assertEqual(rules(base, head), ['field-type-changed'])

    def test_allof_inherited_required_removed(self):
        def build(required):
            document = get_op({'allOf': [
                {'$ref': '#/components/schemas/base'},
                {'type': 'object', 'properties': {'extra': {'type': 'string'}}},
            ]})
            document['components'] = {'schemas': {'base': {
                'type': 'object',
                'properties': {'id': {'type': 'integer'}},
                'required': required,
            }}}
            return document

        self.assertEqual(rules(build(['id']), build([])), ['response-required-removed'])

    def test_nested_allof_is_flattened(self):
        def build(props):
            return get_op({'allOf': [
                {'allOf': [{'type': 'object', 'properties': props}]},
            ]})

        self.assertEqual(
            rules(build({'a': {'type': 'string'}, 'b': {'type': 'string'}}),
                  build({'a': {'type': 'string'}})),
            ['response-field-removed'],
        )

    def test_oneof_member_is_compared(self):
        def build(leaf):
            document = get_op({'oneOf': [
                {'$ref': '#/components/schemas/simple'},
                {'$ref': '#/components/schemas/full'},
            ]})
            document['components'] = {'schemas': {
                'simple': {'type': 'string'},
                'full': {'type': 'object', 'properties': {'id': leaf}},
            }}
            return document

        self.assertEqual(
            rules(build({'type': 'integer'}), build({'type': 'string'})),
            ['field-type-changed'],
        )

    def test_anyof_member_matched_by_title(self):
        def build(leaf):
            return get_op({'anyOf': [
                {'title': 'a', 'type': 'object', 'properties': {'x': leaf}},
                {'title': 'b', 'type': 'string'},
            ]})

        # Reordering alone is not a finding; the type change is.
        head = build({'type': 'integer'})
        head['paths']['/thing']['get']['responses']['200']['content'][
            'application/json']['schema']['anyOf'].reverse()
        self.assertEqual(rules(build({'type': 'string'}), head), ['field-type-changed'])

    def test_request_union_member_removed_is_breaking(self):
        base = post_op({'oneOf': [{'type': 'string'}, {'type': 'integer'}]})
        head = post_op({'oneOf': [{'type': 'string'}]})
        self.assertEqual(rules(base, head), ['request-variant-removed'])

    def test_response_union_member_removed_is_not_reported(self):
        base = get_op({'oneOf': [
            {'title': 'a', 'type': 'string'},
            {'title': 'b', 'type': 'integer'},
        ]})
        head = get_op({'oneOf': [{'title': 'a', 'type': 'string'}]})
        self.assertEqual(rules(base, head), [])


class EnumTest(unittest.TestCase):
    def test_enum_value_removed_at_depth(self):
        def build(values):
            return get_op({
                'type': 'object',
                'properties': {
                    'items': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {'state': {'type': 'string', 'enum': values}},
                        },
                    }
                },
            })

        base, head = build(['open', 'closed', 'draft']), build(['open', 'closed'])
        self.assertEqual(rules(base, head), ['enum-value-removed'])
        self.assertIn('draft', details(base, head, 'enum-value-removed')[0])

    def test_awkward_scalar_enum_values(self):
        awkward = ['+1', '-1', "won't fix", 'false positive', True, False, None, 1]

        def build(values):
            return get_op({'type': 'object', 'properties': {
                'reaction': {'enum': values},
            }})

        base = build(awkward)
        head = build([v for v in awkward if v != '+1'])
        self.assertEqual(rules(base, head), ['enum-value-removed'])
        self.assertIn('+1', details(base, head, 'enum-value-removed')[0])

    def test_boolean_and_string_enum_values_are_distinct(self):
        def build(values):
            return get_op({'type': 'object', 'properties': {'flag': {'enum': values}}})

        self.assertEqual(rules(build([True]), build(['true'])), ['enum-value-removed'])

    def test_enum_value_added_is_not_reported(self):
        def build(values):
            return get_op({'type': 'object', 'properties': {
                'state': {'type': 'string', 'enum': values},
            }})

        self.assertEqual(rules(build(['open']), build(['open', 'closed'])), [])


class WebhookTest(unittest.TestCase):
    def _hooks(self, container, leaf):
        return doc(**{container: {'push': {'post': {
            'operationId': 'webhook/push',
            'requestBody': {'content': {'application/json': {'schema': {
                'type': 'object',
                'properties': {'ref': leaf},
            }}}},
            'responses': {},
        }}}})

    def test_x_webhooks_payload_uses_response_rules(self):
        base = self._hooks('x-webhooks', {'type': 'string'})
        head = doc(**{'x-webhooks': {'push': {'post': {
            'operationId': 'webhook/push',
            'requestBody': {'content': {'application/json': {'schema': {
                'type': 'object', 'properties': {},
            }}}},
            'responses': {},
        }}}})
        self.assertEqual(rules(base, head), ['response-field-removed'])

    def test_webhook_removed(self):
        base = self._hooks('webhooks', {'type': 'string'})
        self.assertEqual(rules(base, doc(webhooks={})), ['webhook-removed'])


class OutputTest(unittest.TestCase):
    def test_summary_counts_additions(self):
        base = get_op({'type': 'object'}, path='/a')
        head = copy.deepcopy(base)
        head['paths']['/b'] = {'get': {'operationId': 'b', 'responses': {}}}
        head['components'] = {'schemas': {'new': {'type': 'object'}}}
        summary = obc.compare(base, head)['summary']
        self.assertEqual(summary['added_operations'], ['GET /b'])
        self.assertEqual(summary['added_schemas'], ['new'])
        self.assertEqual(summary['total_operations'], 2)

    def test_findings_are_capped_and_flagged(self):
        props = {f'p{i}': {'type': 'string'} for i in range(obc.MAX_FINDINGS + 25)}
        base = get_op({'type': 'object', 'properties': props})
        head = get_op({'type': 'object', 'properties': {}})
        result = obc.compare(base, head)
        self.assertEqual(len(result['findings']), obc.MAX_FINDINGS)
        self.assertTrue(result['truncated'])

    def test_shared_schema_is_compared_once(self):
        shared = {'$ref': '#/components/schemas/thing'}
        base = doc(paths={
            '/a': {'get': {'operationId': 'a', 'responses': {'200': {
                'description': 'ok', 'content': {'application/json': {'schema': dict(shared)}}}}}},
            '/b': {'get': {'operationId': 'b', 'responses': {'200': {
                'description': 'ok', 'content': {'application/json': {'schema': dict(shared)}}}}}},
        }, schemas={'thing': {
            'type': 'object', 'properties': {'id': {'type': 'integer'}},
        }})
        head = copy.deepcopy(base)
        head['components']['schemas']['thing']['properties'] = {}
        # Both operations reference the same schema object, so the removal is
        # reported once rather than once per reference site.
        findings = obc.compare(base, head)['findings']
        self.assertEqual([f['rule'] for f in findings], ['response-field-removed'])

    def test_cli_round_trip(self):
        import io
        import json
        import tempfile

        import yaml

        base = get_op({'type': 'object', 'properties': {'id': {'type': 'integer'}}})
        head = get_op({'type': 'object', 'properties': {}})
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, document in (('base.yaml', base), ('head.yaml', head)):
                path = os.path.join(tmp, name)
                with open(path, 'w', encoding='utf-8') as handle:
                    yaml.safe_dump(document, handle)
                paths.append(path)

            captured, sys.stdout = sys.stdout, io.StringIO()
            try:
                self.assertEqual(obc.main(paths), 0)
                payload = json.loads(sys.stdout.getvalue())
            finally:
                sys.stdout = captured

        self.assertEqual(
            [f['rule'] for f in payload['findings']], ['response-field-removed']
        )


if __name__ == '__main__':
    unittest.main()
