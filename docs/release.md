# Release Checklist

## v0.1.0

Follow these steps to cut a release:

### Pre-release

- [ ] All CI checks pass on `main` (lint, typecheck, security, test)
- [ ] `CHANGELOG.md` has a `[0.1.0]` section with the release date filled in
- [ ] Version in `pyproject.toml` matches the tag you are about to create (`version = "0.1.0"`)
- [ ] README and community files (`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`) are up to date

### Tag and push

```bash
git tag v0.1.0
git push origin v0.1.0
```

### Post-release

- [ ] Verify the release appears on the [GitHub Releases page](https://github.com/JimAKennedy/nfr-review/releases)
- [ ] Create a GitHub Release from the tag with notes summarizing the changelog
- [ ] If publishing to PyPI: `python -m build && twine upload dist/*` and verify the package page
- [ ] Announce the release in relevant channels
