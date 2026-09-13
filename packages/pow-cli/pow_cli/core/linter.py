"""Linter — detects and fixes relative asset paths in .usda files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class LintIssue:
    """A single lint finding in a .usda file."""

    file: Path
    line: int
    original: str
    replacement: str
    message: str
    label: str = ""      # short one-line description, used by `pow lint -s`
    start: int = -1      # offset of `original` within its line
    end: int = -1        # end offset, exclusive


@dataclass
class AliasGroup:
    """Categorised alias keys from omniverse.toml [aliases]."""

    pow_assets: dict[str, str]      # group a: pow-assets key
    sim_ready: dict[str, str]       # group b: staging S3 URLs
    nvidia_assets: dict[str, str]   # group c: everything else


# S3 URL prefixes used to classify aliases into groups
_SIM_READY_PREFIXES = (
    "http://omniverse-content-staging.s3.us-west-2.amazonaws.com",
    "https://omniverse-content-staging.s3.us-west-2.amazonaws.com",
)

# NVIDIA production S3 URL (used for non-Pow, non-SimReady assets)
_NVIDIA_PRODUCTION_S3 = "https://omniverse-content-production.s3.us-west-2.amazonaws.com"

# Regex: match @<one or more ../>.pow/assets/<rest>@ inside .usda
# Captures the path after .pow/assets/ so we can rewrite to @pow-assets/<rest>@
_RELATIVE_POW_ASSETS_RE = re.compile(
    r"@(?:\.\./)+\.pow/assets/(.+?)@"
)

# Regex: an asset reference, i.e. anything between a pair of @ in .usda.
# Used to keep version checks out of comments and prim names.
_ASSET_REF_RE = re.compile(r"@[^@]*@")

# Known release namespaces are verified in PowConfig.ISAACSIM_RELEASES.
_ISAAC_ASSET_VERSION_TEMPLATE = r"Assets/Isaac/(?!{target}/)(\d+\.\d+)(?=/)"


# ── Alias config loader ──────────────────────────────────────────────────────


class AliasConfig:
    """Reads and categorises [aliases] from omniverse.toml."""

    OMNIVERSE_TOML_PATH = Path.home() / ".nvidia-omniverse" / "config" / "omniverse.toml"

    def __init__(self) -> None:
        self.groups = self._load()

    def _load(self) -> AliasGroup:
        aliases: dict[str, str] = {}

        if self.OMNIVERSE_TOML_PATH.exists():
            with open(self.OMNIVERSE_TOML_PATH, "rb") as f:
                doc = tomllib.load(f)
            aliases = doc.get("aliases", {})

        pow_assets: dict[str, str] = {}
        sim_ready: dict[str, str] = {}
        nvidia_assets: dict[str, str] = {}

        for key, value in aliases.items():
            if key == "pow-assets":
                pow_assets[key] = value
            elif key in _SIM_READY_PREFIXES:
                sim_ready[key] = value
            else:
                nvidia_assets[key] = value

        return AliasGroup(
            pow_assets=pow_assets,
            sim_ready=sim_ready,
            nvidia_assets=nvidia_assets,
        )

    @property
    def has_pow_assets(self) -> bool:
        return bool(self.groups.pow_assets)


# ── Linter engine ─────────────────────────────────────────────────────────────


def _asset_version_of(sim_version: str) -> str:
    """Verified asset namespaces; unknown releases must not rewrite scenes."""
    from .models.pow_config import PowConfig

    return PowConfig.ISAACSIM_RELEASES.get(sim_version.strip(), {}).get("asset_version", "")


def scan_directory(path: Path) -> List[Path]:
    """Recursively find all .usda files under the given path."""
    if path.is_file():
        return [path] if path.suffix == ".usda" else []
    return sorted(path.rglob("*.usda"))


def lint_file(file_path: Path, alias_config: AliasConfig | None = None) -> List[LintIssue]:
    """Scan a single .usda file for relative asset path issues.

    Returns a list of LintIssue objects, one per problematic line.
    """
    from .models.pow_config import PowConfig

    issues: List[LintIssue] = []
    text = file_path.read_text(encoding="utf-8")

    # ── Prepare detection patterns ─────────────────────────────────────────
    home_dir = str(Path.home())
    # General rule: any @/home/user/...@ → @user-home/...@
    home_abs_re = re.compile(r"@" + re.escape(home_dir) + r"/([^@]+)@")

    # ROS workspace relative rule: @../../../../simros_ws/...@ → @user-home/simros_ws/...@
    ros_ws_rel_re: re.Pattern | None = None
    ros_ws_home_relative: str | None = None

    # Isaac asset version rule: the project's [sim] version decides which
    # Assets/Isaac/<major>.<minor> tree references must point at.
    asset_version_re: re.Pattern | None = None
    sim_version: str = ""
    asset_version: str = ""
    try:
        config = PowConfig()
        raw_ros_ws: str = config.get("isaacsim_ros_ws", "~/IsaacSim-ros_workspaces")
        if raw_ros_ws.startswith("~/"):
            ros_ws_home_relative = raw_ros_ws[2:]
        elif raw_ros_ws.startswith("~"):
            ros_ws_home_relative = raw_ros_ws[1:]

        if ros_ws_home_relative:
            escaped_name = re.escape(ros_ws_home_relative)
            ros_ws_rel_re = re.compile(
                r"@(?:\.\./)+(" + escaped_name + r"/[^@]*)@"
            )

        sim_version = str(config.get("version", "") or "")
        asset_version = _asset_version_of(sim_version)
        if asset_version:
            asset_version_re = re.compile(
                _ISAAC_ASSET_VERSION_TEMPLATE.format(target=re.escape(asset_version))
            )
    except Exception:
        pass

    # ── Build lint rules ───────────────────────────────────────────────────
    # Each rule is a (compiled_regex, handler, scope) triple.  The handler
    # receives (match, file_path, line_num) and returns a
    # (replacement, message, label) tuple.  scope is "line" to search the whole
    # line, or "refs" to search only inside @...@ asset references.
    rules: list[tuple[re.Pattern, callable, str]] = []

    # Rule 1: relative .pow/assets paths
    def _handle_pow_assets(m, _fp, _ln):
        asset_subpath = m.group(1)
        original = m.group(0)
        # Routing rules (checked in order):
        #   1. simready_content  → sim-ready staging S3 URL
        #   2. Pow in path       → pow-assets alias (custom pow content)
        #   3. everything else   → NVIDIA production S3 URL
        if "simready_content" in asset_subpath:
            replacement = f"@{_SIM_READY_PREFIXES[1]}/{asset_subpath}@"
            label = "relative path → use sim-ready staging S3 URL"
            message = (
                f"Relative path to sim-ready asset — use sim-ready staging S3 URL: "
                f"{original} → {replacement}"
            )
        elif "Pow" in asset_subpath:
            replacement = f"@pow-assets/{asset_subpath}@"
            label = "relative path → use pow-assets alias"
            message = (
                f"Relative path to pow asset — use pow-assets alias: "
                f"{original} → {replacement}"
            )
        else:
            replacement = f"@{_NVIDIA_PRODUCTION_S3}/{asset_subpath}@"
            label = "relative path → use NVIDIA production S3 URL"
            message = (
                f"Relative path to NVIDIA asset — use production S3 URL: "
                f"{original} → {replacement}"
            )
        return replacement, message, label

    rules.append((_RELATIVE_POW_ASSETS_RE, _handle_pow_assets, "line"))

    # Rule 2: absolute home-directory paths (general)
    #   @/home/user/anything/...@ → @user-home/anything/...@
    def _handle_home_abs(m, _fp, _ln):
        rest = m.group(1)
        original = m.group(0)
        replacement = f"@user-home/{rest}@"
        message = (
            f"Absolute home path — use user-home alias: "
            f"{original} → {replacement}"
        )
        return replacement, message, "absolute home path → use user-home alias"

    rules.append((home_abs_re, _handle_home_abs, "line"))

    # Rule 3: relative ROS workspace paths
    #   @../../../../simros_ws/...@ → @user-home/simros_ws/...@
    if ros_ws_rel_re:
        def _handle_ros_rel(m, _fp, _ln):
            ws_and_rest = m.group(1)
            original = m.group(0)
            replacement = f"@user-home/{ws_and_rest}@"
            message = (
                f"Relative ROS workspace path — use user-home alias: "
                f"{original} → {replacement}"
            )
            return replacement, message, "relative ROS workspace path → use user-home alias"

        rules.append((ros_ws_rel_re, _handle_ros_rel, "line"))

    # Rule 4: Isaac asset version must match [sim] version
    #   Assets/Isaac/5.1/... → Assets/Isaac/6.1/...   (when version = "6.1.0")
    if asset_version_re:
        def _handle_asset_version(m, _fp, _ln):
            found = m.group(1)
            replacement = f"Assets/Isaac/{asset_version}"
            message = (
                f"Isaac asset version {found} does not match sim.version "
                f"{sim_version} — use {replacement}"
            )
            label = (
                f"asset version {found} → {asset_version} "
                f"(sim.version {sim_version})"
            )
            return replacement, message, label

        # Reference-scoped: a version number in a comment is not an asset path.
        rules.append((asset_version_re, _handle_asset_version, "refs"))

    # ── Scan lines ────────────────────────────────────────────────────────
    for line_num, line in enumerate(text.splitlines(), start=1):
        ref_spans: list[tuple[int, int]] | None = None
        for pattern, handler, scope in rules:
            if scope == "refs":
                if ref_spans is None:
                    ref_spans = [m.span() for m in _ASSET_REF_RE.finditer(line)]
                spans = ref_spans
            else:
                spans = [(0, len(line))]

            for start, end in spans:
                # pos/endpos keep the offsets line-relative, which is what
                # fix_file needs to rewrite exactly this match and nothing else.
                for match in pattern.finditer(line, start, end):
                    replacement, message, label = handler(match, file_path, line_num)
                    issues.append(
                        LintIssue(
                            file=file_path,
                            line=line_num,
                            original=match.group(0),
                            replacement=replacement,
                            message=message,
                            label=label,
                            start=match.start(),
                            end=match.end(),
                        )
                    )

    return issues


_MAX_FIX_PASSES = 5


def _apply_pass(file_path: Path, issues: List[LintIssue]) -> int:
    """Rewrite each issue's own span, skipping ones nested inside another.

    Returns the number of fixes written.  Replacing by span rather than by
    string keeps look-alike text elsewhere in the file - a version number in a
    comment, say - untouched.
    """
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)

    by_line: dict[int, List[LintIssue]] = {}
    for issue in issues:
        if issue.start >= 0:
            by_line.setdefault(issue.line, []).append(issue)

    applied = 0
    for line_num, line_issues in by_line.items():
        index = line_num - 1
        if index >= len(lines):
            continue
        line = lines[index]

        # Widest match first, then right to left so earlier offsets stay valid.
        ordered = sorted(line_issues, key=lambda i: (i.start, -(i.end - i.start)))
        chosen: List[LintIssue] = []
        for issue in ordered:
            if line[issue.start:issue.end] != issue.original:
                continue  # the line moved under us; a later pass will catch it
            # One rule can match inside another's span (rule 4 sits inside the
            # reference rule 1 rewrites).  Take the outer one now and let the
            # next pass re-lint the rewritten text.
            if chosen and issue.start < chosen[-1].end:
                continue
            chosen.append(issue)

        for issue in reversed(chosen):
            line = line[:issue.start] + issue.replacement + line[issue.end:]
            applied += 1
        lines[index] = line

    if applied:
        file_path.write_text("".join(lines), encoding="utf-8")
    return applied


def fix_file(
    file_path: Path,
    issues: List[LintIssue],
    alias_config: AliasConfig | None = None,
) -> None:
    """Apply all lint fixes to a file in-place.

    Rules can chain: rewriting a relative path to its S3 URL (rule 1) can leave
    an Isaac asset version behind for rule 4 to correct.  Each pass applies the
    outermost fixes and re-lints, so a single `pow lint fix` settles the file.
    """
    remaining = issues
    for _ in range(_MAX_FIX_PASSES):
        if not remaining or not _apply_pass(file_path, remaining):
            return
        remaining = lint_file(file_path, alias_config)
