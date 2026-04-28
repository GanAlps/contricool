# Runbook — prod rollback

## When to run this

Prod is broken. `/v1/health` is failing, or alarms are firing, or you have telemetry showing a recent merge introduced a regression. You need to get prod back to a known-good state quickly.

## Decision tree

1. **Is prod returning 5xx broadly?** → roll back.
2. **Is prod working but a single feature is broken?** → consider a forward-fix PR through the normal pipeline (faster than rollback if the fix is small and obvious).
3. **Is the issue cosmetic / non-customer-facing?** → forward-fix; do not roll back.
4. **Did the most recent prod deploy fail before the smoke step?** → CFN already rolled the stack back; nothing to do here. Investigate the failed run; fix forward.

Rollback frequency goal: **<1/quarter**. If we're rolling back more, the gating between dev and prod isn't catching enough.

## Prerequisites

- You are the repo admin (or the prod environment's required reviewer).
- You can identify the **last known-good `release/...` tag**. List with:

  ```bash
  git fetch --tags
  git tag --list 'release/*' --sort=-creatordate | head -10
  ```

  Tags are pushed by `deploy.yml` after every successful prod deploy. The most recent tag *before* the bad merge is your rollback target.

- The prod GitHub Environment's required-reviewer rule is on (Phase 0); rollback execution requires your approval just like a normal prod deploy. **You can approve your own rollback** — that's intentional, since you triggered it.

## Steps

1. **Identify the rollback target.**

   ```bash
   git fetch --tags
   git tag --list 'release/*' --sort=-creatordate | head -10
   ```

   Pick the tag *before* the suspected-bad release. Example: if `release/2026-04-28-bad1234` is the broken one, target `release/2026-04-28-038ed11`.

2. **Trigger `rollback.yml` on GitHub.**

   - Go to *Actions → Rollback (prod) → Run workflow*.
   - Branch: `main` (the workflow checks out the tag itself; this is just where the workflow file lives).
   - `tag`: paste the rollback target, e.g. `release/2026-04-28-038ed11`.
   - Click *Run workflow*.

3. **Approve the prod environment gate.**

   GitHub will pause at the deploy step and require your approval. Click *Review pending deployments → prod → Approve and deploy*.

4. **Watch the workflow.**

   The deploy step takes ~3-5 minutes. The smoke step retries `/v1/health` for up to ~100 seconds, accounting for CloudFront propagation.

5. **Verify in CloudWatch + browser.**

   - Open prod CloudFront URL in a browser; load the placeholder page; hit `/v1/health`. Body's `version` should reflect the rollback target.
   - Check CloudWatch alarms in `Contricool-Prod-Monitoring` — the API 5xx alarm should clear within ~10 minutes.
   - Tail Lambda logs to confirm requests are succeeding:

     ```bash
     aws logs tail /aws/lambda/contricool-api-prod \
       --follow --since 5m --profile contricool-admin
     ```

## Post-rollback actions

1. **File an incident note** in `specs/runbooks/<YYYY-MM-DD>-rollback.md` describing:
   - When the bad release went out (`git show <bad-tag>`).
   - What was the symptom (alarm name, error message, customer report).
   - What we rolled back to.
   - Suspected root cause.

2. **Open an issue** for the forward-fix work. Don't push the fix straight to `main` without going back through the normal dev → prod gate.

3. **Run a post-mortem** if the incident lasted >30 min or affected real users.

## Troubleshooting

| Symptom                                                                   | Likely cause                                                          | Fix                                                                                                                                                                                                                                |
|---|---|---|
| Workflow fails at "Validate tag format"                                    | Tag string typo (e.g. `release/2026-4-28-038ed11` — missing zero pad) | Re-run with the exact tag. `git tag --list 'release/*'` to copy-paste.                                                                                                                                                              |
| Workflow fails at "Verify tag exists and is on main ancestry"             | Tag was deleted, or points to a commit not on main (rebase happened)  | Pick a different known-good tag. If your tags have drifted off main, that's a problem worth investigating separately.                                                                                                              |
| `cdk deploy` fails with "Stack ... is in UPDATE_ROLLBACK_FAILED state"     | Previous deploy died mid-update; CFN couldn't roll back automatically | Open CFN console → `Contricool-Prod-Api` → *Stack actions → Continue update rollback*. Then re-run rollback.yml.                                                                                                                    |
| Smoke step fails after deploy succeeds                                    | CloudFront cache, or actual broken-rollback                           | Wait 5 min and re-curl manually. If still broken, check Lambda logs. Worst case: the rollback target itself is broken — pick an even older tag.                                                                                  |
| Workflow sits indefinitely on "Waiting for review"                        | The required reviewer isn't responding                                | Page the reviewer. If you ARE the reviewer, you're missing the GitHub notification — go to *Actions* directly.                                                                                                                      |
| `/v1/health` shows the *new* version, not the rolled-back one             | Browser/CDN cached                                                    | Add `?nocache=$(date +%s)` to the URL, or hit it from `curl` (no cache).                                                                                                                                                            |
| Need to roll back FAST, the workflow is too slow                          | Acceptable trade-off                                                  | The fast path (direct `aws lambda update-alias`) requires `lambda:UpdateAlias` on the prod role, which we deferred. If rollback latency becomes a regular problem, file an issue to widen the role and add a fast-rollback flag. |

## Why we don't fast-rollback today

Direct `aws lambda update-alias --function-name contricool-api-prod --name live --function-version <N>` would take ~5 seconds vs the ~5 minute CDK redeploy. We chose CDK redeploy at MVP because:

1. The prod deploy role doesn't currently have `lambda:UpdateAlias` on the prod Lambda — adding it widens the role's blast radius and requires re-deploying `Contricool-Shared`.
2. CDK redeploy is *idempotent and atomic*: the source-of-truth is the checked-out commit, and CDK keeps published versions and the alias in sync. A direct alias update is a sideband mutation that drifts CFN's view of reality from AWS's view.
3. Rollback is rare. 5 minutes is fine.

If rollback ever becomes routine, revisit this trade-off.

## Owner

This runbook is the operator's guide. Owner = repo admin (currently @GanAlps). Update this file every time the rollback flow changes.
