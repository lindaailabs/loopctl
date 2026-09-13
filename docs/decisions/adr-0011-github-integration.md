# ADR-0011: GitHub pull-request integration

- Status: accepted
- Date: 2026-09-13

## Context

loopctl's requirement → MR loop targeted GitLab only (`GitLabClient`,
`GITLAB_TOKEN`, `gitlab_project_id`). Several real projects (e.g. `liganex`) are
hosted on GitHub, so a real closed loop is impossible for them: the
`creating_mr` step hard-fails validation without a GitLab project id/token.

We need the same headless, unattended PR capability against GitHub without
forking the workflow or breaking the existing GitLab path.

## Decision

Add a **second, parallel integration** (`src/loopctl/integrations/github.py`)
that mirrors `gitlab.py` 1:1:

- `GitHubClient` protocol: `push_branch` + `open_mr(repo, ...)`.
- `HttpGitHubClient`: `git push` + `POST /repos/{repo}/pulls`
  (Bearer `GITHUB_TOKEN`, env `GITHUB_API_URL` override), with the same
  exponential-backoff / `api_error` retry contract as GitLab.
- `DryRunGitHubClient`: no-op paired with the `fake` engine.
- `GitHubError(kind)` mirroring `GitLabError`.
- `MRInfo` (url + iid) is **shared** with GitLab — the workflow only reads
  `mr.url`, so both return the same type.

The host is selected per project via a new `provider` field on
`ProjectConfig` (`"gitlab"` default, `"github"`). `Workflow` holds both a
`gitlab` and a `github` client; `creating_mr` branches on `provider`. A new
`github_repo` (owner/repo) field plus provider-aware `runtime_issues` checks
(`GITHUB_TOKEN` / `github_repo` when `provider=github`) keep the fail-fast
contract. `loopctl init` gains `--provider` and `--github-repo`.

## Alternatives considered

- **Unify GitLab + GitHub behind one `MergeClient` protocol** (rename
  `open_mr(project_id: int)` → `open_mr(repo: str)`). Cleaner long-term, but
  it changes the already-tested GitLab contract and is a broader, riskier
  refactor than the task requires. Deferred — the parallel design is
  conservative and keeps GitLab behavior byte-identical.
- **Require projects to mirror to GitLab.** Rejected: adds operational burden
  and contradicts the goal of driving the existing GitHub repo directly.

## Consequences

- GitHub-hosted projects can now run the full loop and open a PR via
  `provider=github` + `GITHUB_TOKEN`.
- GitLab behavior is unchanged (default provider, identical tests still pass).
- Two near-duplicate push implementations exist (one per host); acceptable for
  now and easy to extract later if a third host appears.

## Example

The integration is exercised end to end against a real GitHub-hosted project.
The screenshot below shows a pull request that loopctl's autonomous pipeline
generated and pushed for the `liganex` project
(`liganex/pull/1`):

![loopctl-generated GitHub PR (liganex/pull/1)](../assets/screenshots/loopctl-pr-ai-video-canvas.png)
