from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from pow_cli.cli.ros import ros_group


@pytest.mark.cli
class TestRosLaunch:
    """Bare `pow ros` and the `launch` subcommand forward args to the container."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        self.runner = CliRunner()
        self.mock_run = mocker.patch(
            "pow_cli.core.ros_manager.RosManager.run_simros_container"
        )

    def _invoke(self, args):
        return self.runner.invoke(
            ros_group, args, env={"NO_COLOR": "1", "TERM": "dumb"}
        )

    def test_bare_ros_launches(self):
        result = self._invoke([])
        assert result.exit_code == 0
        self.mock_run.assert_called_once_with(extra_args=None, verbose=False)

    def test_extra_args_forwarded(self):
        result = self._invoke(["bash"])
        assert result.exit_code == 0
        self.mock_run.assert_called_once_with(extra_args=["bash"], verbose=False)

    def test_verbose_and_multiple_args(self):
        result = self._invoke(["-v", "ros2", "topic", "list"])
        assert result.exit_code == 0
        self.mock_run.assert_called_once_with(
            extra_args=["ros2", "topic", "list"], verbose=True
        )

    def test_explicit_launch_subcommand(self):
        result = self._invoke(["launch", "bash"])
        assert result.exit_code == 0
        self.mock_run.assert_called_once_with(extra_args=["bash"], verbose=False)

    def test_help_lists_subcommands(self):
        result = self._invoke(["--help"])
        assert result.exit_code == 0
        assert "build" in result.output
        assert "launch" in result.output
        self.mock_run.assert_not_called()


@pytest.mark.cli
class TestRosBuild:
    """`pow ros build` builds the custom image from ros_dockerfile."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        self.runner = CliRunner()
        self.cfg = MagicMock()
        self.cfg.project_root = Path("/home/user/myproject")
        self.cfg.ros_dockerfile = "docker/Dockerfile.simros"
        self.cfg.ros_docker_image = "my_robot_sim"
        self.cfg.ros_distro = "jazzy"
        mocker.patch("pow_cli.cli.ros.RosManager.__init__", return_value=None)
        mocker.patch(
            "pow_cli.cli.ros.RosManager.config",
            new_callable=mocker.PropertyMock,
            return_value=self.cfg,
        )
        self.mock_exists = mocker.patch(
            "pow_cli.cli.ros.RosManager.image_exists", return_value=True
        )
        self.mock_build = mocker.patch(
            "pow_cli.cli.ros.RosManager.build_custom_ros_image",
            return_value={"status": "built", "image": "my_robot_sim"},
        )
        self.mock_build_base = mocker.patch(
            "pow_cli.cli.ros.RosManager.build_simros_image",
            return_value={"status": "built", "image": "pow_simros_jazzy"},
        )
        # config.ros_ws_path / "jazzy_ws" — workspace exists by default
        self.cfg.ros_ws_path.__truediv__.return_value.exists.return_value = True

    def _invoke(self, args):
        return self.runner.invoke(
            ros_group, args, env={"NO_COLOR": "1", "TERM": "dumb"}
        )

    def test_build_dispatches_to_subcommand(self):
        result = self._invoke(["build"])
        assert result.exit_code == 0
        self.mock_build.assert_called_once()
        assert self.mock_build.call_args.kwargs["no_cache"] is False
        assert "my_robot_sim" in result.output

    def test_build_no_cache_passed_through(self):
        result = self._invoke(["build", "--no-cache"])
        assert result.exit_code == 0
        assert self.mock_build.call_args.kwargs["no_cache"] is True

    def test_build_refuses_aarch64(self, mocker):
        mocker.patch("platform.machine", return_value="aarch64")
        result = self._invoke(["build"])
        assert result.exit_code != 0
        assert "amd64-only" in result.output
        self.mock_build.assert_not_called()
        self.mock_build_base.assert_not_called()

    def test_build_without_dockerfile_hints_and_exits_zero(self):
        self.cfg.ros_dockerfile = ""
        result = self._invoke(["build"])
        assert result.exit_code == 0
        assert "nothing to build" in result.output.lower()
        self.mock_build.assert_not_called()

    def test_build_missing_base_image_builds_it_first(self):
        self.mock_exists.return_value = False
        result = self._invoke(["build"])
        assert result.exit_code == 0
        self.mock_build_base.assert_called_once()
        self.mock_build.assert_called_once()
        assert "pow_simros_jazzy" in result.output

    def test_build_base_image_skipped_when_present(self):
        result = self._invoke(["build"])
        assert result.exit_code == 0
        self.mock_build_base.assert_not_called()
        self.mock_build.assert_called_once()

    def test_build_missing_base_and_workspace_errors(self):
        self.mock_exists.return_value = False
        self.cfg.ros_ws_path.__truediv__.return_value.exists.return_value = False
        result = self._invoke(["build"])
        assert result.exit_code != 0
        assert "pow init" in result.output
        self.mock_build_base.assert_not_called()
        self.mock_build.assert_not_called()

    def test_build_base_failure_exits_nonzero(self):
        self.mock_exists.return_value = False
        self.mock_build_base.side_effect = RuntimeError("base build failed")
        result = self._invoke(["build"])
        assert result.exit_code == 1
        assert "base build failed" in result.output
        self.mock_build.assert_not_called()

    def test_build_not_initialized_errors(self):
        self.cfg.project_root = None
        result = self._invoke(["build"])
        assert result.exit_code != 0
        assert "pow init" in result.output
        self.mock_build.assert_not_called()

    def test_build_failure_exits_nonzero(self):
        self.mock_build.side_effect = RuntimeError("docker build failed")
        result = self._invoke(["build"])
        assert result.exit_code == 1
        assert "docker build failed" in result.output
