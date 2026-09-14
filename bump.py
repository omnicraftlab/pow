#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Bump the pow-cli version.

Updates packages/pow-cli/pyproject.toml, the workspace root pyproject.toml (kept
in lockstep), uv.lock, and the top CHANGELOG heading if it is [Unreleased].
No commit, no tag, no push. Review the diff and CHANGELOG, then commit, tag and push; publishing
happens when the GitHub release is created (see docs/releasing.md).

    uv run bump.py --bump patch
    uv run bump.py --bump minor --bump rc
    uv run bump.py 0.3.0rc1
    uv run bump.py --bump minor --dry-run
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

PKG_TOML = Path("packages/pow-cli/pyproject.toml")
ROOT_TOML = Path("pyproject.toml")
CHANGELOG = Path("packages/pow-cli/CHANGELOG.md")
VERSIONED_FILES = [str(ROOT_TOML), str(PKG_TOML), "uv.lock"]

BUMP_CHOICES = ["major", "minor", "patch", "stable", "alpha", "beta", "rc"]

# Must match the guard in .github/workflows/publish.yml, or the tag builds nothing.
CANONICAL_VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?")


def child_env() -> dict[str, str]:
    """Environment for nested commands.

    This script runs inside uv's own PEP 723 environment; leaking VIRTUAL_ENV
    into nested `uv` calls makes every one of them warn about a mismatch with
    the project's .venv.
    """
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    return env


def say(message: str = "") -> None:
    """Print, flushing so our output stays interleaved with the subprocesses'."""
    print(message, flush=True)


def die(message: str) -> None:
    sys.exit(f"error: {message}")


def run(*args: str, capture: bool = False) -> str:
    """Run a command, failing the bump if it does."""
    result = subprocess.run(args, text=True, capture_output=capture, env=child_env())
    if result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        die(f"`{' '.join(args)}` failed")
    return result.stdout.strip() if capture else ""


def project_version(path: Path) -> str:
    with path.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def semver(version: str) -> str:
    """Canonical PEP 440 -> SemVer: 0.2.0rc1 -> 0.2.0-rc.1.

    pyproject.toml holds the PEP 440 form because uv and PyPI normalize to it;
    tags, the GitHub release title, and CHANGELOG headings use SemVer.
    """
    return re.sub(r"(a|b|rc)(\d+)$", r"-\1.\2", version)


def release_changelog(text: str, version: str, release_date: date) -> str:
    """Promote only the first H2 when it is the Unreleased section."""
    heading = re.search(r"^ {0,3}##[ \t]+([^\r\n]*)", text, re.MULTILINE)
    if heading is None or heading.group(1).strip().rstrip("#").strip() != "[Unreleased]":
        return text
    return (
        text[:heading.start()]
        + f"## [{semver(version)}] - {release_date.isoformat()}"
        + text[heading.end():]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="uv run bump.py",
        description="Bump the pow-cli version and date the top Unreleased changelog entry.",
        epilog=(
            "The version written to pyproject.toml is canonical PEP 440 -- X.Y.Z "
            "optionally followed by aN, bN, or rcN -- because uv and PyPI "
            "normalize to that form. The git tag and CHANGELOG heading use the "
            "SemVer spelling instead (0.3.0rc1 -> 0.3.0-rc.1). .post and .dev "
            "releases are rejected because the publish workflow refuses to build "
            "them. Nothing is committed; that is yours to do."
        ),
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="set an exact version, e.g. 0.3.0rc1",
    )
    parser.add_argument(
        "--bump",
        action="append",
        choices=BUMP_CHOICES,
        metavar="PART",
        help=(
            "bump a version component (%(choices)s); repeatable, "
            "e.g. --bump minor --bump rc"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change; change nothing",
    )

    args = parser.parse_args()
    if args.version and args.bump:
        parser.error("give either an exact version or --bump, not both")
    if not args.version and not args.bump:
        parser.error("give a version (e.g. 0.3.0rc1) or --bump PART")
    return args


def main() -> None:
    args = parse_args()

    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        env=child_env(),
    )
    if root.returncode != 0:
        die("not inside a git repository")
    os.chdir(root.stdout.strip())

    if shutil.which("uv") is None:
        die("uv is not installed")

    spec = [args.version] if args.version else [
        arg for part in args.bump for arg in ("--bump", part)
    ]

    # Resolve the target version before writing anything.
    current = run("uv", "version", "--package", "pow-cli", "--short", capture=True)
    new_version = run(
        "uv", "version", "--package", "pow-cli", "--dry-run", "--short", *spec,
        capture=True,
    )

    if not CANONICAL_VERSION.fullmatch(new_version):
        die(
            f"'{new_version}' is not a canonical PEP 440 release version; "
            f"the publish workflow would reject v{new_version}"
        )

    say(f"pow-cli {current} => {new_version}")
    release_date = date.today()
    changelog_text = CHANGELOG.read_text()
    updated_changelog = release_changelog(changelog_text, new_version, release_date)
    changelog_changed = updated_changelog != changelog_text
    tag_version = semver(new_version)

    if args.dry_run:
        say("\ndry run; would then:")
        say(f"  uv version --package pow-cli --no-sync {' '.join(spec)}")
        say(f"  uv version --no-sync {new_version}        # workspace root")
        if changelog_changed:
            say(f"  {CHANGELOG}: ## [Unreleased] => ## [{tag_version}] - {release_date.isoformat()}")
        return

    # --no-sync relocks uv.lock (which pins pow-cli's own version) without
    # rebuilding the virtualenv, so this never reaches the NVIDIA index.
    run("uv", "version", "--package", "pow-cli", "--no-sync", *spec)
    run("uv", "version", "--no-sync", new_version)

    for toml in (PKG_TOML, ROOT_TOML):
        got = project_version(toml)
        if got != new_version:
            die(f"{toml} is {got}, expected {new_version}")

    changed_files = list(VERSIONED_FILES)
    if changelog_changed:
        CHANGELOG.write_text(updated_changelog)
        changed_files.append(str(CHANGELOG))

    say("\nchanged:")
    for path in changed_files:
        say(f"  {path}")

    # Tags and CHANGELOG headings use the SemVer spelling of the same version.
    tag_version = semver(new_version)

    if f"[{tag_version}]" not in updated_changelog:
        say(f"\nwarning: no '[{tag_version}]' heading in {CHANGELOG}")

    say(
        f"\nNothing committed. Next:\n"
        f"  1. review the [{tag_version}] entry in {CHANGELOG}\n"
        f"  2. git commit -m 'chore: bump to {tag_version}'\n"
        f"  3. git tag -a v{tag_version} -m 'pow-cli {tag_version}', push branch and tag\n"
        f"  4. gh release create v{tag_version} --title 'pow@v{tag_version}'"
        f"{' --prerelease' if tag_version != new_version else ''} --notes ...\n"
        f"To undo:\n"
        f"  git checkout -- {' '.join(changed_files)}"
    )


if __name__ == "__main__":
    main()
