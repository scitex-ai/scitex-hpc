import pytest

from scitex_hpc.scheduler import load_profile


@pytest.fixture
def profile_path(tmp_path):
    path = tmp_path / "hpc.yaml"
    path.write_text(
        "host: legacy\npartition: legacy_partition\nprofiles:\n  test:\n    host: example\n    scheduler: grid-engine\n    dialect: tsubame\n    account: billing\n    bundle:\n      resource_type: cpu_example\n      cpus: 4\n      memory_mib: 8192\n"
    )
    return path


def test_named_profile_resolves_explicit_backend_and_bundle(profile_path):
    # Arrange
    name = "test"
    # Act
    profile = load_profile(name, path=profile_path)
    # Assert
    assert (profile.host, profile.bundle.resource_type) == ("example", "cpu_example")


def test_missing_profile_is_not_silently_inferred(profile_path):
    # Arrange
    name = "missing"
    # Act
    resolve = load_profile
    # Assert
    with pytest.raises(ValueError, match="No scheduler profile"):
        resolve(name, path=profile_path)


def test_profile_typo_is_not_silently_ignored(tmp_path):
    # Arrange
    path = tmp_path / "hpc.yaml"
    path.write_text(
        "profiles:\n  test:\n    host: example\n    scheduler: slurm\n    typo: wrong\n"
    )
    # Act
    resolve = load_profile
    # Assert
    with pytest.raises(TypeError):
        resolve("test", path=path)
