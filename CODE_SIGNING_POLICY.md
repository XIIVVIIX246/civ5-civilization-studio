# Code signing policy

## Policy

Public binaries must originate from this public repository and an identified
commit. Release builds run on GitHub-hosted Windows runners, execute the test
and public-package gates, and publish hashes generated after any signature is
applied. Signing keys are never stored in this repository or on a maintainer's
development machine.

Unsigned builds must contain `SIGNING_STATUS.txt` with
`UNSIGNED_PUBLIC_CANDIDATE` and must not be described as trusted releases.
Signed builds must pass Authenticode verification and retain signer and
timestamp evidence.

## SignPath statement

The project intends to apply for free code signing provided by SignPath.io,
certificate by SignPath Foundation. Until that application is approved and
the workflow is connected, published candidates remain explicitly unsigned.

## Roles

- Committer and reviewer: [XIIVVIIX246](https://github.com/XIIVVIIX246)
- Release and signing approver: [XIIVVIIX246](https://github.com/XIIVVIIX246)

Contributions from people without direct write access require review before
merge. Signing requests require explicit approval after all protected-branch
checks pass.

## Privacy

The program does not transfer information to other networked systems unless
the user explicitly requests an external action, such as opening a Steam page
or publishing their own files. It has no telemetry, advertisements, accounts,
or automatic upload service. See `docs/PUBLIC_RELEASE.md`.

## Release evidence

Each release records its source commit, application version, SHA-256 digest,
test result, signature status, and the boundary between static validation and
actual Civilization V runtime testing.
