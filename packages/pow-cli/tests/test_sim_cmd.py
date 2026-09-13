import pytest
from click.testing import CliRunner

from pow_cli.cli.sim import sim_group
from pow_cli.core.models.pow_config import PowConfig


@pytest.fixture(autouse=True)
def skip_setup(mocker):
    """Argument-routing tests; real prerequisite setup is covered separately."""
    mocker.patch.object(PowConfig, "configured_default_version", return_value="")
    return mocker.patch("pow_cli.cli.sim._ensure_sim_ready")


@pytest.mark.cli
class TestSim:
    """`pow sim` forwards raw args and bridge selection to Runner.run_sim."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        self.runner = CliRunner()
        self.mock_run = mocker.patch("pow_cli.core.runner.Runner.run_sim")

    def _invoke(self, args):
        return self.runner.invoke(
            sim_group, args, env={"NO_COLOR": "1", "TERM": "dumb"}
        )

    def test_bare_sim_uses_defaults(self, mocker):
        # Pin the auto-detected default; otherwise the assertion depends on
        # what happens to be installed under ~/.pow/isaacsim on this machine.
        mocker.patch.object(PowConfig, "resolve_installed_version", return_value="5.1.0")

        result = self._invoke([])
        assert result.exit_code == 0
        self.mock_run.assert_called_once_with(
            version="5.1.0", ros_bridge="jazzy", extra_args=[]
        )

    def test_launch_default_version_follows_installed(self, mocker):
        """-v defaults to whatever is installed, not a frozen constant."""
        mocker.patch.object(PowConfig, "resolve_installed_version", return_value="6.1.0")

        result = self._invoke(["--no-ros"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["version"] == "6.1.0"

    def test_no_ros_disables_bridge(self):
        result = self._invoke(["--no-ros"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["ros_bridge"] is None

    def test_ros_selects_bridge_distro(self):
        result = self._invoke(["--ros", "humble"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["ros_bridge"] == "humble"

    def test_no_ros_wins_over_ros(self):
        result = self._invoke(["--ros", "humble", "--no-ros"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["ros_bridge"] is None

    def test_unsupported_bridge_rejected(self):
        result = self._invoke(["--ros", "iron"])
        assert result.exit_code == 2
        self.mock_run.assert_not_called()

    def test_version_option(self):
        result = self._invoke(["-v", "5.0.0"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["version"] == "5.0.0"

    def test_raw_args_after_double_dash(self):
        result = self._invoke(["--", "--no-window", "--/renderer/enabled=gpu"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["extra_args"] == [
            "--no-window",
            "--/renderer/enabled=gpu",
        ]

    def test_unknown_options_pass_through_without_double_dash(self):
        result = self._invoke(["--/renderer/enabled=gpu"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["extra_args"] == ["--/renderer/enabled=gpu"]

    def test_runs_outside_a_pow_project(self, tmp_path, monkeypatch):
        """No pow.toml above cwd must not produce a 'Not initialized' error."""
        monkeypatch.chdir(tmp_path)
        result = self._invoke([])
        assert result.exit_code == 0
        assert "Not initialized" not in result.output

    def test_explicit_launch_subcommand(self, mocker):
        """`pow sim launch` is the explicit form of the bare command."""
        mocker.patch.object(PowConfig, "resolve_installed_version", return_value="5.1.0")

        result = self._invoke(["launch", "--", "--no-window"])
        assert result.exit_code == 0
        self.mock_run.assert_called_once_with(
            version="5.1.0", ros_bridge="jazzy", extra_args=["--no-window"]
        )

    def test_help_lists_subcommands(self, skip_setup):
        result = self._invoke(["--help"])
        assert result.exit_code == 0
        assert "launch" in result.output
        assert "check" in result.output
        self.mock_run.assert_not_called()
        skip_setup.assert_not_called()

    def test_help_lists_launch_options(self, mocker):
        """Bare `pow sim` accepts launch's options, so its help must show them."""
        scan = mocker.patch.object(
            PowConfig, "resolve_installed_version", return_value="6.1.0"
        )

        result = self._invoke(["--help"])
        assert result.exit_code == 0
        assert "-v, --version" in result.output
        assert "--ros" in result.output
        assert "--no-ros" in result.output
        # The shown default is a literal string; rendering help must not scan.
        scan.assert_not_called()


@pytest.mark.cli
class TestSimCheck:
    """`pow sim check` forwards the version and raw args to Runner.run_sim_check."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        self.runner = CliRunner()
        self.mock_check = mocker.patch("pow_cli.core.runner.Runner.run_sim_check")
        self.mock_run = mocker.patch("pow_cli.core.runner.Runner.run_sim")

    def _invoke(self, args):
        return self.runner.invoke(
            sim_group, args, env={"NO_COLOR": "1", "TERM": "dumb"}
        )

    def test_check_uses_default_version(self, mocker):
        mocker.patch.object(PowConfig, "resolve_installed_version", return_value="5.1.0")

        result = self._invoke(["check"])
        assert result.exit_code == 0
        self.mock_check.assert_called_once_with(version="5.1.0", extra_args=[])
        self.mock_run.assert_not_called()

    def test_check_honors_version_option(self):
        result = self._invoke(["check", "-v", "5.0.0"])
        assert result.exit_code == 0
        assert self.mock_check.call_args.kwargs["version"] == "5.0.0"

    def test_check_forwards_raw_args(self):
        result = self._invoke(["check", "--", "--no-ros-env"])
        assert result.exit_code == 0
        assert self.mock_check.call_args.kwargs["extra_args"] == ["--no-ros-env"]

    def test_check_runs_outside_a_pow_project(self, tmp_path, monkeypatch):
        """No pow.toml above cwd must not produce a 'Not initialized' error."""
        monkeypatch.chdir(tmp_path)
        result = self._invoke(["check"])
        assert result.exit_code == 0
        assert "Not initialized" not in result.output


@pytest.mark.cli
class TestSimDefaultVersion:
    """`-v` -> [sim] default_version in system.toml -> newest installed."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        self.runner = CliRunner()
        self.mock_run = mocker.patch("pow_cli.core.runner.Runner.run_sim")
        self.mock_check = mocker.patch("pow_cli.core.runner.Runner.run_sim_check")
        self.mocker = mocker

    def _invoke(self, args):
        return self.runner.invoke(
            sim_group, args, env={"NO_COLOR": "1", "TERM": "dumb"}
        )

    def _pin(self, pinned, installed):
        self.mocker.patch.object(
            PowConfig, "configured_default_version", return_value=pinned
        )
        self.mocker.patch.object(
            PowConfig, "installed_versions", return_value=list(installed)
        )
        self.mocker.patch.object(
            PowConfig,
            "resolve_installed_version",
            return_value=installed[0] if installed else PowConfig.ISAACSIM_VERSION,
        )

    def test_pinned_version_is_used(self):
        self._pin("5.1.0", ["6.1.0", "5.1.0"])

        result = self._invoke([])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["version"] == "5.1.0"

    def test_version_option_overrides_the_pin(self):
        self._pin("5.1.0", ["6.1.0", "5.1.0"])

        result = self._invoke(["-v", "6.1.0"])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["version"] == "6.1.0"
        assert "system.toml pins" not in result.output

    def test_missing_pin_is_passed_to_setup_without_falling_back(self, skip_setup):
        self._pin("5.1.0", ["6.1.0"])

        result = self._invoke([])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["version"] == "5.1.0"
        skip_setup.assert_called_once_with("5.1.0", check=False)

    def test_pin_is_honored_when_nothing_is_installed(self):
        """First use installs the pin rather than selecting another version."""
        self._pin("5.1.0", [])

        result = self._invoke([])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["version"] == "5.1.0"
        assert "system.toml pins" not in result.output

    def test_no_pin_falls_back_to_newest_installed(self):
        self._pin("", ["6.1.0", "5.1.0"])

        result = self._invoke([])
        assert result.exit_code == 0
        assert self.mock_run.call_args.kwargs["version"] == "6.1.0"

    def test_check_honors_the_pin(self):
        self._pin("5.1.0", ["6.1.0", "5.1.0"])

        result = self._invoke(["check"])
        assert result.exit_code == 0
        assert self.mock_check.call_args.kwargs["version"] == "5.1.0"
