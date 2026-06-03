# Release Checklist

## Automated Pipeline

Tagged pushes (`v*.*.*`) trigger the release workflow (`.github/workflows/release.yml`):

1. **build-push** — builds and pushes the container image to `ghcr.io`
2. **pypi-publish** — builds sdist + wheel and uploads to PyPI via OIDC Trusted Publishing
3. **github-release** — creates a GitHub Release with changelog notes

## Pre-release

- [ ] All CI checks pass on `main` (lint, typecheck, security, test)
- [ ] `CHANGELOG.md` has a section for the release version with the date filled in
- [ ] Version in `pyproject.toml` matches the tag you are about to create
- [ ] README and community files (`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`) are up to date

## Tag and Push

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow handles everything else automatically.

## Post-release

- [ ] Verify the [GitHub Release](https://github.com/JimAKennedy/nfr-review/releases) was created
- [ ] Verify the package is on [PyPI](https://pypi.org/project/nfr-review/)
- [ ] Run `pip install nfr-review==<version>` in a clean venv to confirm
- [ ] Announce the release in relevant channels

## PyPI Trusted Publishing Setup

PyPI Trusted Publishing uses OpenID Connect (OIDC) so the release workflow can publish
without long-lived API tokens. This is a **one-time manual setup** on pypi.org.

### First-time setup (before the first release)

1. Go to <https://pypi.org/manage/account/publishing/>
2. Under **Add a new pending publisher**, fill in:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `nfr-review` |
   | Owner | `JimAKennedy` |
   | Repository name | `nfr-review` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. Click **Add**

After the first successful publish, the project will appear under your PyPI account and
the pending publisher converts to an active trusted publisher.

### How it works

- The release workflow's `pypi-publish` job runs in the `pypi` GitHub environment
- GitHub Actions mints a short-lived OIDC token scoped to the workflow run
- `pypa/gh-action-pypi-publish` exchanges the OIDC token with PyPI for upload credentials
- No API tokens or secrets need to be stored in the repository

### Existing project (already on PyPI)

If the project already exists on PyPI, go to the project's Publishing settings
(`https://pypi.org/manage/project/nfr-review/settings/publishing/`) and add the
trusted publisher there instead of using the pending publisher flow.
