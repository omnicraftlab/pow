"""Changelog promotion by the repository's release helper."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("bump", Path(__file__).resolve().parents[3] / "bump.py")
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


@pytest.mark.parametrize("version,heading", [
    ("0.4.0", "0.4.0"),
    ("0.4.0rc1", "0.4.0-rc.1"),
])
def test_promotes_top_unreleased_preserving_body(version, heading):
    text = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- Feature\n\n## [0.3.0] - 2026-09-07\n"
    assert bump.release_changelog(text, version, date(2026, 9, 14)) == text.replace(
        "## [Unreleased]", f"## [{heading}] - 2026-09-14", 1
    )


@pytest.mark.parametrize("text", [
    "# Changelog\n",
    "## [0.3.0] - 2026-09-07\n\n## [Unreleased]\n",
    "## Other\n\n## [Unreleased]\n",
])
def test_does_not_promote_later_or_missing_unreleased(text):
    assert bump.release_changelog(text, "0.4.0", date(2026, 9, 14)) == text
