---
name: OpenAPI PR Reviewer
description: >
  Daily automation that reviews the latest "Update OpenAPI 3.0/3.1 Descriptions" PRs
  opened by github-openapi-bot, checks for breaking changes, and — when none are found —
  merges the latest pair and closes the older superseded PRs. Posts a Slack notification
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
    post-to-slack-channel:
      description: >
        Post a message to the #api-platform Slack channel. Message must be 200 characters or
        less. Supports Slack markdown (*bold*, _italic_, `code`, <url|text>). Requires the
        SLACK_BOT_TOKEN secret and GH_AW_SLACK_CHANNEL_ID (set below) to be configured.
      runs-on: ubuntu-latest
      output: "Message posted to Slack."
      permissions:
        contents: read
      inputs:
        message:
          description: "The message to post (max 200 characters, Slack markdown)."
          required: true
          type: string
      env:
        SLACK_BOT_TOKEN: "${{ secrets.SLACK_BOT_TOKEN }}"
        SLACK_CHANNEL_ID: "${{ env.GH_AW_SLACK_CHANNEL_ID }}"
      steps:
        - name: Post message to Slack
          uses: actions/github-script@v9
          with:
            script: |
              const fs = require('fs');
              const token = process.env.SLACK_BOT_TOKEN;
              const channel = process.env.SLACK_CHANNEL_ID;
              const staged = process.env.GH_AW_SAFE_OUTPUTS_STAGED === 'true';
              const outFile = process.env.GH_AW_AGENT_OUTPUT;
              if (!outFile || !fs.existsSync(outFile)) { core.info('No agent output.'); return; }
              const data = JSON.parse(fs.readFileSync(outFile, 'utf8'));
              const items = (data.items || []).filter(i => i.type === 'post_to_slack_channel');
              for (const item of items) {
                const message = item.message || '';
                if (!message) { core.warning('Empty message, skipping'); continue; }
                if (message.length > 200) { core.warning(`Message too long (${message.length}), skipping`); continue; }
                if (staged) {
                  await core.summary.addRaw(`## 🎭 Staged: would post to Slack (${channel})\n\n${message}\n`).write();
                  continue;
                }
                if (!token) { core.setFailed('SLACK_BOT_TOKEN not configured'); return; }
                if (!channel) { core.setFailed('GH_AW_SLACK_CHANNEL_ID not configured'); return; }
                const res = await fetch('https://slack.com/api/chat.postMessage', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json; charset=utf-8', 'Authorization': `Bearer ${token}` },
                  body: JSON.stringify({ channel, text: message }),
                });
                const body = await res.json();
                if (!body.ok) { core.setFailed(`Slack API error: ${body.error}`); return; }
                core.info(`✅ Posted to Slack (ts=${body.ts})`);
              }

    # ---- Merge + close + notify ------------------------------------------------------
    # The agent calls this ONCE when there are NO breaking changes. It performs the
    # privileged local-git merge (the merge API times out on these diffs), closes the
    # older superseded PRs, and posts the merged-PR list to Slack — all in one gated job
    # so the "merged" notification only fires on real success.
    merge-openapi-prs:
      description: >
        Merge the latest OpenAPI 3.0 and 3.1 description PRs into the default branch, close
        the older superseded PRs, and notify Slack. Call this ONLY when no breaking changes
        were found. Provide the two latest PR numbers and the list of older PR numbers.
      runs-on: ubuntu-latest
      output: "OpenAPI PRs merged, older PRs closed, Slack notified."
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
          description: "One-line summary of the merged changes for the Slack notification."
          required: true
          type: string
      env:
        # Dedicated PAT (or GitHub App token) that can push to the protected default branch.
        # The default GITHUB_TOKEN cannot bypass required status checks; see PR description.
        MERGE_TOKEN: "${{ secrets.OPENAPI_MERGE_TOKEN }}"
        SLACK_BOT_TOKEN: "${{ secrets.SLACK_BOT_TOKEN }}"
        SLACK_CHANNEL_ID: "${{ env.GH_AW_SLACK_CHANNEL_ID }}"
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
        - name: Checkout default branch
          uses: actions/checkout@v5
          with:
            fetch-depth: 0
            token: ${{ env.MERGE_TOKEN }}
        - name: Merge PRs locally and push
          if: ${{ env.GH_AW_SAFE_OUTPUTS_STAGED != 'true' }}
          env:
            PR_30: ${{ steps.req.outputs.pr_30 }}
            PR_31: ${{ steps.req.outputs.pr_31 }}
          run: |
            set -euo pipefail
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            DEFAULT_BRANCH="${GITHUB_REF_NAME}"
            git checkout "$DEFAULT_BRANCH"
            # Fetch the two PR heads (bot branches live in this repo, so pull/N/head works).
            git fetch origin "pull/${PR_30}/head:pr-${PR_30}"
            git fetch origin "pull/${PR_31}/head:pr-${PR_31}"
            # Merge 3.0 first, then 3.1, to avoid conflicts (they touch disjoint paths).
            git merge --no-ff "pr-${PR_30}" -m "Merge OpenAPI 3.0 descriptions (#${PR_30})"
            git merge --no-ff "pr-${PR_31}" -m "Merge OpenAPI 3.1 descriptions (#${PR_31})"
            git push origin "$DEFAULT_BRANCH"
        - name: Preview merge (staged)
          if: ${{ env.GH_AW_SAFE_OUTPUTS_STAGED == 'true' }}
          env:
            PR_30: ${{ steps.req.outputs.pr_30 }}
            PR_31: ${{ steps.req.outputs.pr_31 }}
            OLDER: ${{ steps.req.outputs.older_prs }}
          run: |
            echo "🎭 Staged: would merge #${PR_30} + #${PR_31} into ${GITHUB_REF_NAME}, then close: ${OLDER:-none}"
        - name: Close older superseded PRs
          if: ${{ env.GH_AW_SAFE_OUTPUTS_STAGED != 'true' && steps.req.outputs.older_prs != '' }}
          env:
            GH_TOKEN: ${{ env.MERGE_TOKEN }}
            PR_30: ${{ steps.req.outputs.pr_30 }}
            PR_31: ${{ steps.req.outputs.pr_31 }}
            OLDER: ${{ steps.req.outputs.older_prs }}
          run: |
            set -euo pipefail
            IFS=',' read -ra NUMS <<< "$OLDER"
            for n in "${NUMS[@]}"; do
              n=$(echo "$n" | tr -d ' ')
              [ -z "$n" ] && continue
              gh pr close "$n" --repo "$GITHUB_REPOSITORY" \
                --comment "Superseded by the newer OpenAPI description PRs #${PR_30} and #${PR_31}, which have been merged. Closing this older PR." || \
                echo "warning: failed to close #$n"
            done
        - name: Notify Slack of merge
          if: ${{ env.GH_AW_SAFE_OUTPUTS_STAGED != 'true' }}
          uses: actions/github-script@v9
          env:
            PR_30: ${{ steps.req.outputs.pr_30 }}
            PR_31: ${{ steps.req.outputs.pr_31 }}
            SUMMARY: ${{ steps.req.outputs.summary }}
          with:
            script: |
              const token = process.env.SLACK_BOT_TOKEN;
              const channel = process.env.SLACK_CHANNEL_ID;
              if (!token || !channel) { core.warning('Slack not configured; skipping notify'); return; }
              const text = `✅ Merged OpenAPI description PRs #${process.env.PR_30} & #${process.env.PR_31} in <https://github.com/${process.env.GITHUB_REPOSITORY}|rest-api-description>. ${process.env.SUMMARY || ''}`.slice(0, 200);
              const res = await fetch('https://slack.com/api/chat.postMessage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json; charset=utf-8', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ channel, text }),
              });
              const body = await res.json();
              if (!body.ok) core.warning(`Slack notify failed: ${body.error}`);

# The #api-platform Slack channel ID. Update this to the real channel ID before enabling.
env:
  GH_AW_SLACK_CHANNEL_ID: "${{ vars.API_PLATFORM_SLACK_CHANNEL_ID }}"
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

Do **not** merge. Call `post-to-slack-channel` with a concise alert (≤200 chars), e.g.:

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
2. **Never call both** `merge-openapi-prs` and a breaking-change `post-to-slack-channel` in
   the same run — it's one or the other.
3. **Merge the latest pair only.** Older PRs are closed as superseded, never merged (they're
   stale snapshots of the same evolving descriptions).
4. Keep git operations read-only in your own analysis — the actual merge/push is performed by
   the privileged `merge-openapi-prs` job, not by you.
5. Stay within the turn budget: analyze one representative file per platform; don't parse the
   entire dereferenced JSON unless a specific schema detail is in question.
