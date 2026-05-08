#!/usr/bin/env python3
"""Install third-party skills from skills-lock.json.

Downloads skill directories from their source GitHub repositories and
places them under .agents/skills/. Only installs skills listed in
skills-lock.json that are not already present locally, unless --force
is given.

Usage:
    python scripts/install_skills.py               # install missing skills
    python scripts/install_skills.py --force        # reinstall all skills
    python scripts/install_skills.py --check        # verify installed hashes
    python scripts/install_skills.py --update-lock  # update lock hashes to match installed
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
from collections import defaultdict
from pathlib import Path

LOCK_FILE = "skills-lock.json"
SKILLS_DIR = Path(".agents/skills")
GITHUB_ARCHIVE_URL = "https://github.com/{source}/archive/refs/heads/main.tar.gz"


def load_lock(project_root: Path) -> dict:
    lock_path = project_root / LOCK_FILE
    if not lock_path.exists():
        print(f"Error: {LOCK_FILE} not found in {project_root}", file=sys.stderr)
        sys.exit(1)
    with open(lock_path) as f:
        return json.load(f)


def compute_hash(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def download_archive(source: str) -> tarfile.TarFile:
    url = GITHUB_ARCHIVE_URL.format(source=source)
    print(f"  Downloading {source} archive...")
    try:
        req = urllib.request.Request(url)
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"token {token}")
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            for branch in ("master", "HEAD"):
                fallback = url.replace("/main.tar.gz", f"/{branch}.tar.gz")
                try:
                    req = urllib.request.Request(fallback)
                    if token:
                        req.add_header("Authorization", f"token {token}")
                    with urllib.request.urlopen(req) as resp:
                        data = resp.read()
                    break
                except urllib.error.HTTPError:
                    continue
            else:
                print(
                    f"  Error: could not download {source} (tried main/master/HEAD)",
                    file=sys.stderr,
                )
                raise
        else:
            raise
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")


def extract_skill(
    tar: tarfile.TarFile,
    skill_path_in_repo: str,
    dest: Path,
) -> int:
    """Extract a skill directory from a tarball. Returns file count."""
    prefix = None
    for member in tar.getmembers():
        if prefix is None:
            prefix = member.name.split("/")[0]
        full_prefix = f"{prefix}/{skill_path_in_repo}/"
        if (
            member.name.startswith(full_prefix)
            or member.name == f"{prefix}/{skill_path_in_repo}"
        ):
            rel = member.name[len(f"{prefix}/{skill_path_in_repo}") :].lstrip("/")
            if member.isdir():
                (dest / rel).mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as src:  # type: ignore[union-attr]
                    target.write_bytes(src.read())
    count = sum(1 for _ in dest.rglob("*") if _.is_file()) if dest.exists() else 0
    return count


def install_skills(project_root: Path, *, force: bool = False) -> int:
    lock = load_lock(project_root)
    skills = lock.get("skills", {})
    if not skills:
        print("No skills in lock file.")
        return 0

    by_source: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for name, info in skills.items():
        by_source[info["source"]].append((name, info))

    installed = 0
    skipped = 0
    failed = 0

    for source, skill_list in sorted(by_source.items()):
        to_install = []
        for name, info in skill_list:
            dest = project_root / SKILLS_DIR / name
            skill_md = dest / "SKILL.md"
            if not force and skill_md.exists():
                existing_hash = compute_hash(skill_md)
                if existing_hash == info["computedHash"]:
                    print(f"  {name}: up to date (skipped)")
                    skipped += 1
                    continue
                else:
                    print(f"  {name}: hash mismatch, reinstalling")
            to_install.append((name, info))

        if not to_install:
            continue

        try:
            tar = download_archive(source)
        except Exception as e:
            print(f"  Failed to download {source}: {e}", file=sys.stderr)
            failed += len(to_install)
            continue

        for name, info in to_install:
            dest = project_root / SKILLS_DIR / name
            skill_dir_in_repo = os.path.dirname(info["skillPath"])

            if dest.exists():
                shutil.rmtree(dest)

            dest.mkdir(parents=True, exist_ok=True)
            count = extract_skill(tar, skill_dir_in_repo, dest)

            skill_md = dest / "SKILL.md"
            if not skill_md.exists():
                print(
                    f"  {name}: SKILL.md not found after extraction (FAILED)", file=sys.stderr
                )
                failed += 1
                continue

            actual_hash = compute_hash(skill_md)
            if actual_hash != info["computedHash"]:
                print(
                    f"  {name}: hash verification failed "
                    f"(expected {info['computedHash'][:12]}..., "
                    f"got {actual_hash[:12]}...)",
                    file=sys.stderr,
                )
                print(f"  {name}: installed anyway ({count} files) — source may have updated")
            else:
                print(f"  {name}: installed ({count} files, hash verified)")
            installed += 1

        tar.close()

    print(f"\nDone: {installed} installed, {skipped} up-to-date, {failed} failed")
    return 1 if failed else 0


def check_skills(project_root: Path) -> int:
    lock = load_lock(project_root)
    skills = lock.get("skills", {})
    ok = 0
    mismatch = 0
    missing = 0

    for name, info in sorted(skills.items()):
        skill_md = project_root / SKILLS_DIR / name / "SKILL.md"
        if not skill_md.exists():
            print(f"  {name}: MISSING")
            missing += 1
        else:
            actual = compute_hash(skill_md)
            if actual == info["computedHash"]:
                print(f"  {name}: OK")
                ok += 1
            else:
                expected = info["computedHash"][:12]
                print(
                    f"  {name}: HASH MISMATCH (expected {expected}..., got {actual[:12]}...)"
                )
                mismatch += 1

    print(f"\n{ok} ok, {mismatch} mismatch, {missing} missing")
    if missing or mismatch:
        print("Run 'python scripts/install_skills.py' to fix.")
        return 1
    return 0


def update_lock(project_root: Path) -> int:
    """Update lock file hashes to match currently installed skills."""
    lock = load_lock(project_root)
    skills = lock.get("skills", {})
    updated = 0

    for name, info in sorted(skills.items()):
        skill_md = project_root / SKILLS_DIR / name / "SKILL.md"
        if not skill_md.exists():
            print(f"  {name}: not installed, skipping")
            continue
        actual = compute_hash(skill_md)
        if actual != info["computedHash"]:
            info["computedHash"] = actual
            print(f"  {name}: hash updated")
            updated += 1
        else:
            print(f"  {name}: unchanged")

    if updated:
        lock_path = project_root / LOCK_FILE
        with open(lock_path, "w") as f:
            json.dump(lock, f, indent=2)
            f.write("\n")
        print(f"\nUpdated {updated} hashes in {LOCK_FILE}")
    else:
        print("\nAll hashes already current")
    return 0


def find_project_root() -> Path:
    """Walk up from cwd to find the directory containing skills-lock.json."""
    cwd = Path.cwd()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / LOCK_FILE).exists():
            return candidate
    script_root = Path(__file__).parent.parent
    if (script_root / LOCK_FILE).exists():
        return script_root
    return cwd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install third-party skills from skills-lock.json"
    )
    parser.add_argument(
        "--force", action="store_true", help="Reinstall all skills even if up to date"
    )
    parser.add_argument(
        "--check", action="store_true", help="Verify installed skills match lock file hashes"
    )
    parser.add_argument(
        "--update-lock",
        action="store_true",
        help="Update lock file hashes to match installed skills",
    )
    parser.add_argument(
        "--root", type=Path, default=None, help="Project root (default: auto-detect)"
    )
    args = parser.parse_args()

    project_root = args.root or find_project_root()

    print(f"Skills lock: {project_root / LOCK_FILE}")
    print(f"Skills dir:  {project_root / SKILLS_DIR}\n")

    if args.check:
        sys.exit(check_skills(project_root))
    elif args.update_lock:
        sys.exit(update_lock(project_root))
    else:
        sys.exit(install_skills(project_root, force=args.force))


if __name__ == "__main__":
    main()
