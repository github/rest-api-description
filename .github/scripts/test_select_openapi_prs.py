#!/usr/bin/env python3
"""Tests for select_openapi_prs.

Run with: python3 -m unittest discover -s .github/scripts
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import select_openapi_prs as sel  # noqa: E402


def pr(number, title, sha=None, created='2026-01-01T00:00:00Z'):
    return {
        'number': number,
        'title': title,
        'headRefOid': sha if sha is not None else f'{number:040x}',
        'createdAt': created,
    }


def as_dict(lines):
    return dict(line.split('=', 1) for line in lines)


class SelectionTest(unittest.TestCase):
    def test_selects_newest_per_title(self):
        prs = [
            pr(1, sel.TITLE_30, created='2026-01-01T00:00:00Z'),
            pr(2, sel.TITLE_30, created='2026-01-03T00:00:00Z'),
            pr(3, sel.TITLE_31, created='2026-01-02T00:00:00Z'),
        ]
        out = as_dict(sel.outputs(prs))
        self.assertEqual(out['found'], 'true')
        self.assertEqual(out['pr_30'], '2')
        self.assertEqual(out['pr_31'], '3')
        self.assertEqual(out['superseded'], '1')

    def test_ties_broken_by_number(self):
        same = '2026-01-01T00:00:00Z'
        out = as_dict(sel.outputs([
            pr(10, sel.TITLE_30, created=same),
            pr(11, sel.TITLE_30, created=same),
        ]))
        self.assertEqual(out['pr_30'], '11')
        self.assertEqual(out['superseded'], '10')

    def test_unrelated_bot_pull_requests_are_never_superseded(self):
        prs = [
            pr(1, sel.TITLE_30, created='2026-01-01T00:00:00Z'),
            pr(2, sel.TITLE_30, created='2026-01-02T00:00:00Z'),
            pr(3, 'Bump some dependency'),
            pr(4, 'Update OpenAPI 3.0 Descriptions '),
            pr(5, 'update openapi 3.0 descriptions'),
            pr(6, 'Update OpenAPI 3.2 Descriptions'),
            pr(7, 'Revert "Update OpenAPI 3.0 Descriptions"'),
        ]
        out = as_dict(sel.outputs(prs))
        self.assertEqual(out['pr_30'], '2')
        self.assertEqual(out['superseded'], '1')

    def test_only_unrelated_pull_requests_means_nothing_to_do(self):
        out = as_dict(sel.outputs([pr(1, 'Bump some dependency')]))
        self.assertEqual(out['found'], 'false')
        self.assertEqual(out['pr_30'], '')
        self.assertEqual(out['pr_31'], '')
        self.assertEqual(out['superseded'], '')

    def test_empty_input(self):
        out = as_dict(sel.outputs([]))
        self.assertEqual(out['found'], 'false')
        self.assertEqual(out['superseded'], '')

    def test_one_title_only(self):
        out = as_dict(sel.outputs([pr(9, sel.TITLE_31)]))
        self.assertEqual(out['found'], 'true')
        self.assertEqual(out['pr_30'], '')
        self.assertEqual(out['sha_30'], '')
        self.assertEqual(out['pr_31'], '9')
        self.assertEqual(out['superseded'], '')


class ShaPinningTest(unittest.TestCase):
    def test_head_sha_is_emitted_for_each_selection(self):
        out = as_dict(sel.outputs([
            pr(1, sel.TITLE_30, sha='a' * 40),
            pr(2, sel.TITLE_31, sha='b' * 40),
        ]))
        self.assertEqual(out['sha_30'], 'a' * 40)
        self.assertEqual(out['sha_31'], 'b' * 40)

    def test_sha_tracks_the_newest_pull_request_not_the_first(self):
        out = as_dict(sel.outputs([
            pr(1, sel.TITLE_30, sha='a' * 40, created='2026-01-01T00:00:00Z'),
            pr(2, sel.TITLE_30, sha='c' * 40, created='2026-02-01T00:00:00Z'),
        ]))
        self.assertEqual(out['pr_30'], '2')
        self.assertEqual(out['sha_30'], 'c' * 40)

    def test_pull_request_without_head_sha_blocks_closing_its_siblings(self):
        prs = [
            pr(1, sel.TITLE_30, created='2026-01-01T00:00:00Z'),
            pr(2, sel.TITLE_30, sha='', created='2026-01-02T00:00:00Z'),
        ]
        out = as_dict(sel.outputs(prs))
        self.assertEqual(out['found'], 'false')
        self.assertEqual(out['pr_30'], '')
        self.assertEqual(out['sha_30'], '')
        # #1 is older, but its replacement was never validated, so it must
        # not be closed.
        self.assertEqual(out['superseded'], '')

    def test_unpinnable_title_does_not_block_the_other_title(self):
        prs = [
            pr(1, sel.TITLE_30, created='2026-01-01T00:00:00Z'),
            pr(2, sel.TITLE_30, sha='', created='2026-01-02T00:00:00Z'),
            pr(3, sel.TITLE_31, created='2026-01-01T00:00:00Z'),
            pr(4, sel.TITLE_31, created='2026-01-02T00:00:00Z'),
        ]
        out = as_dict(sel.outputs(prs))
        self.assertEqual(out['found'], 'true')
        self.assertEqual(out['pr_30'], '')
        self.assertEqual(out['pr_31'], '4')
        # Only the 3.1 sibling is superseded; the 3.0 pair is left alone.
        self.assertEqual(out['superseded'], '3')

    def test_titles_flag_lists_recognised_titles(self):
        self.assertEqual(list(sel.TITLES), [sel.TITLE_30, sel.TITLE_31])

    def test_malformed_entries_are_ignored(self):
        out = as_dict(sel.outputs([
            'not a dict',
            {'title': sel.TITLE_30},
            pr(5, sel.TITLE_30),
        ]))
        self.assertEqual(out['pr_30'], '5')
        self.assertEqual(out['superseded'], '')


class CliTest(unittest.TestCase):
    def test_titles_flag_prints_exact_titles(self):
        import io

        captured, sys.stdout = sys.stdout, io.StringIO()
        try:
            self.assertEqual(sel.main(['--titles']), 0)
            printed = sys.stdout.getvalue().splitlines()
        finally:
            sys.stdout = captured

        self.assertEqual(printed, [sel.TITLE_30, sel.TITLE_31])


if __name__ == '__main__':
    unittest.main()
