---
name: OpenAPI PR Reviewer
description: >
  Daily automation that reviews the latest "Update OpenAPI 3.0/3.1 Descriptions" PRs
  opened by github-openapi-bot, checks for breaking changes, and — when none are found —
  merges the latest pair and closes the older superseded PRs. Posts a chatterbox notification
  to #api-platform on merge, and alerts #api-platform when a breaking change is detected.

# Runs every day at 15:00 UTC (~10:00 ET), after the bot's overnight description sync.
# Also runnable on demand via the Actions "Run workflow" button.
on:
  schedule:
    - cron: "0 15 * * *"
  workflow_dispatch:

# The agent itself is READ-ONLY. All privileged writes (merge/push/close/Slack) happen in
# the custom safe-output jobs below, which hold the write tokens. This is gh-aw's defense
# against prompt injection: nothing the model "decides" can write without passing through
# a gated job.
permissions:
  contents: read
  pull-requests: read

engine: copilot

# Cost guardrail: a normal review needs ~10-20 turns (diff analysis on a handful of files).
# This cap only stops runaway loops (e.g. re-reading a 250K-line diff repeatedly).
max-turns: 30

concurrency:
  group: openapi-pr-reviewer

tools:
  github:
    toolsets: [context, repos, pull_requests]
  # The agent needs local git to analyze the large diffs — the GitHub diff API returns
  # HTTP 422 / changed_files:0 on these ~64-file, 250K-line PRs.
  bash:
    - "git *"
    - "grep *"
    - "sort *"
    - "comm *"
    - "head *"
    - "tail *"
    - "wc *"

# SAFETY: ship in staged (dry-run) mode. Safe-output jobs will PREVIEW their actions in the
# run summary instead of merging/pushing/posting. Flip to `false` (or remove) only after the
# required secrets and branch-protection bypass are provisioned (see the PR description / #3408).
safe-outputs:
  staged: true
  jobs:
    # ---- Breaking-change alert -------------------------------------------------------
    # The agent calls this when it detects a breaking change and therefore does NOT merge.
    post-to-chatterbox:
      description: >
        Post a message to the #api-platform Slack channel via chatterbox. Message must be 200
        characters or less. Supports Slack markdown (*bold*, _italic_, `code`, <url|text>).
        Requires the CHATTERBOX_URL and CHATTERBOX_TOKEN secrets to be configured.
      runs-on: ubuntu-latest
      output: "Message posted to chatterbox."
      permissions:
        contents: read
      inputs:
        message:
          description: "The message to post (max 200 characters, Slack markdown)."
          required: true
          type: string
      env:
        # gh-aw does NOT auto-inject GH_AW_SAFE_OUTPUTS_STAGED into custom safe-output jobs
        # (only into its own built-in jobs), so we set it explicitly here from the
        # `safe-outputs.staged` value. To go live, set this to "false" (or remove it) in BOTH
        # custom jobs AND set `safe-outputs.staged: false`, then recompile.
        GH_AW_SAFE_OUTPUTS_STAGED: "true"
        CHATTERBOX_URL: "${{ secrets.CHATTERBOX_URL }}"
        CHATTERBOX_TOKEN: "${{ secrets.CHATTERBOX_TOKEN }}"
      steps:
        - name: Post message to chatterbox
          uses: actions/github-script@v9
          with:
            script: |
              const fs = require('fs');
              const url = process.env.CHATTERBOX_URL;
              const token = process.env.CHATTERBOX_TOKEN;
              const staged = process.env.GH_AW_SAFE_OUTPUTS_STAGED === 'true';
              const outFile = process.env.GH_AW_AGENT_OUTPUT;
              if (!outFile || !fs.existsSync(outFile)) { core.info('No agent output.'); return; }
              const data = JSON.parse(fs.readFileSync(outFile, 'utf8'));
              const items = (data.items || []).filter(i => i.type === 'post_to_chatterbox');
              for (const item of items) {
                const message = item.message || '';
                if (!message) { core.warning('Empty message, skipping'); continue; }
                if (message.length > 200) { core.warning(`Message too long (${message.length}), skipping`); continue; }
                if (staged) {
                  await core.summary.addRaw(`## Staged: would post to chatterbox #api-platform\n\n${message}\n`).write();
                  continue;
                }
                if (!url || !token) { core.setFailed('CHATTERBOX_URL or CHATTERBOX_TOKEN not configured'); return; }
                const endpoint = `${url.replace(/\/$/, '')}/topics/%23api-platform`;
                const auth = Buffer.from(`${token}:`).toString('base64');
                const res = await fetch(endpoint, {
                  method: 'POST',
                  headers: { 'Authorization': `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
                  body: message,
                });
                if (!res.ok) { core.setFailed(`chatterbox error: ${res.status} ${await res.text()}`); return; }
                core.info(`Posted to chatterbox #api-platform (status ${res.status})`);
              }

    # ---- Merge + close + notify ------------------------------------------------------
    # The agent calls this ONCE when there are NO breaking changes. It merges the two latest
    # PRs via the GitHub merge API (merging a PR satisfies the "require a pull request" branch
    # rule, so no protected-branch push/bypass is needed), closes the older superseded PRs,
    # and posts the merged-PR list to chatterbox — all in one gated job so the "merged"
    # notification only fires on real success.
    merge-openapi-prs:
      description: >
        Merge the latest OpenAPI 3.0 and 3.1 description PRs into the default branch, close
        the older superseded PRs, and notify chatterbox. Call this ONLY when no breaking changes
        were found. Provide the two latest PR numbers and the list of older PR numbers.
      runs-on: ubuntu-latest
      output: "OpenAPI PRs merged, older PRs closed, chatterbox notified."
      permissions:
        contents: write
        pull-requests: write
      inputs:
        pr_30:
          description: "PR number of the latest 'Update OpenAPI 3.0 Descriptions' PR."
          required: true
          type: number
        pr_31:
          description: "PR number of the latest 'Update OpenAPI 3.1 Descriptions' PR."
          required: true
          type: number
        older_prs:
          description: "Comma-separated PR numbers of older superseded PRs to close (may be empty)."
          required: false
          type: string
        summary:
          description: "One-line summary of the merged changes for the chatterbox notification."
          required: true
          type: string
      env:
        # See note on the post-to-chatterbox job: gh-aw doesn't inject this into custom
        # safe-output jobs, so we set it explicitly. Flip to "false" here + in
        # `safe-outputs.staged` to go live, then recompile.
        GH_AW_SAFE_OUTPUTS_STAGED: "true"
        CHATTERBOX_URL: "${{ secrets.CHATTERBOX_URL }}"
        CHATTERBOX_TOKEN: "${{ secrets.CHATTERBOX_TOKEN }}"
      steps:
        - name: Read agent request
          id: req
          uses: actions/github-script@v9
          with:
            script: |
              const fs = require('fs');
              const outFile = process.env.GH_AW_AGENT_OUTPUT;
              const data = JSON.parse(fs.readFileSync(outFile, 'utf8'));
              const item = (data.items || []).find(i => i.type === 'merge_openapi_prs');
              if (!item) { core.setFailed('No merge_openapi_prs item in agent output'); return; }
              core.setOutput('pr_30', String(item.pr_30));
              core.setOutput('pr_31', String(item.pr_31));
              core.setOutput('older_prs', item.older_prs || '');
              core.setOutput('summary', item.summary || '');
        - name: Merge the two latest PRs via the merge API
          env:
            # Use the secret directly: gh-aw injects the job `env:` at step level, and a
            # step-level env value can't reference another same-step env var via `env.`.
            GH_TOKEN: ${{ secrets.OPENAPI_MERGE_TOKEN }}
            PR_30: ${{ steps.req.outputs.pr_30 }}
            PR_31: ${{ steps.req.outputs.pr_31 }}
            DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
          run: |
            set -euo pipefail
            # Staged/dry-run guard. We check the shell env var (injected by gh-aw) rather than a
            # step `if:` because gh-aw sets GH_AW_SAFE_OUTPUTS_STAGED at step level, and a step's
            # own step-level env is NOT visible to that same step's `if:` conditional.
            if [ "${GH_AW_SAFE_OUTPUTS_STAGED:-}" = "true" ]; then
              echo "🎭 Staged: would merge #${PR_30} + #${PR_31} into ${DEFAULT_BRANCH}."
              exit 0
            fi
            # Merge each PR through the GitHub merge API (a merge commit, like the old --no-ff).
            # These diffs are huge (~64 files / 250K lines), so the synchronous merge call can
            # gateway-timeout (502/504) even though the merge completes server-side. Retry, and
            # after each failure poll the PR's merged state before giving up.
            merge_pr() {
              local n="$1" label="$2"
              echo "Merging #$n ($label)..."
              for attempt in 1 2 3 4 5; do
                if [ "$(gh pr view "$n" --repo "$GITHUB_REPOSITORY" --json merged -q .merged)" = "true" ]; then
                  echo "#$n already merged."; return 0
                fi
                if gh pr merge "$n" --repo "$GITHUB_REPOSITORY" --merge; then
                  echo "#$n merged."; return 0
                fi
                echo "Merge attempt $attempt for #$n failed (likely a gateway timeout on a large diff); waiting to see if it completed server-side..."
                sleep 30
                if [ "$(gh pr view "$n" --repo "$GITHUB_REPOSITORY" --json merged -q .merged)" = "true" ]; then
                  echo "#$n merged (completed server-side after timeout)."; return 0
                fi
              done
              echo "ERROR: failed to merge #$n after retries." >&2; return 1
            }
            # Merge 3.0 first, then 3.1 (they touch disjoint paths, so no conflicts).
            merge_pr "$PR_30" "OpenAPI 3.0"
            merge_pr "$PR_31" "OpenAPI 3.1"
        - name: Close older superseded PRs
          if: ${{ success() && steps.req.outputs.older_prs != '' }}
          env:
            GH_TOKEN: ${{ secrets.OPENAPI_MERGE_TOKEN }}
            PR_30: ${{ steps.req.outputs.pr_30 }}
            PR_31: ${{ steps.req.outputs.pr_31 }}
            OLDER: ${{ steps.req.outputs.older_prs }}
          run: |
            set -euo pipefail
            if [ "${GH_AW_SAFE_OUTPUTS_STAGED:-}" = "true" ]; then
              echo "🎭 Staged: would close superseded PRs: ${OLDER:-none}"
              exit 0
            fi
            IFS=',' read -ra NUMS <<< "$OLDER"
            for n in "${NUMS[@]}"; do
              n=$(echo "$n" | tr -d ' ')
              [ -z "$n" ] && continue
              gh pr close "$n" --repo "$GITHUB_REPOSITORY" \
                --comment "Superseded by the newer OpenAPI description PRs #${PR_30} and #${PR_31}, which have been merged. Closing this older PR." || \
                echo "warning: failed to close #$n"
            done
        - name: Notify chatterbox of merge
          uses: actions/github-script@v9
          env:
            PR_30: ${{ steps.req.outputs.pr_30 }}
            PR_31: ${{ steps.req.outputs.pr_31 }}
            SUMMARY: ${{ steps.req.outputs.summary }}
          with:
            script: |
              const text = `Merged OpenAPI description PRs #${process.env.PR_30} & #${process.env.PR_31} in <https://github.com/${process.env.GITHUB_REPOSITORY}|rest-api-description>. ${process.env.SUMMARY || ''}`.slice(0, 200);
              if (process.env.GH_AW_SAFE_OUTPUTS_STAGED === 'true') {
                await core.summary.addRaw(`## 🎭 Staged: would post to chatterbox #api-platform\n\n${text}\n`).write();
                return;
              }
              const url = process.env.CHATTERBOX_URL;
              const token = process.env.CHATTERBOX_TOKEN;
              if (!url || !token) { core.warning('chatterbox not configured; skipping notify'); return; }
              const endpoint = `${url.replace(/\/$/, '')}/topics/%23api-platform`;
              const auth = Buffer.from(`${token}:`).toString('base64');
              const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Authorization': `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
                body: text,
              });
              if (!res.ok) core.warning(`chatterbox notify failed: ${res.status} ${await res.text()}`);

---

# OpenAPI PR Reviewer

You are an automated reviewer for the `github/rest-api-description` repository. Every day you
review the latest OpenAPI description update PRs opened by `github-openapi-bot`, decide
whether they contain any breaking changes, and either merge them (when safe) or raise a Slack
alert (when a breaking change is found).

## Goal

- **No breaking changes** → merge the latest 3.0 + 3.1 PRs, close the older superseded PRs,
  and notify `#api-platform` with the merged PR numbers.
- **Breaking change found** → do NOT merge; alert `#api-platform` so a human can review.

## Step 1: Find the PRs

List open pull requests in this repository. Identify:

1. The **latest** open PR titled **"Update OpenAPI 3.0 Descriptions"** (highest number).
2. The **latest** open PR titled **"Update OpenAPI 3.1 Descriptions"** (highest number).
3. All **older** open PRs with either of those two titles (every one except the two latest).

If there is no open PR of either title, call `noop` with "No OpenAPI update PRs open — nothing to do" and stop.

## Step 2: Analyze the diffs for breaking changes

The GitHub diff API times out on these PRs (they touch ~64 files / 250K lines), so analyze
locally with git. The repository is already checked out in the workspace.

For each of the two latest PRs:

```bash
git fetch origin pull/<PR_NUMBER>/head:pr-<PR_NUMBER>
git diff --name-only origin/HEAD...pr-<PR_NUMBER>   # scope: which files/platforms changed
```

Focus your semantic analysis on the compact (non-dereferenced) specs — for 3.0 use
`descriptions/api.github.com/api.github.com.yaml`; for 3.1 use the corresponding file under
`descriptions-next/`. The 3.0 and 3.1 PRs always carry the **same logical changes**, so a
thorough read of one platform covers both.

Detect breaking changes using this classification:

| Change | Breaking? | How to detect |
|---|---|---|
| New endpoint / operation added | No | added `"/path"` keys (`grep '^\+  "/'`) |
| **Endpoint / operation removed** | 🔴 YES | removed `"/path"` keys (`grep '^\-  "/'`) |
| New property on a response schema | No | added property lines |
| **Property removed from a response** | 🔴 YES | removed property lines |
| **New required field on a request body** | 🔴 YES | new entries in a request `required:` array |
| **Enum value removed** | 🔴 YES | removed entries in an `enum:` array |
| New schema definition | No | new `components/schemas` entry |
| **Schema definition removed** | 🔴 YES | removed `components/schemas` entry |

To avoid false positives from reordering (webhook schemas reorder a lot), confirm a suspected
removal is real: `comm -23` the sorted stripped `−` lines against the sorted `+` lines, and
verify operation counts with `git show pr-<N>:<file> | grep -c operationId`. A `$ref` that
merely moved is not a breaking change.

## Step 3: Act on the result

### If you found ANY breaking change

Do **not** merge. Call `post-to-chatterbox` with a concise alert (≤200 chars), e.g.:

> ⚠️ Breaking change in rest-api-description PR #<N>: <one-line description>. Needs human review before merge.

Then stop. Do not call `merge-openapi-prs`.

### If there are NO breaking changes

Call `merge-openapi-prs` exactly once with:

- `pr_30`: the latest 3.0 PR number
- `pr_31`: the latest 3.1 PR number
- `older_prs`: a comma-separated list of the older superseded PR numbers to close (empty string if none)
- `summary`: a short (≤120 char) human summary of what changed (e.g. "1 new endpoint, 3 new webhooks; api.github.com + ghec only")

The `merge-openapi-prs` job merges both PRs into the default branch, closes the older PRs,
and posts the merged-PR list to `#api-platform`. You do **not** need to post a separate
success message.

## Important rules

1. **Only ever merge when you are confident there are no breaking changes.** When in doubt,
   treat it as breaking and alert Slack instead of merging.
2. **Never call both** `merge-openapi-prs` and a breaking-change `post-to-chatterbox` in
   the same run — it's one or the other.
3. **Merge the latest pair only.** Older PRs are closed as superseded, never merged (they're
   stale snapshots of the same evolving descriptions).
4. Keep git operations read-only in your own analysis — the actual merge/push is performed by
   the privileged `merge-openapi-prs` job, not by you.
5. Stay within the turn budget: analyze one representative file per platform; don't parse the
   entire dereferenced JSON unless a specific schema detail is in question.
