# sample-repo

Tracked fixture used by `tests/test_e2e.py`. The end-to-end test copies this
directory to a temporary path, runs `git init` + commit there, and invokes
`nfr-review run` against the copy. Do NOT add a `.git` directory here — the
test creates one in the temp copy so auditability has real provenance to
read.
