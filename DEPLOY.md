# Deploy / Host uneXpected v7.3.1

This package can be run as a local CLI. A production service requires a separately authorized host and deployment process.

1. Choose a host and isolation model; run under a dedicated least-privilege OS account/container.
2. Pin Python version, package checksum and source-control revision. Review dependencies (runtime uses Python standard library).
3. Configure secrets through the host secret manager/environment, never in source or chat. Start with the mock provider and no external-action scopes.
4. Configure persistent volume, SQLite backup/restore, disk limits, log retention, process supervision and health checks.
5. If adding connectors, implement a narrow adapter per tool, document scopes, require approval for consequential operations and add permission/abuse tests before enabling it.
6. Run the full test suite, live-provider smoke tests and a restore drill. Verify timeout, cancellation, budget and cost limits under load.
7. Only then mark deployment as verified, with host, version, test evidence, owner, rollback command and monitoring coverage.

No deployment was performed by this build.

## GitHub-backed privileged-action approvals

The runtime can use `GitHubPullRequestApprovalVerifier` as its production approval adapter. It verifies an approval request JSON file committed to the head of an open pull request, and requires a current `APPROVED` review on that exact head commit from a configured trusted GitHub administrator. The pull request must target the configured base branch, originate from this repository (not a fork), remain open, and be authored by an identity other than the trusted approver. The action digest and permission are read from the committed request file, not caller-provided claims. A successful approval is atomically marked as consumed in a local SQLite ledger; a second use is denied. API, parsing, timestamp, permission or ledger failures deny access. The SQLite ledger is local to one runtime instance; run exactly one active instance with a persistent disk. Do not horizontally scale this verifier until its consumption ledger is migrated to a shared transactional database.

Required host variables:

- `UNEXPECTED_GITHUB_APPROVAL_TOKEN`: fine-grained GitHub token stored only in the host secret manager. Grant only this repository and `Metadata: read`, `Contents: read`, `Pull requests: read`.
- `UNEXPECTED_GITHUB_APPROVAL_REPOSITORY`: fixed repository name, for example `soueilouay-creator/uneXpected-`.
- `UNEXPECTED_GITHUB_APPROVAL_TRUSTED_REVIEWERS`: comma-separated GitHub logins; each must currently have `admin` permission.
- `UNEXPECTED_GITHUB_APPROVAL_BASE_BRANCH`: protected base branch (default `main`).
- `UNEXPECTED_GITHUB_APPROVAL_MAX_AGE_SECONDS`: 60–604800 seconds (default 3600).
- `UNEXPECTED_APPROVAL_LEDGER_PATH`: persistent writable path; back it up with the runtime state.

A trusted GitHub administrator can create an approval request using the repository's `Request privileged-action approval` Actions workflow. The workflow creates a bot-authored PR with `approvals/requests/<proposal_id>.json`; the configured admin reviews and approves that PR. The caller passes `ApprovalContext(approval_id=f'github-pr:<number>:<proposal_id>', approver='<reviewer-login>', approved_permissions=frozenset({permission}), action_digest=<canonical-action-digest>)`. The context is only a locator and consistency claim; GitHub API evidence is authoritative.

Do not deploy this verifier until the read-only token exists in the actual host secret manager, the base branch is protected by a ruleset requiring pull requests, CODEOWNERS approval and passing CI, the Actions workflow is enabled, and a live approval/revocation/replay smoke test has passed. No token was configured or stored by this source change.
