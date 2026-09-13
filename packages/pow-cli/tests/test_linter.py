"""Lint rule 4 — Isaac asset paths must match the project's [sim] version."""

import pytest

from pow_cli.core.linter import lint_file, fix_file

S3 = "https://omniverse-content-production.s3.us-west-2.amazonaws.com"


@pytest.fixture
def project(tmp_path, monkeypatch, reset_config_singleton):
    """Build a project on disk and return a writer for its .usda file."""

    def _make(usda: str, *, pow_toml: str | None = '[sim]\nversion = "6.1.0"\n'):
        if pow_toml is not None:
            (tmp_path / "pow.toml").write_text(pow_toml)
        usda_file = tmp_path / "stage.usda"
        usda_file.write_text(usda)
        monkeypatch.chdir(tmp_path)
        return usda_file

    return _make


def _ref(version: str) -> str:
    return f"    prepend references = @{S3}/Assets/Isaac/{version}/Isaac/Robots/Carter/nova_carter.usd@\n"


class TestAssetVersionRule:
    def test_flags_a_reference_from_an_older_release(self, project):
        usda = project(_ref("5.0"))

        issues = lint_file(usda)

        assert len(issues) == 1
        # Only the version segment is reported, so the fix survives rule 1.
        assert issues[0].original == "Assets/Isaac/5.0"
        assert issues[0].replacement == "Assets/Isaac/6.1"
        assert issues[0].line == 1
        assert "does not match sim.version 6.1.0" in issues[0].message

    def test_matching_version_is_left_alone(self, project):
        usda = project(_ref("6.1"))

        assert lint_file(usda) == []

    def test_fix_rewrites_the_version_in_place(self, project):
        usda = project(_ref("5.0"))

        fix_file(usda, lint_file(usda))

        assert usda.read_text() == _ref("6.1")
        assert lint_file(usda) == []

    def test_a_newer_reference_is_pulled_back_to_the_configured_version(self, project):
        usda = project(_ref("6.1"), pow_toml='[sim]\nversion = "5.1.0"\n')

        issues = lint_file(usda)

        assert [(i.original, i.replacement) for i in issues] == [
            ("Assets/Isaac/6.1", "Assets/Isaac/5.1")
        ]

    def test_relative_reference_is_fully_fixed_in_one_pass(self, project):
        """Rules 1 and 4 both fire on this line; one `lint fix` must settle both."""
        usda = project(
            "    prepend references = "
            "@../../.pow/assets/Assets/Isaac/5.0/Isaac/Robots/Carter/nova_carter.usd@\n"
        )

        issues = lint_file(usda)
        fix_file(usda, issues)

        assert len(issues) == 2
        text = usda.read_text()
        assert f"@{S3}/Assets/Isaac/6.1/Isaac/Robots/Carter/nova_carter.usd@" in text
        assert "5.0" not in text
        assert lint_file(usda) == []

    def test_fix_does_not_touch_look_alike_text_outside_references(self, project):
        """A version in a comment is not a path - `pow lint fix` must skip it."""
        comment = "# authored against Assets/Isaac/5.0 - keep this as written\n"
        usda = project(comment + _ref("5.0"))

        fix_file(usda, lint_file(usda))

        assert usda.read_text() == comment + _ref("6.1")

    def test_an_earlier_fix_does_not_strand_a_relative_path(self, project):
        """Rule 4 firing on line 1 must not block rule 1 on line 2."""
        relative = (
            "    prepend references = "
            "@../../.pow/assets/Assets/Isaac/5.0/Isaac/Props/forklift.usd@\n"
        )
        usda = project(_ref("5.0") + relative)

        fix_file(usda, lint_file(usda))

        text = usda.read_text()
        assert "../../.pow/assets" not in text
        assert text.count("Assets/Isaac/6.1") == 2
        assert lint_file(usda) == []

    def test_version_outside_an_asset_reference_is_ignored(self, project):
        usda = project(
            "# authored against Assets/Isaac/5.0\n"
            'def Xform "Assets_Isaac_5_0" {\n}\n'
        )

        assert lint_file(usda) == []

    def test_every_mismatched_line_is_reported(self, project):
        usda = project(_ref("5.0") + _ref("6.1") + _ref("5.1"))

        issues = lint_file(usda)

        assert [i.line for i in issues] == [1, 3]

    def test_short_label_names_both_versions(self, project):
        usda = project(_ref("5.0"))

        assert lint_file(usda)[0].label == (
            "asset version 5.0 → 6.1 (sim.version 6.1.0)"
        )


class TestAssetVersionRuleIsOptional:
    def test_skipped_without_pow_toml(self, project):
        usda = project(_ref("5.0"), pow_toml=None)

        assert lint_file(usda) == []

    def test_skipped_when_version_is_unset(self, project):
        usda = project(_ref("5.0"), pow_toml="[sim]\nenable_ros = false\n")

        assert lint_file(usda) == []

    def test_other_rules_still_run_without_a_version(self, project):
        usda = project(
            "    prepend references = @../../.pow/assets/Pow/MyRobot/robot.usd@\n",
            pow_toml="[sim]\nenable_ros = false\n",
        )

        issues = lint_file(usda)

        assert [i.replacement for i in issues] == ["@pow-assets/Pow/MyRobot/robot.usd@"]
        assert issues[0].label == "relative path → use pow-assets alias"


@pytest.mark.parametrize("source", ["5.1", "6.0", "6.1"])
def test_6_1_0_asset_fixes_are_explicit_and_idempotent(project, source):
    usda = project(_ref(source), pow_toml='[sim]\nversion = "6.1.0"\n')
    original = usda.read_text()
    issues = lint_file(usda)
    assert usda.read_text() == original
    assert bool(issues) == (source != "6.1")
    fix_file(usda, issues)
    assert usda.read_text() == _ref("6.1")
    assert lint_file(usda) == []
    fix_file(usda, [])
    assert usda.read_text() == _ref("6.1")
