import shutil
import zipfile
from pathlib import Path

import click
import pytest

from pow_cli.core.initializer import Initializer
from pow_cli.core.models.pow_config import PowConfig


@pytest.fixture
def initializer(tmp_path, mocker):
    mocker.patch("platform.machine", return_value="x86_64")
    mocker.patch("platform.system", return_value="Linux")
    mocker.patch("distro.id", return_value="ubuntu")
    mocker.patch("distro.version", return_value="22.04")
    return Initializer(global_path=tmp_path / ".pow")


@pytest.fixture
def archive_download(tmp_path, mocker):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("isaac-sim.sh", "#!/bin/sh\n")
        bundle.writestr("isaac-sim.compatibility_check.sh", "#!/bin/sh\n")

    def retrieve(url, dest, reporthook):
        shutil.copyfile(archive, dest)
        reporthook(1, archive.stat().st_size, archive.stat().st_size)

    return mocker.patch("urllib.request.urlretrieve", side_effect=retrieve)


def test_architecture_check_failure(initializer, mocker):
    mocker.patch("platform.machine", return_value="arm64")
    with pytest.raises(RuntimeError, match="Unsupported architecture: arm64"):
        initializer.download_isaacsim()


def test_os_check_failure(initializer, mocker):
    mocker.patch("distro.version", return_value="20.04")
    mocker.patch("distro.name", return_value="Ubuntu")
    with pytest.raises(RuntimeError, match="Unsupported OS: Ubuntu 20.04"):
        initializer.download_isaacsim()


@pytest.mark.parametrize(
    "version,expected_host",
    [
        ("5.1.0", "https://download.isaacsim.omniverse.nvidia.com/"),
        ("6.1.0", "https://downloads.isaacsim.nvidia.com/"),
    ],
)
def test_download_extracts_required_scripts(initializer, archive_download, version, expected_host):
    result = initializer.download_isaacsim(version=version, check=True)

    assert result["status"] == "Downloaded and installed"
    assert result["version"] == version
    archive_download.assert_called_once()
    url, destination, _ = archive_download.call_args.args
    assert url == f"{expected_host}isaac-sim-standalone-{version}-linux-x86_64.zip"
    assert str(destination).endswith(".part")
    assert not Path(destination).exists()
    install = Path(result["path"])
    assert Initializer.isaacsim_ready(install, check=True)
    assert (install / "isaac-sim.sh").stat().st_mode & 0o111

    assert initializer.download_isaacsim(version=version)["status"] == "Already installed"
    archive_download.assert_called_once()


def test_unknown_version_is_rejected(initializer):
    with pytest.raises(click.ClickException, match="Unsupported Isaac Sim version"):
        initializer.download_isaacsim(version="9.9.9")


def test_incomplete_install_is_backed_up(initializer, archive_download):
    install = PowConfig.version_dir(PowConfig.ISAACSIM_VERSION, initializer.global_path)
    install.mkdir(parents=True)
    (install / "user.txt").write_text("original")

    result = initializer.download_isaacsim(check=True)

    assert Initializer.isaacsim_ready(install, check=True)
    assert (Path(result["backup"]) / "user.txt").read_text() == "original"
    assert PowConfig.installed_versions(initializer.global_path) == [PowConfig.ISAACSIM_VERSION]


@pytest.mark.parametrize("failure", ["download", "extraction", "validation", "post-install", "interrupt"])
def test_failed_repair_restores_original(initializer, archive_download, mocker, tmp_path, failure):
    install = PowConfig.version_dir(PowConfig.ISAACSIM_VERSION, initializer.global_path)
    install.mkdir(parents=True)
    original = {"isaac-sim.sh": "old launcher", "user.txt": "original"}
    for name, content in original.items():
        (install / name).write_text(content)

    error_type = RuntimeError
    if failure == "download":
        archive_download.side_effect = OSError("network failed")
    elif failure == "post-install":
        # Exercise the real extractor's post_install.sh failure cleanup.
        with zipfile.ZipFile(tmp_path / "source.zip", "a") as bundle:
            bundle.writestr("post_install.sh", "#!/bin/sh\n")
        mocker.patch("subprocess.run", side_effect=RuntimeError("post-install failed"))
    else:
        def extract(zip_path, target, *args):
            target.mkdir(parents=True)
            (target / "partial.txt").write_text("partial extraction")
            if failure == "interrupt":
                raise KeyboardInterrupt()
            if failure == "extraction":
                raise RuntimeError("extraction failed")
            # Returning without scripts also fails readiness validation.
        mocker.patch.object(initializer, "_extract_isaacsim_zip", side_effect=extract)
        if failure == "interrupt":
            error_type = KeyboardInterrupt

    with pytest.raises(error_type):
        initializer.download_isaacsim(check=True)

    assert {p.name: p.read_text() for p in install.iterdir()} == original
    backups = initializer.global_path / "isaacsim-backups"
    assert not backups.exists() or not list(backups.iterdir())


def test_repair_of_symlink_preserves_its_target(initializer, archive_download, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    (external / "user.txt").write_text("original")
    install = PowConfig.version_dir(PowConfig.ISAACSIM_VERSION, initializer.global_path)
    install.parent.mkdir(parents=True)
    install.symlink_to(external, target_is_directory=True)

    result = initializer.download_isaacsim()

    assert Initializer.isaacsim_ready(install)
    assert not install.is_symlink()
    assert Path(result["backup"]).resolve() == external
    assert (external / "user.txt").read_text() == "original"
