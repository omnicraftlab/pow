"""CPU-only regression coverage for the Isaac Sim 6.1.0 integration boundary."""
import json
from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from pow_cli.core.models.pow_config import PowConfig
from pow_cli.core.initializer import Initializer
from pow_cli.core.ros_manager import RosManager
from pow_cli.core.linter import _asset_version_of
from pow_cli.cli.init import _resolve_sim_version


@pytest.fixture
def project(tmp_path, monkeypatch, reset_config_singleton):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pow.toml").write_text('[sim]\nversion = "5.1.0"\nenable_ros = false\n')
    return tmp_path


def test_release_and_installed_fallback(tmp_path):
    assert PowConfig.ISAACSIM_VERSION == "6.1.0"
    assert PowConfig.release("6.1.0")["url"] == "https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.1.0-linux-x86_64.zip"
    for version in ("5.1.0", "6.0.1", "6.1.0"):
        install = PowConfig.version_dir(version, tmp_path)
        install.mkdir(parents=True)
        (install / "isaac-sim.sh").touch()
        assert PowConfig.resolve_installed_version(tmp_path) == version


def test_version_precedence(mocker):
    mocker.patch.object(PowConfig, "configured_default_version", return_value="6.0.1")
    picker = mocker.patch("pow_cli.cli.init.ask_choice", return_value="6.0.1")
    assert _resolve_sim_version("6.1.0", "5.1.0") == "6.1.0"
    assert _resolve_sim_version(None, "5.1.0") == "5.1.0"
    picker.assert_not_called()
    assert _resolve_sim_version(None, None) == "6.0.1"
    assert picker.call_args.kwargs["default"] == "6.0.1"


def test_switch_preserves_config_and_is_idempotent(project):
    config = project / "pow.toml"
    config.write_text('# custom\n[sim]\nversion = "5.1.0" # selected\nextensions = ["my.ext"]\n[[profiles]]\nname = "custom"\n')
    init = Initializer()
    assert init.config.get("version") == "5.1.0"
    target = PowConfig.version_dir("6.1.0", init.config.global_path)
    target.mkdir(parents=True)
    init.link_managed_isaacsim("6.1.0")
    assert (project / "_isaacsim").resolve() == target
    init._patch_pow_toml(config, False, sim_version="6.1.0")
    saved = config.read_text()
    assert '# custom' in saved and '# selected' in saved and 'my.ext' in saved and '[[profiles]]' in saved
    assert init._patch_pow_toml(config, False, sim_version="6.1.0") == {}
    assert config.read_text() == saved
    assert init.link_managed_isaacsim("6.1.0")["status"] == "Existed"


@pytest.mark.parametrize("version,namespace", [("5.1.0", "5.1"), ("6.0.1", "6.0"), ("6.1.0", "6.1"), ("7.0.0", "")])
def test_verified_asset_mapping(version, namespace):
    assert _asset_version_of(version) == namespace


def test_workspace_mismatch_never_mutates(mocker, tmp_path):
    run = mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="old-commit\n"))
    with pytest.raises(click.ClickException, match="separate directory"):
        RosManager.validate_workspace(tmp_path, "6.1.0")
    assert run.call_count == 1
    assert run.call_args.args[0][-2:] == ["rev-parse", "HEAD"]


def test_workspace_tag_with_user_edits_is_preserved(mocker, tmp_path):
    modified = tmp_path / "user.txt"
    modified.write_text("user changes")
    mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=PowConfig.release("6.1.0")["ros_ws_commit"] + "\n"))
    RosManager.validate_workspace(tmp_path, "6.1.0")
    assert modified.read_text() == "user changes"


@pytest.mark.parametrize("label", [None, "6.0.1", "6.1.0"])
def test_image_provenance(mocker, label):
    mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps([{"Config": {"Labels": {RosManager._SIM_LABEL: label}}}])))
    if label == "6.1.0":
        RosManager.validate_image("pow_simros_jazzy", "6.1.0")
    else:
        with pytest.raises(click.ClickException, match="Nothing was removed"):
            RosManager.validate_image("pow_simros_jazzy", "6.1.0")


def test_optional_distribution_must_match_selected_version(project, mocker):
    dist = mocker.Mock(version="5.1.0.0")
    mocker.patch("importlib.metadata.distribution", return_value=dist)
    assert Initializer().get_isaacsim_path("6.1.0") is None
    dist.locate_file.assert_not_called()


def test_6_1_0_asset_set_info_unset_preserves_assets(project, monkeypatch):
    from pow_cli.core.asset_manager import AssetManager
    monkeypatch.setattr(AssetManager, "OMNIVERSE_TOML_PATH", project / "omniverse.toml")
    (project / "pow.toml").write_text('[sim]\nversion = "6.1.0"\n')
    assets = project / "local-assets"
    assets.mkdir()
    sentinel = assets / "user.usda"
    sentinel.write_text("user asset")
    manager = AssetManager()
    assert manager.set_local_asset_path(str(assets)) == str(assets)
    assert manager.get_local_asset_path() == str(assets)
    assert manager.get_assets_symlink_path().resolve() == assets
    assert manager.get_kit_path() == PowConfig.version_dir("6.1.0", manager.global_dir) / "apps/isaacsim.exp.base.kit"
    manager.unset_local_asset_path()
    assert not manager.get_assets_symlink_path().exists()
    assert manager.get_local_asset_path() == ""
    assert sentinel.read_text() == "user asset"


def test_asset_set_existing_symlink_suggests_asset_unset(project, monkeypatch):
    from pow_cli.core.asset_manager import AssetError, AssetManager

    monkeypatch.setattr(
        AssetManager, "OMNIVERSE_TOML_PATH", project / "omniverse.toml"
    )
    assets = project / "local-assets"
    assets.mkdir()
    manager = AssetManager()
    manager.global_dir.mkdir(parents=True, exist_ok=True)
    manager.get_assets_symlink_path().symlink_to(assets, target_is_directory=True)

    with pytest.raises(AssetError, match="pow asset unset") as error:
        manager.set_local_asset_path(str(assets))

    assert "Remove it manually" not in str(error.value)


@pytest.mark.parametrize("version", ["5.1.0", "6.0.1", "6.1.0"])
def test_selected_python_launcher(project, mocker, version):
    from pow_cli.core.runner import Runner
    (project / "pow.toml").write_text(f'[sim]\nversion = "{version}"\nenable_ros = false\n')
    install = PowConfig.version_dir(version, PowConfig().global_path)
    install.mkdir(parents=True)
    (install / "python.sh").touch()
    run = mocker.patch("subprocess.run")
    Runner.run_python(extra_args=["script.py", "--arg", "value with spaces"])
    assert run.call_args.args[0] == [str(install / "python.sh"), "script.py", "--arg", "value with spaces"]


@pytest.mark.parametrize("returncode,stdout", [(1, ""), (0, "invalid json"), (0, "[]")])
def test_image_inspect_failure_is_actionable(mocker, returncode, stdout):
    mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=returncode, stdout=stdout, stderr="daemon unavailable"))
    with pytest.raises(click.ClickException, match="Could not inspect"):
        RosManager.validate_image("image", "6.1.0")


def test_clone_6_1_0_uses_official_ref(project, mocker):
    cfg = PowConfig()
    ws = project / "new-workspace"
    run = mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=PowConfig.release("6.1.0")["ros_ws_commit"]))
    RosManager(cfg).setup_ros_workspace(ws_path=ws, sim_version="6.1.0")
    assert next(c.args[0] for c in run.call_args_list if c.args[0][:2] == ["git", "clone"]) == ["git", "clone", "-b", "IsaacSim-6.1.0", "--quiet", "https://github.com/isaac-sim/IsaacSim-ros_workspaces.git", str(ws)]


def test_new_project_records_6_1_0(project, mocker):
    (project / "pow.toml").unlink()
    mocker.patch.object(Initializer, "init_git")
    result = Initializer().create_pow_toml()
    assert result["status"] == "Created"
    assert 'version = "6.1.0"' in (project / "pow.toml").read_text()


@pytest.mark.parametrize("label,mount,accepted", [("6.1.0", True, True), ("6.0.1", True, False), ("6.1.0", False, False)])
def test_running_container_compatibility(project, mocker, label, mount, accepted):
    cfg = PowConfig()
    mocker.patch.object(cfg, "get", return_value="6.1.0")
    mocker.patch.object(RosManager, "_load_and_validate_config", return_value=(cfg, "image"))
    mocker.patch.object(RosManager, "_is_container_running", return_value=True)
    attach = mocker.patch.object(RosManager, "_attach_to_container")
    data = [{"Config": {"Labels": {RosManager._SIM_LABEL: label}}, "Mounts": [
        {"Source": str((cfg.ros_ws_path / "jazzy_ws").resolve()) if mount else "/other", "Destination": "/jazzy_ws"}
    ]}]
    mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(data)))
    if accepted:
        RosManager.run_simros_container()
        attach.assert_called_once()
    else:
        with pytest.raises(click.ClickException, match="incompatible or unverified"):
            RosManager.run_simros_container()
        attach.assert_not_called()
