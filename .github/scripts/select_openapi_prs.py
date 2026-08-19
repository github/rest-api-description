#!/usr/bin/env python3
"""Select the OpenAPI description update PRs to merge, and the superseded ones.

Reads the JSON array produced by

    gh pr list --state open --author <bot> \
        --json number,title,headRefOid,createdAt

on stdin and writes `key=value` lines suitable for `$GITHUB_OUTPUT`.

Two properties matter for safety and are the reason this is a script rather
than an inline `jq` filter:

* Only pull requests whose title is *exactly* one of the two recognised
  description-update titles are considered. Any other pull request by the
  same author is neither merged nor closed.
* A title only contributes superseded pull requests when its own newest
  pull request was selected, so nothing is closed unless a validated
  replacement for that exact title is being merged.
* Superseded numbers are emitted per title rather than in one list, so the
  workflow can confirm a pull request still carries the title it was
  selected under before closing it.
* The head commit SHA of each selected pull request is emitted alongside its
  number, so every later step can pin to the exact commit that was inspected
  instead of resolving a branch name again.
"""

import argparse
import json
import sys

TITLE_30 = 'Update OpenAPI 3.0 Descriptions'
TITLE_31 = 'Update OpenAPI 3.1 Descriptions'
TITLES = (TITLE_30, TITLE_31)
# Output suffix -> exact title. The workflow reads a title through `--title`
# so the two files never drift apart.
GROUPS = (('30', TITLE_30), ('31', TITLE_31))


def _sort_key(pr):
    # `createdAt` is RFC 3339 in UTC, so lexical order is chronological.
    # The number breaks ties deterministically.
    return (pr.get('createdAt') or '', pr.get('number') or 0)


def select(pull_requests):
    """Return the pinnable newest PR per recognised title, and the superseded.

    A title only contributes superseded pull requests when its own newest
    pull request was actually selected. Nothing is ever closed on the basis
    of a replacement that was not validated. The superseded numbers are keyed
    by title so the caller can re-check that association before closing.
    """
    recognised = [
        pr
        for pr in pull_requests
        if isinstance(pr, dict) and pr.get('title') in TITLES and pr.get('number')
    ]

    selected = {}
    superseded = {title: [] for title in TITLES}
    for title in TITLES:
        candidates = [pr for pr in recognised if pr['title'] == title]
        if not candidates:
            continue
        newest = max(candidates, key=_sort_key)
        # Without a head SHA the newest pull request cannot be pinned to an
        # exact commit, so it is not merged from a mutable branch instead --
        # and none of its older siblings are closed.
        if not newest.get('headRefOid'):
            continue
        selected[title] = newest
        superseded[title] = sorted(
            pr['number'] for pr in candidates if pr['number'] != newest['number']
        )

    return selected, superseded


def outputs(pull_requests):
    selected, superseded = select(pull_requests)

    lines = [f'found={"true" if selected else "false"}']
    for suffix, title in GROUPS:
        pr = selected.get(title)
        lines.append(f'pr_{suffix}={pr["number"] if pr else ""}')
        lines.append(f'sha_{suffix}={pr["headRefOid"] if pr else ""}')
        lines.append(
            f'superseded_{suffix}=' + ' '.join(str(n) for n in superseded[title])
        )

    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--title',
        choices=[suffix for suffix, _ in GROUPS],
        help='print the exact recognised title for one output group and exit',
    )
    args = parser.parse_args(argv)

    if args.title:
        print(dict(GROUPS)[args.title])
        return 0

    payload = json.load(sys.stdin)
    if not isinstance(payload, list):
        print('expected a JSON array of pull requests', file=sys.stderr)
        return 2

    for line in outputs(payload):
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
