#!/usr/bin/env python3
"""Tests for the auto-merge workflow's freeze gate.

Run with: python3 -m unittest discover -s .github/scripts
"""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / 'workflows/auto-merge-openapi-updates.yml'
FREEZE_STEP = textwrap.dedent(
    WORKFLOW.read_text()
    .split('        id: freeze\n', 1)[1]
    .split('        run: |\n', 1)[1]
    .split('\n      - name:', 1)[0]
)

# Model a candidate with a new GHES directory so the old inference would freeze.
GH_STUB = r'''
gh() {
  printf '%s\n' "$*" >>"$GH_CALLS"
  case "$1 $2" in
    'label list')
      printf '%s\n' "$FREEZE_LABELS"
      if [ "$FAIL_READ" = labels ]; then
        echo 'Could not read labels (HTTP 503)' >&2
        return 1
      fi
      ;;
    'issue list')
      printf '%s\n' "$FREEZE_ISSUES"
      if [ "$FAIL_READ" = issues ]; then
        echo 'Could not read issues (HTTP 503)' >&2
        return 1
      fi
      ;;
    api\ *)
      printf '%s\n' ghes-3.98
      if [[ "$2" != *'?ref=main' ]]; then
        printf '%s\n' ghes-3.99
      fi
      ;;
    *)
      echo "Unexpected gh command: $*" >&2
      return 99
      ;;
  esac
}
'''


class MergeFreezeTest(unittest.TestCase):
    def run_freeze(self, labels='merge-freeze', issues='', fail_read=''):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            calls = Path(directory) / 'calls'
            output.touch()
            calls.touch()
            result = subprocess.run(
                ['bash', '-c', GH_STUB + FREEZE_STEP],
                cwd=directory,
                env={
                    **os.environ,
                    'GH_REPO': 'test/repo',
                    'GH_CALLS': str(calls),
                    'GITHUB_OUTPUT': str(output),
                    'FREEZE_LABELS': labels,
                    'FREEZE_ISSUES': issues,
                    'FAIL_READ': fail_read,
                    'DEFAULT_BRANCH': 'main',
                    'SHA_30': 'a' * 40,
                    'SHA_31': 'b' * 40,
                },
                capture_output=True,
                text=True,
            )
            outputs = dict(line.split('=', 1) for line in output.read_text().splitlines())
            return result, outputs, calls.read_text()

    def test_open_freeze_issue_holds_merges(self):
        result, outputs, calls = self.run_freeze(issues='#123 Release freeze')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs['status'], 'frozen')
        self.assertIn('#123 Release freeze', outputs['detail'])
        self.assertIn('issue list --label merge-freeze --state open', calls)

    def test_no_open_freeze_issue_allows_new_ghes_directory(self):
        result, outputs, calls = self.run_freeze()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs['status'], 'clear')
        self.assertNotIn('/contents/', calls)

    def test_missing_freeze_label_allows_progress(self):
        result, outputs, calls = self.run_freeze(labels='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs['status'], 'clear')
        self.assertNotIn('issue list', calls)

    def test_label_read_failure_stops_the_step(self):
        result, outputs, calls = self.run_freeze(fail_read='labels')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('status', outputs)
        self.assertIn('Could not read labels', result.stderr)
        self.assertNotIn('issue list', calls)

    def test_issue_read_failure_stops_the_step_even_with_partial_output(self):
        result, outputs, _ = self.run_freeze(
            issues='#123 Release freeze', fail_read='issues',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('status', outputs)
        self.assertIn('Could not read issues', result.stderr)


if __name__ == '__main__':
    unittest.main()
