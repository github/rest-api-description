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
        self.assertEqual(out['superseded_30'], '1')
        self.assertEqual(out['superseded_31'], '')

    def test_ties_broken_by_number(self):
        same = '2026-01-01T00:00:00Z'
        out = as_dict(sel.outputs([
            pr(10, sel.TITLE_30, created=same),
            pr(11, sel.TITLE_30, created=same),
        ]))
        self.assertEqual(out['pr_30'], '11')
        self.assertEqual(out['superseded_30'], '10')

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
        self.assertEqual(out['superseded_30'], '1')
        self.assertEqual(out['superseded_31'], '')

    def test_only_unrelated_pull_requests_means_nothing_to_do(self):
        out = as_dict(sel.outputs([pr(1, 'Bump some dependency')]))
        self.assertEqual(out['found'], 'false')
        self.assertEqual(out['pr_30'], '')
        self.assertEqual(out['pr_31'], '')
        self.assertEqual(out['superseded_30'], '')
        self.assertEqual(out['superseded_31'], '')

    def test_empty_input(self):
        out = as_dict(sel.outputs([]))
        self.assertEqual(out['found'], 'false')
        self.assertEqual(out['superseded_30'], '')
        self.assertEqual(out['superseded_31'], '')

    def test_one_title_only(self):
        out = as_dict(sel.outputs([pr(9, sel.TITLE_31)]))
        self.assertEqual(out['found'], 'true')
        self.assertEqual(out['pr_30'], '')
        self.assertEqual(out['sha_30'], '')
        self.assertEqual(out['pr_31'], '9')
        self.assertEqual(out['superseded_31'], '')


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
        self.assertEqual(out['superseded_30'], '')

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
        self.assertEqual(out['superseded_30'], '')
        self.assertEqual(out['superseded_31'], '3')

    def test_superseded_numbers_stay_with_their_title(self):
        prs = [
            pr(1, sel.TITLE_30, created='2026-01-01T00:00:00Z'),
            pr(2, sel.TITLE_30, created='2026-01-04T00:00:00Z'),
            pr(3, sel.TITLE_31, created='2026-01-02T00:00:00Z'),
            pr(4, sel.TITLE_31, created='2026-01-03T00:00:00Z'),
        ]
        _, superseded = sel.select(prs)
        # The association is what lets the workflow confirm a pull request
        # still carries the title it was superseded under before closing it.
        self.assertEqual(superseded[sel.TITLE_30], [1])
        self.assertEqual(superseded[sel.TITLE_31], [3])

    def test_malformed_entries_are_ignored(self):
        out = as_dict(sel.outputs([
            'not a dict',
            {'title': sel.TITLE_30},
            pr(5, sel.TITLE_30),
        ]))
        self.assertEqual(out['pr_30'], '5')
        self.assertEqual(out['superseded_30'], '')


def api_pr(number, title, sha='sha', created='2026-01-01T00:00:00Z', login='bot'):
    """One entry shaped like the REST pulls endpoint returns it."""
    return {
        'number': number,
        'title': title,
        'head': {'sha': sha},
        'created_at': created,
        'user': {'login': login},
    }


class NormaliseTest(unittest.TestCase):
    """Reading every page matters: a dropped page leaves superseded PRs open."""

    def test_pages_are_flattened_and_fields_mapped(self):
        pages = [
            [api_pr(1, sel.TITLE_30, sha='a', created='2026-01-01T00:00:00Z')],
            [api_pr(2, sel.TITLE_30, sha='b', created='2026-02-01T00:00:00Z')],
        ]
        self.assertEqual(
            sel.normalise(pages, 'bot'),
            [
                {
                    'number': 1,
                    'title': sel.TITLE_30,
                    'headRefOid': 'a',
                    'createdAt': '2026-01-01T00:00:00Z',
                },
                {
                    'number': 2,
                    'title': sel.TITLE_30,
                    'headRefOid': 'b',
                    'createdAt': '2026-02-01T00:00:00Z',
                },
            ],
        )

    def test_a_flat_list_is_accepted_too(self):
        self.assertEqual(len(sel.normalise([api_pr(1, sel.TITLE_30)], 'bot')), 1)

    def test_another_author_is_never_eligible(self):
        pages = [[api_pr(1, sel.TITLE_30, login='someone-else')]]
        self.assertEqual(sel.normalise(pages, 'bot'), [])

    def test_an_unreadable_author_is_skipped_rather_than_assumed(self):
        pages = [[{'number': 1, 'title': sel.TITLE_30, 'head': {'sha': 'a'}}]]
        self.assertEqual(sel.normalise(pages, 'bot'), [])

    def test_a_malformed_entry_does_not_abort_the_page(self):
        pages = [['not a dict', api_pr(2, sel.TITLE_30), None]]
        self.assertEqual([pr['number'] for pr in sel.normalise(pages, 'bot')], [2])

    def test_a_missing_head_survives_normalisation_and_blocks_pinning(self):
        pages = [[{'number': 1, 'title': sel.TITLE_30, 'user': {'login': 'bot'}}]]
        normalised = sel.normalise(pages, 'bot')
        self.assertIsNone(normalised[0]['headRefOid'])
        self.assertEqual(sel.outputs(normalised)[0], 'found=false')

    def test_an_older_pull_request_on_a_later_page_is_still_superseded(self):
        # The regression this guards: the oldest matches arrive last, and
        # dropping them would leave a stale pull request open to be selected
        # by a later run once the merged one closes.
        pages = [
            [api_pr(9, sel.TITLE_30, sha='new', created='2026-05-01T00:00:00Z')],
            [api_pr(1, sel.TITLE_30, sha='old', created='2026-01-01T00:00:00Z')],
        ]
        out = dict(line.split('=', 1) for line in sel.outputs(sel.normalise(pages, 'bot')))
        self.assertEqual(out['pr_30'], '9')
        self.assertEqual(out['sha_30'], 'new')
        self.assertEqual(out['superseded_30'], '1')


class CliTest(unittest.TestCase):
    def _run(self, argv):
        import io

        captured, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = sel.main(argv)
            printed = sys.stdout.getvalue().splitlines()
        finally:
            sys.stdout = captured
        return code, printed

    def test_title_flag_prints_the_exact_title_for_a_group(self):
        self.assertEqual(self._run(['--title', '30']), (0, [sel.TITLE_30]))
        self.assertEqual(self._run(['--title', '31']), (0, [sel.TITLE_31]))

    def test_selecting_without_an_author_is_refused(self):
        import io

        captured, sys.stderr = sys.stderr, io.StringIO()
        try:
            self.assertEqual(sel.main([]), 2)
        finally:
            sys.stderr = captured

    def test_title_flag_rejects_an_unknown_group(self):
        import io

        captured, sys.stderr = sys.stderr, io.StringIO()
        try:
            with self.assertRaises(SystemExit):
                sel.main(['--title', '32'])
        finally:
            sys.stderr = captured


if __name__ == '__main__':
    unittest.main()
