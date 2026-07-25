# Session transfer: jk-standards bundle

Temporary artifact — delete this branch once consumed.

`jk-standards.bundle` is a complete git bundle of the new
`JimAKennedy/jk-standards` repository's `main` branch (commits: initial
scaffold; doc anti-drift toolkit + hooks + workflows + skills + poly
migration notes; deps-only doc-drift parity fix). It was built in a session
that had no push access to the newly created jk-standards remote.

To consume:

    git clone jk-standards.bundle jk-standards
    cd jk-standards
    git remote set-url origin https://github.com/JimAKennedy/jk-standards.git
    pip install -e ".[dev]" && python -m pytest tests/ && jk-standards all
    git push -u origin main
    git tag v0.1.0 && git push origin v0.1.0
