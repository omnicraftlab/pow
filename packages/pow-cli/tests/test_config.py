import click
import pytest
from pow_cli.core.models.pow_config import PowConfig

def test_singleton(tmp_path, monkeypatch, reset_config_singleton):
    """Test that PowConfig is a singleton."""
    root = tmp_path / "project"
    root.mkdir()
    pow_toml = root / "pow.toml"
    pow_toml.write_text("[sim]\nversion='5.1.0'")
    monkeypatch.chdir(root)
    
    c1 = PowConfig()
    c2 = PowConfig()
    assert c1 is c2

def test_find_project_root(tmp_path, monkeypatch, reset_config_singleton):
    """Test finding the project root with pow.toml using template structure."""
    root = tmp_path / "project"
    root.mkdir()
    pow_toml = root / "pow.toml"
    
    # Matching pow.template.toml structure
    content = """
[sim]
version = "5.1.0"
ext_folders = ["./exts"]
"""
    pow_toml.write_text(content)
    
    subdir = root / "subdir"
    subdir.mkdir()
    
    monkeypatch.chdir(subdir)
    
    config = PowConfig()
    assert config.project_root == root
    assert config.get("version") == "5.1.0"
    assert config.get("ext_folders") == ["./exts"]

def test_config_profile_merging(tmp_path, monkeypatch, reset_config_singleton):
    """Test the profile merging logic."""
    root = tmp_path / "project"
    root.mkdir()
    pow_toml = root / "pow.toml"
    
    # Data by pow.template.toml
    content = """
[sim]
version = "5.1.0"
headless = false
enable_ros = false

[[profiles]]
name = "perf"
headless = true
custom_val = "perf_mode"
"""
    pow_toml.write_text(content)
    monkeypatch.chdir(root)
    
    config = PowConfig()
    
    # 1. Base default profile (maps to 'sim')
    assert config.get("version") == "5.1.0"
    assert config.get("headless") is False
    assert config.get("enable_ros") is False 
    
    # 2. 'perf' profile merges [sim] + 'perf' profile
    # - headless: from 'perf' (True) overrides [sim] (False)
    # - version: from [sim] (5.1.0)
    perf_profile = config.get_profile("perf")
    assert perf_profile["headless"] is True
    assert perf_profile["enable_ros"] is False
    assert perf_profile["version"] == "5.1.0"
    assert perf_profile["custom_val"] == "perf_mode"
    
    # Test through get() helper
    assert config.get("headless", profile="perf") is True
    assert config.get("enable_ros", profile="perf") is False

def test_no_config_found(tmp_path, monkeypatch, reset_config_singleton):
    """Test behavior when no pow.toml is found."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    
    config = PowConfig()
    # instantiation should succeed to allow access to global paths
    assert config.global_dir_name == ".pow"

    # but accessing project data should raise the error
    with pytest.raises(RuntimeError, match="Project not initialized: pow.toml not found"):
        _ = config.data

def test_global_dir_name_default(tmp_path, monkeypatch, reset_config_singleton):
    """Test global_dir_name defaults to .pow when no pyproject.toml exists."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    config = PowConfig()
    assert config.global_dir_name == ".pow"

def test_global_dir_name_custom(tmp_path, monkeypatch, reset_config_singleton):
    """Test global_dir_name reads from pyproject.toml."""
    root = tmp_path / "project"
    root.mkdir()
    pyproject = root / "pyproject.toml"
    pyproject.write_text('[tool.pow-cli]\nglobal_dir_name = ".custom_pow"')
    monkeypatch.chdir(root)
    config = PowConfig()
    assert config.global_dir_name == ".custom_pow"

# ── extends feature tests ──────────────────────────────────────────────────────

def _make_config(tmp_path, monkeypatch, reset_config_singleton_fixture, content: str) -> PowConfig:
    """Helper: write pow.toml, chdir, and return a fresh PowConfig."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    reset_config_singleton_fixture  # already applied via fixture
    return PowConfig()


def test_profile_extends_another_profile(tmp_path, monkeypatch, reset_config_singleton):
    """A profile can extend another named profile (yolo → centerpose)."""
    content = """
[sim]
version = "5.1.0"
headless = false
exts = ["isaacsim.code_editor.vscode"]

[[profiles]]
name = "yolo"
headless = true
exts = ["oc.proj.yolo"]

[[profiles]]
name = "centerpose"
extends = "yolo"
cpu_performance_mode = true
exts.add = ["oc.proj.centerpose"]
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    profile = config.get_profile("centerpose")
    # Inherits headless=true from yolo
    assert profile["headless"] is True
    # version comes from [sim] via yolo (yolo has no extends → extends [sim])
    assert profile["version"] == "5.1.0"
    # cpu_performance_mode set in centerpose
    assert profile["cpu_performance_mode"] is True
    # exts: yolo's list + centerpose's .add list
    assert profile["exts"] == ["oc.proj.yolo", "oc.proj.centerpose"]


def test_profile_extends_default_explicit(tmp_path, monkeypatch, reset_config_singleton):
    """extends = 'default' falls back to [sim]."""
    content = """
[sim]
headless = false
exts = ["base_ext"]

[[profiles]]
name = "myprofile"
extends = "default"
headless = true
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    profile = config.get_profile("myprofile")
    assert profile["headless"] is True
    assert profile["exts"] == ["base_ext"]


def test_profile_no_extends_defaults_to_sim(tmp_path, monkeypatch, reset_config_singleton):
    """A profile without 'extends' inherits from [sim] only."""
    content = """
[sim]
headless = false
exts = ["base_ext"]

[[profiles]]
name = "slim"
headless = true
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    profile = config.get_profile("slim")
    assert profile["headless"] is True
    assert profile["exts"] == ["base_ext"]


def test_profile_extends_add_appends_list(tmp_path, monkeypatch, reset_config_singleton):
    """exts.add appends to the inherited list from [sim]."""
    content = """
[sim]
exts = ["base_ext"]

[[profiles]]
name = "extra"
"exts.add" = ["added_ext"]
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    profile = config.get_profile("extra")
    assert profile["exts"] == ["base_ext", "added_ext"]


def test_profile_extends_add_on_non_list_raises(tmp_path, monkeypatch, reset_config_singleton):
    """exts.add targeting a non-list raises ClickException at resolution time."""
    import click as _click
    content = """
[sim]
headless = false

[[profiles]]
name = "bad"
"headless.add" = [true]
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    with pytest.raises(_click.ClickException, match="not a list"):
        config.get_profile("bad")


def test_profile_extends_unknown_target_raises(tmp_path, monkeypatch, reset_config_singleton):
    """extends pointing to a non-existent profile raises ClickException."""
    import click as _click
    content = """
[sim]
headless = false

[[profiles]]
name = "child"
extends = "ghost"
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    with pytest.raises(_click.ClickException, match="not found"):
        config.get_profile("child")


def test_profile_extends_circular_raises(tmp_path, monkeypatch, reset_config_singleton):
    """Circular extends (a→b→a) raises ClickException."""
    import click as _click
    content = """
[sim]
headless = false

[[profiles]]
name = "a"
extends = "b"

[[profiles]]
name = "b"
extends = "a"
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    with pytest.raises(_click.ClickException, match="[Cc]ircular"):
        config.get_profile("a")


# ── custom ROS image config tests ───────────────────────────────────────────────

def test_ros_defaults(tmp_path, monkeypatch, reset_config_singleton):
    """ros_dockerfile/ros_docker_image fall back to defaults when unset."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text("[sim]\nenable_ros = true\n")
    monkeypatch.chdir(root)
    config = PowConfig()

    assert config.ros_dockerfile == ""
    assert config.ros_docker_image == "pow_simros"
    assert config.ros_bridge == "jazzy"
    # No custom dockerfile → base image name; container name derived from it
    assert config.ros_image_name == f"pow_simros_{config.ros_distro}"
    assert config.ros_container_name == f"pow_simros_{config.ros_distro}"


def test_ros_custom_values(tmp_path, monkeypatch, reset_config_singleton):
    """ros_dockerfile/ros_docker_image are read from [sim]."""
    content = """
[sim]
enable_ros = true
ros_dockerfile = "docker/Dockerfile.simros"
ros_docker_image = "my_robot_sim"
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    assert config.ros_dockerfile == "docker/Dockerfile.simros"
    assert config.ros_docker_image == "my_robot_sim"
    # Custom dockerfile set → image name is the docker image name
    assert config.ros_image_name == "my_robot_sim"
    # Container name is derived from the image name
    assert config.ros_container_name == "my_robot_sim"


def test_ros_container_name_sanitizes_image_reference(
    tmp_path, monkeypatch, reset_config_singleton
):
    """Registry-style image references are sanitized into valid container names."""
    content = """
[sim]
enable_ros = true
ros_dockerfile = "docker/Dockerfile.simros"
ros_docker_image = "ghcr.io/acme/robot:v1"
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    assert config.ros_image_name == "ghcr.io/acme/robot:v1"
    assert config.ros_container_name == "ghcr.io_acme_robot_v1"


def test_ros_defaults_without_pow_toml(tmp_path, monkeypatch, reset_config_singleton):
    """ROS properties return defaults (no RuntimeError) when pow.toml is absent."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    config = PowConfig()

    assert config.ros_dockerfile == ""
    assert config.ros_docker_image == "pow_simros"
    assert config.ros_bridge == "jazzy"


def test_ros_bridge_reads_flag(tmp_path, monkeypatch, reset_config_singleton):
    """ros_bridge is read from [sim] and overridable per profile."""
    content = """
[sim]
enable_ros = true
ros_bridge = "humble"

[[profiles]]
name = "onjazzy"
extends = "default"
ros_bridge = "jazzy"
"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text(content)
    monkeypatch.chdir(root)
    config = PowConfig()

    assert config.ros_bridge == "humble"
    assert config.get_ros_bridge() == "humble"
    assert config.get_ros_bridge("onjazzy") == "jazzy"


def test_ros_bridge_invalid_raises(tmp_path, monkeypatch, reset_config_singleton):
    """An unsupported ros_bridge value fails fast with a ClickException."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "pow.toml").write_text('[sim]\nros_bridge = "iron"\n')
    monkeypatch.chdir(root)
    config = PowConfig()

    with pytest.raises(click.ClickException, match="Invalid ros_bridge"):
        _ = config.ros_bridge


# ── Isaac Sim version registry ──────────────────────────────────────────────────

def _install(base, version):
    d = base / "isaacsim" / version
    d.mkdir(parents=True)
    (d / "isaac-sim.sh").touch()
    return d


def test_supported_versions_are_ordered_latest_first():
    """The default, the picker and resolve_installed_version all take the head."""
    assert PowConfig.SUPPORTED_ISAACSIM_VERSIONS[0] == PowConfig.ISAACSIM_VERSION
    assert PowConfig.SUPPORTED_ISAACSIM_VERSIONS == ("6.1.0", "5.1.0")


def test_installed_versions_lists_latest_first(tmp_path):
    _install(tmp_path, "5.1.0")
    _install(tmp_path, "6.1.0")

    assert PowConfig.installed_versions(tmp_path) == ["6.1.0", "5.1.0"]


@pytest.mark.parametrize("arch", PowConfig.SUPPORTED_ARCHITECTURES)
def test_release_returns_metadata_for_supported_versions(arch):
    for version in PowConfig.SUPPORTED_ISAACSIM_VERSIONS:
        release = PowConfig.release(version, arch)
        assert release["url"].startswith("https://")
        assert release["url"].endswith(f"/{release['filename']}")
        assert release["filename"] == f"isaac-sim-standalone-{version}-linux-{arch}.zip"
        assert release["ros_ws_ref"] == f"IsaacSim-{version}"
        assert "downloads" not in release


def test_release_hosts_differ_per_version():
    """6.1.0 is served from a different host - the URL cannot be derived."""
    assert PowConfig.release("6.1.0", "x86_64")["url"].startswith(
        "https://downloads.isaacsim.nvidia.com/"
    )
    assert PowConfig.release("5.1.0", "x86_64")["url"].startswith(
        "https://download.isaacsim.omniverse.nvidia.com/"
    )


@pytest.mark.parametrize(
    "machine,arch",
    [("x86_64", "x86_64"), ("AMD64", "x86_64"), ("aarch64", "aarch64"), ("arm64", "aarch64"), ("ppc64le", "ppc64le")],
)
def test_host_arch_normalizes_machine_names(mocker, machine, arch):
    mocker.patch("platform.machine", return_value=machine)

    assert PowConfig.host_arch() == arch


def test_release_defaults_to_the_host_architecture(mocker):
    mocker.patch("platform.machine", return_value="aarch64")

    assert PowConfig.release("6.1.0")["url"] == (
        "https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.1.0-linux-aarch64.zip"
    )


def test_every_version_is_available_on_every_supported_architecture():
    for arch in PowConfig.SUPPORTED_ARCHITECTURES:
        assert PowConfig.versions_for_arch(arch) == PowConfig.SUPPORTED_ISAACSIM_VERSIONS


def test_unknown_architecture_has_no_builds():
    assert PowConfig.versions_for_arch("ppc64le") == ()
    with pytest.raises(click.ClickException, match="no linux-ppc64le build.*Available on ppc64le: none"):
        PowConfig.release("6.1.0", "ppc64le")


def test_release_without_a_build_for_the_arch_is_hidden_and_rejected(mocker):
    releases = {
        version: {**release, "downloads": dict(release["downloads"])}
        for version, release in PowConfig.ISAACSIM_RELEASES.items()
    }
    del releases["5.1.0"]["downloads"]["aarch64"]
    mocker.patch.object(PowConfig, "ISAACSIM_RELEASES", releases)

    assert PowConfig.versions_for_arch("aarch64") == ("6.1.0",)
    assert PowConfig.versions_for_arch("x86_64") == ("6.1.0", "5.1.0")
    with pytest.raises(click.ClickException, match="5.1.0 has no linux-aarch64 build. Available on aarch64: 6.1.0"):
        PowConfig.release("5.1.0", "aarch64")


def test_release_rejects_dropped_version():
    """6.0.1 is no longer installable, so there is no download URL for it."""
    with pytest.raises(click.ClickException, match="Unsupported Isaac Sim version '6.0.1'"):
        PowConfig.release("6.0.1")


@pytest.mark.parametrize("version", ["9.9.9", "", "5.1", "../5.1.0"])
def test_release_rejects_unknown_versions(version):
    with pytest.raises(click.ClickException, match="Unsupported Isaac Sim version"):
        PowConfig.release(version)


def test_version_dir_builds_path_under_global(tmp_path):
    assert PowConfig.version_dir("5.1.0", tmp_path) == tmp_path / "isaacsim" / "5.1.0"


def test_version_dir_allows_unregistered_but_well_formed_version(tmp_path):
    """A manually placed install must still be reachable via `pow sim -v`."""
    assert PowConfig.version_dir("5.0.0", tmp_path) == tmp_path / "isaacsim" / "5.0.0"


@pytest.mark.parametrize("version", ["..", "../../etc", "a/b", "/abs", "", ".hidden"])
def test_version_dir_rejects_path_traversal(version, tmp_path):
    with pytest.raises(click.ClickException, match="Invalid Isaac Sim version"):
        PowConfig.version_dir(version, tmp_path)


def test_installed_versions_ignores_incomplete_extractions(tmp_path):
    _install(tmp_path, "5.1.0")
    (tmp_path / "isaacsim" / "6.1.0").mkdir()  # no isaac-sim.sh

    assert PowConfig.installed_versions(tmp_path) == ["5.1.0"]


def test_resolve_installed_version_returns_sole_install(tmp_path):
    _install(tmp_path, "5.1.0")

    assert PowConfig.resolve_installed_version(tmp_path) == "5.1.0"


def test_resolve_installed_version_prefers_newest_known(tmp_path):
    _install(tmp_path, "6.1.0")
    _install(tmp_path, "5.1.0")

    assert PowConfig.resolve_installed_version(tmp_path) == "6.1.0"


def test_resolve_installed_version_falls_back_to_default(tmp_path):
    assert PowConfig.resolve_installed_version(tmp_path) == PowConfig.ISAACSIM_VERSION


# ── system.toml [sim] default_version ───────────────────────────────────────────

def test_configured_default_version_returns_pinned_value(tmp_path):
    (tmp_path / "system.toml").write_text('[sim]\ndefault_version = " 5.1.0 "\n')

    assert PowConfig.configured_default_version(tmp_path) == "5.1.0"


def test_configured_default_version_without_system_toml(tmp_path):
    assert PowConfig.configured_default_version(tmp_path) == ""


def test_configured_default_version_without_sim_section(tmp_path):
    (tmp_path / "system.toml").write_text('[asset]\nuse_local_asset = false\n')

    assert PowConfig.configured_default_version(tmp_path) == ""


def test_configured_default_version_ignores_malformed_toml(tmp_path):
    """A corrupt system.toml must never break `pow sim`."""
    (tmp_path / "system.toml").write_text("not = valid = toml\n")

    assert PowConfig.configured_default_version(tmp_path) == ""


def test_invalid_pow_toml_reports_a_plain_error(tmp_path, monkeypatch, reset_config_singleton):
    """A syntax error in pow.toml must read as an error, not a tomllib traceback."""
    (tmp_path / "pow.toml").write_text('[sim]\nversion = "6.1.0"\nbad = [\n')
    monkeypatch.chdir(tmp_path)

    with pytest.raises(click.ClickException, match="is not valid TOML"):
        PowConfig()
