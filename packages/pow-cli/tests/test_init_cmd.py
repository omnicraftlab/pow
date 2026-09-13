import pytest
from pathlib import Path
from click.testing import CliRunner

from pow_cli.cli.init import init_cmd
from pow_cli.core.models.pow_config import PowConfig


@pytest.fixture(autouse=True)
def isolated_project(tmp_path, monkeypatch, reset_config_singleton):
    """Initializer command tests must not write to the checkout or real home."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(project)


@pytest.mark.cli
class TestInitCmd:
    @pytest.fixture(autouse=True)
    def mock_manager_methods(self, mocker):
        """Mock common Initializer methods used by init_cmd to avoid side effects."""
        self.mock_create_global = mocker.patch(
            "pow_cli.core.initializer.Initializer.create_global_folder",
            return_value={"global_existed": False, "results": []}
        )
        mocker.patch("pow_cli.core.initializer.Initializer.create_system_toml",
                     return_value={"status": "Existed", "path": "system.toml"})
        mocker.patch("pow_cli.core.initializer.Initializer.setup_omniverse_user_home_alias",
                     return_value={"status": "unchanged", "path": "omniverse.toml"})
        self.mock_download = mocker.patch(
            "pow_cli.core.initializer.Initializer.download_isaacsim",
            return_value={"status": "Already installed", "path": "/tmp/isaacsim"}
        )
        # Answer the version picker with the default so the "n\n" inputs below
        # keep lining up with the Confirm prompts they were written for.
        self.mock_version_prompt = mocker.patch(
            "pow_cli.cli.init.ask_choice",
            return_value=PowConfig.ISAACSIM_VERSION,
        )
        self.mock_fix_cache = mocker.patch(
            "pow_cli.core.initializer.Initializer.fix_asset_browser_cache",
            return_value=True
        )
        self.mock_setup_ros = mocker.patch(
            "pow_cli.core.ros_manager.RosManager.setup_ros_workspace",
            return_value={
                "status": "success",
                "ros_distro": "jazzy",
                "ubuntu_version": "24.04",
                "path": "/tmp/.pow/sim-ros",
                "ws_ref": f"IsaacSim-{PowConfig.ISAACSIM_VERSION}",
            }
        )
        self.mock_setup_project = mocker.patch(
            "pow_cli.core.initializer.Initializer.setup_project_structure",
            return_value={"results": []}
        )
        self.mock_read_config = mocker.patch("pow_cli.core.initializer.Initializer.read_config")
        self.mock_create_pow_toml = mocker.patch(
            "pow_cli.core.initializer.Initializer.create_pow_toml",
            return_value={"status": "Created", "path": "pow.toml"}
        )
        self.mock_sleep = mocker.patch("time.sleep")
        mocker.patch("pow_cli.core.initializer.Initializer.link_managed_isaacsim",
                     return_value={"status": "Existed", "path": "_isaacsim"})
        mocker.patch("pow_cli.core.initializer.Initializer.setup_vscode_configs",
                     return_value={"status": "Success", "results": []})
        self.runner = CliRunner()


    def test_init_cmd_step_1_output(self):
        result = self.runner.invoke(init_cmd, input="n\nn\n", env={"NO_COLOR": "1", "TERM": "dumb"}) 
        assert result.exit_code == 0
        assert "[1/10] 🔧 Config:" in result.output
        assert "Using global directory" in result.output

    def test_init_cmd_missing_pyproject_toml(self, mocker):
        mocker.patch("pathlib.Path.exists", return_value=False)
        result = self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})
        assert "pyproject.toml not found" in result.output
        assert result.exit_code == 0

    def test_init_cmd_accepts_existing_global_folder(self):
        self.mock_create_global.return_value = {
            "global_existed": True,
            "results": [{"path": ".pow/isaacsim", "status": "Existed"}]
        }
        result = self.runner.invoke(init_cmd, input="n\nn\n", env={"NO_COLOR": "1", "TERM": "dumb"})
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_init_cmd_asset_browser_fix_output(self):
        self.mock_create_global.return_value = {"global_existed": True, "results": []}
        result = self.runner.invoke(init_cmd, input="n\nn\n", env={"NO_COLOR": "1", "TERM": "dumb"})
        assert "Created missing cache file." in result.output

    def test_init_cmd_asset_browser_already_fixed_output(self):
        self.mock_create_global.return_value = {"global_existed": True, "results": []}
        self.mock_fix_cache.return_value = False
        result = self.runner.invoke(init_cmd, input="n\nn\n", env={"NO_COLOR": "1", "TERM": "dumb"})
        assert "Cache file already exists." in result.output

    def test_init_cmd_ros_integration_output(self, mocker):
        self.mock_create_global.return_value = {"global_existed": True, "results": []}
        mocker.patch("pow_cli.cli.init.Confirm.ask", return_value=True)
        mocker.patch(
            "pow_cli.cli.init.ask_path", return_value="~/IsaacSim-ros_workspaces"
        )
        mocker.patch(
            "pow_cli.core.ros_manager.RosManager.build_simros_image",
            return_value={"status": "existed", "image": "pow_simros_jazzy"},
        )
        mocker.patch(
            "pow_cli.core.ros_manager.RosManager.build_custom_ros_image",
            return_value={"status": "skipped"},
        )
        mocker.patch(
            "pow_cli.core.initializer.Initializer.link_managed_isaacsim",
            return_value={"status": "Existed", "path": "_isaacsim"},
        )
        mocker.patch(
            "pow_cli.core.initializer.Initializer.setup_vscode_configs",
            return_value={"status": "Success", "results": []},
        )
        mocker.patch(
            "pow_cli.core.initializer.Initializer.setup_omniverse_user_home_alias",
            return_value={"status": "exists", "path": "omniverse.toml"},
        )

        # Force Path("pow.toml").exists() to be False so we skip the first Confirm.
        def mock_exists(path_obj, *args, **kwargs):
            return str(path_obj) == "pyproject.toml"
        mocker.patch("pathlib.Path.exists", side_effect=mock_exists, autospec=True)

        result = self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})
        assert result.exit_code == 0
        assert "ROS bridge:" in result.output

    def test_init_cmd_ros_skipped_output(self):
        self.mock_create_global.return_value = {"global_existed": True, "results": []}
        # Answer 'n' to override config, 'n' to ROS integration
        result = self.runner.invoke(init_cmd, input="n\nn\n", env={"NO_COLOR": "1", "TERM": "dumb"})
        assert "Skipping ROS integration." in result.output


@pytest.mark.cli
class TestInitCmdSimVersion:
    """Which Isaac Sim version `pow init` installs."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        self.runner = CliRunner()
        self.mock_download = mocker.patch(
            "pow_cli.core.initializer.Initializer.download_isaacsim",
            return_value={"status": "Already installed", "path": "/tmp/isaacsim"},
        )
        self.mock_prompt = mocker.patch(
            "pow_cli.cli.init.ask_choice", return_value=PowConfig.ISAACSIM_VERSION
        )
        # False answers both Confirms: keep any existing pow.toml, skip ROS.
        self.mock_confirm = mocker.patch("pow_cli.cli.init.Confirm.ask", return_value=False)
        mocker.patch(
            "pow_cli.core.initializer.Initializer.create_global_folder",
            return_value={"global_existed": True, "results": []},
        )
        mocker.patch("pow_cli.core.initializer.Initializer.create_system_toml",
                     return_value={"status": "Existed", "path": "system.toml"})
        mocker.patch("pow_cli.core.initializer.Initializer.fix_asset_browser_cache",
                     return_value=False)
        mocker.patch("pow_cli.core.initializer.Initializer.setup_project_structure",
                     return_value={"results": []})
        self.mock_vscode = mocker.patch(
            "pow_cli.core.initializer.Initializer.setup_vscode_configs",
            return_value={"status": "Success", "results": [], "version": "6.1.0"},
        )
        mocker.patch("pow_cli.core.initializer.Initializer.setup_omniverse_user_home_alias",
                     return_value={"status": "unchanged", "path": "omniverse.toml"})
        self.mock_link = mocker.patch(
            "pow_cli.core.initializer.Initializer.link_managed_isaacsim",
            return_value={"status": "Existed", "path": "_isaacsim"},
        )
        self.mock_create_pow_toml = mocker.patch(
            "pow_cli.core.initializer.Initializer.create_pow_toml",
            return_value={"status": "Created", "path": "pow.toml"},
        )
        mocker.patch("time.sleep")

    def _no_pow_toml(self, mocker):
        """Only pyproject.toml exists, so step 2 asks nothing."""
        mocker.patch(
            "pathlib.Path.exists",
            side_effect=lambda path_obj, *a, **kw: str(path_obj) == "pyproject.toml",
            autospec=True,
        )

    @pytest.mark.parametrize("update_settings", [None, False, True])
    def test_flag_selects_version_without_prompting(self, mocker, update_settings):
        if update_settings is None:
            self._no_pow_toml(mocker)
        else:
            Path("pow.toml").write_text(
                f'[sim]\nversion = "{PowConfig.ISAACSIM_VERSION}"\nenable_ros = false\n'
            )
            self.mock_confirm.return_value = update_settings

        result = self.runner.invoke(
            init_cmd, ["--sim-version", "5.1.0"], env={"NO_COLOR": "1", "TERM": "dumb"}
        )

        assert result.exit_code == 0
        self.mock_prompt.assert_not_called()
        assert self.mock_download.call_args.kwargs["version"] == "5.1.0"
        assert self.mock_link.call_args.kwargs["version"] == "5.1.0"
        assert self.mock_create_pow_toml.call_args.kwargs["override"] is True
        assert self.mock_create_pow_toml.call_args.kwargs["sim_version"] == "5.1.0"

    def test_vscode_configs_are_built_for_the_resolved_version(self, mocker):
        """Step 9 must configure the version init selected, not whatever _isaacsim is."""
        self._no_pow_toml(mocker)

        self.runner.invoke(
            init_cmd, ["--sim-version", "5.1.0"], env={"NO_COLOR": "1", "TERM": "dumb"}
        )

        assert self.mock_vscode.call_args.kwargs["version"] == "5.1.0"

    def test_an_unchanged_link_keeps_the_extension_paths(self, mocker):
        self._no_pow_toml(mocker)
        self.mock_link.return_value = {"status": "Existed", "path": "_isaacsim"}

        self.runner.invoke(
            init_cmd, ["--sim-version", "5.1.0"], env={"NO_COLOR": "1", "TERM": "dumb"}
        )

        assert self.mock_vscode.call_args.kwargs["version_changed"] is False

    def test_a_repointed_link_rewrites_the_extension_paths(self, mocker):
        self._no_pow_toml(mocker)
        self.mock_link.return_value = {
            "status": "Repointed", "path": "_isaacsim", "previous": "/old/6.1.0",
        }

        self.runner.invoke(
            init_cmd, ["--sim-version", "5.1.0"], env={"NO_COLOR": "1", "TERM": "dumb"}
        )

        assert self.mock_vscode.call_args.kwargs["version_changed"] is True

    def test_a_link_failure_stops_before_vscode_and_pow_toml(self, mocker):
        """Configuring or recording a version that is not linked leaves a broken project."""
        self._no_pow_toml(mocker)
        self.mock_link.return_value = {
            "status": "Error", "message": "'_isaacsim' exists and is not a symlink.",
        }

        result = self.runner.invoke(
            init_cmd, ["--sim-version", "5.1.0"], env={"NO_COLOR": "1", "TERM": "dumb"}
        )

        assert result.exit_code == 1
        assert "Initialization incomplete" in result.output
        self.mock_vscode.assert_not_called()
        self.mock_create_pow_toml.assert_not_called()

    def test_flag_rejects_unsupported_version(self, mocker):
        self._no_pow_toml(mocker)

        result = self.runner.invoke(
            init_cmd, ["--sim-version", "9.9.9"], env={"NO_COLOR": "1", "TERM": "dumb"}
        )

        assert result.exit_code != 0
        self.mock_download.assert_not_called()

    def test_existing_pow_toml_version_wins_over_default(self, mocker):
        """Keeping an existing pow.toml installs the version it declares."""
        mocker.patch(
            "pathlib.Path.exists",
            side_effect=lambda p, *a, **kw: str(p) in ("pyproject.toml", "pow.toml"),
            autospec=True,
        )
        mocker.patch("pow_cli.core.initializer.Initializer.read_config")
        mocker.patch(
            "pow_cli.core.models.pow_config.PowConfig.get",
            side_effect=lambda key, default=None, profile="default": {
                "version": "5.1.0", "enable_ros": False,
            }.get(key, default),
        )

        result = self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})

        assert result.exit_code == 0
        self.mock_prompt.assert_not_called()
        assert self.mock_download.call_args.kwargs["version"] == "5.1.0"

    @pytest.mark.parametrize(
        "config_version", [PowConfig.SUPPORTED_ISAACSIM_VERSIONS[-1], "9.9.9"]
    )
    def test_updating_existing_config_can_change_the_version(self, mocker, config_version):
        pow_toml = Path("pow.toml")
        original = (
            '# project settings\n[sim]\n'
            f'version = "{config_version}" # selected release\n'
            'enable_ros = false\n'
            'isaacsim_ros_ws = "~/IsaacSim-ros_workspaces"\n'
            'exts = ["my.custom.ext"]\n'
            '\n[[profiles]]\nname = "mine"\nheadless = true\n'
        )
        pow_toml.write_text(original)
        self.mock_confirm.side_effect = [True, False]
        selected_version = PowConfig.ISAACSIM_VERSION
        self.mock_prompt.return_value = selected_version
        mocker.stop(self.mock_create_pow_toml)
        mocker.patch("pow_cli.core.initializer.Initializer.init_git")

        result = self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})

        assert result.exit_code == 0, result.output
        self.mock_prompt.assert_called_once()
        assert self.mock_download.call_args.kwargs["version"] == selected_version
        assert self.mock_link.call_args.kwargs["version"] == selected_version
        assert self.mock_vscode.call_args.kwargs["version"] == selected_version
        assert pow_toml.read_text() == original.replace(
            f'version = "{config_version}"', f'version = "{selected_version}"'
        )

    def test_picker_is_used_when_nothing_else_specifies_a_version(self, mocker):
        self._no_pow_toml(mocker)
        mocker.patch.object(PowConfig, "installed_versions", return_value=["5.1.0"])
        self.mock_prompt.return_value = "5.1.0"

        result = self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})

        assert result.exit_code == 0
        choices = self.mock_prompt.call_args[0][1]
        # Latest first, annotated from data pow already has.
        assert choices == [("6.1.0", "latest"), ("5.1.0", "installed")]
        assert self.mock_prompt.call_args.kwargs["default"] == PowConfig.ISAACSIM_VERSION
        assert self.mock_download.call_args.kwargs["version"] == "5.1.0"

    def test_picker_marks_a_version_both_latest_and_installed(self, mocker):
        self._no_pow_toml(mocker)
        mocker.patch.object(PowConfig, "installed_versions", return_value=["6.1.0"])

        self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})

        assert self.mock_prompt.call_args[0][1] == [
            ("6.1.0", "latest, installed"),
            ("5.1.0", ""),
        ]

    def test_picker_only_lists_versions_built_for_the_host_architecture(self, mocker):
        self._no_pow_toml(mocker)
        mocker.patch.object(PowConfig, "installed_versions", return_value=[])
        arch_filter = mocker.patch.object(PowConfig, "versions_for_arch", return_value=("5.1.0",))

        self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})

        arch_filter.assert_called()
        assert self.mock_prompt.call_args[0][1] == [("5.1.0", "latest")]
        assert self.mock_prompt.call_args.kwargs["default"] == "5.1.0"


@pytest.mark.cli
class TestInitCmdFinalize:
    """Step 10 reports what it wrote to pow.toml, and fails loudly when it can't."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        self.runner = CliRunner()
        mocker.patch(
            "pow_cli.core.initializer.Initializer.download_isaacsim",
            return_value={"status": "Already installed", "path": "/tmp/isaacsim"},
        )
        mocker.patch("pow_cli.cli.init.ask_choice", return_value=PowConfig.ISAACSIM_VERSION)
        # Say yes to updating pow.toml, no to ROS.
        self.mock_confirm = mocker.patch(
            "pow_cli.cli.init.Confirm.ask", side_effect=[True, False]
        )
        mocker.patch("pow_cli.core.initializer.Initializer.read_config")
        mocker.patch("pow_cli.core.initializer.Initializer.create_global_folder",
                     return_value={"global_existed": True, "results": []})
        mocker.patch("pow_cli.core.initializer.Initializer.create_system_toml",
                     return_value={"status": "Existed", "path": "system.toml"})
        mocker.patch("pow_cli.core.initializer.Initializer.fix_asset_browser_cache",
                     return_value=False)
        mocker.patch("pow_cli.core.initializer.Initializer.setup_project_structure",
                     return_value={"results": []})
        self.mock_vscode = mocker.patch(
            "pow_cli.core.initializer.Initializer.setup_vscode_configs",
            return_value={"status": "Success", "results": [], "version": "6.1.0"},
        )
        mocker.patch("pow_cli.core.initializer.Initializer.setup_omniverse_user_home_alias",
                     return_value={"status": "unchanged", "path": "omniverse.toml"})
        mocker.patch("pow_cli.core.initializer.Initializer.link_managed_isaacsim",
                     return_value={"status": "Existed", "path": "_isaacsim"})
        mocker.patch("time.sleep")
        # An existing pow.toml, so step 2 asks whether to update it.
        mocker.patch(
            "pathlib.Path.exists",
            side_effect=lambda path_obj, *a, **kw: str(path_obj) in
            ("pyproject.toml", "pow.toml"),
            autospec=True,
        )
        self.mock_create_pow_toml = mocker.patch(
            "pow_cli.core.initializer.Initializer.create_pow_toml"
        )

    def _run(self):
        return self.runner.invoke(init_cmd, env={"NO_COLOR": "1", "TERM": "dumb"})

    def test_step2_promises_a_merge_not_a_replacement(self):
        self.mock_create_pow_toml.return_value = {
            "status": "Updated", "path": "pow.toml", "changed": {},
        }

        result = self._run()

        # Confirm.ask is mocked, so check the question it was asked with.
        assert "Update settings in existing pow.toml?" in self.mock_confirm.call_args_list[0][0][0]
        assert "Will update only version, enable_ros and isaacsim_ros_ws." in result.output
        assert "Your other settings and comments are kept." in result.output

    def test_updated_lists_the_settings_that_moved(self):
        self.mock_create_pow_toml.return_value = {
            "status": "Updated",
            "path": "pow.toml",
            "changed": {
                "version": ("5.1.0", "6.1.0"),
                "enable_ros": (False, True),
                "isaacsim_ros_ws": (None, "~/ws"),
            },
        }

        result = self._run()

        assert result.exit_code == 0
        assert "Updated pow.toml" in result.output
        assert "version: 5.1.0 → 6.1.0" in result.output
        # Booleans read the way pow.toml spells them, not the way Python does.
        assert "enable_ros: false → true" in result.output
        assert "isaacsim_ros_ws: unset → ~/ws" in result.output

    def test_unchanged_file_reads_as_a_no_op(self):
        self.mock_create_pow_toml.return_value = {
            "status": "Updated", "path": "pow.toml", "changed": {},
        }

        result = self._run()

        assert result.exit_code == 0
        assert "pow.toml already up to date" in result.output
        assert "Updated pow.toml" not in result.output

    def test_parse_error_marks_the_step_failed(self):
        self.mock_create_pow_toml.return_value = {
            "status": "Error",
            "path": "pow.toml",
            "message": "Unexpected character: 'x' at line 7 col 3",
        }

        result = self._run()

        assert result.exit_code == 1
        assert "[10/10] ❌ Finalizing:" in result.output
        assert "pow.toml could not be parsed" in result.output
        assert "at line 7 col 3" in result.output
        assert "Project initialized successfully" not in result.output

    def test_success_keeps_the_check_mark(self):
        self.mock_create_pow_toml.return_value = {
            "status": "Updated", "path": "pow.toml", "changed": {},
        }

        result = self._run()

        assert "[10/10] ✅ Finalizing:" in result.output
        assert "Project initialized successfully" in result.output
