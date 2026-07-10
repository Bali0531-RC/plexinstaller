"""Bootstrap script contracts for distro dependency recovery."""

from pathlib import Path

SCRIPT = (Path(__file__).parents[1] / "web2/public/setup.sh").read_text()


def test_bootstrap_probes_real_pip_enabled_venv():
    assert 'python3 -m venv "$probe_dir/venv"' in SCRIPT
    assert '"$probe_dir/venv/bin/python" -m pip --version' in SCRIPT


def test_bootstrap_installs_exact_debian_python_venv_then_falls_back():
    exact = 'apt-get install -y "python${python_series}-venv"'
    fallback = "apt-get install -y python3-venv"

    assert exact in SCRIPT
    assert fallback in SCRIPT
    assert SCRIPT.index(exact) < SCRIPT.index(fallback)


def test_bootstrap_rechecks_venv_after_package_install():
    assert SCRIPT.count("if ! venv_available; then") == 2
    assert "install_venv_support || exit 1" in SCRIPT


def test_bootstrap_removes_partial_staging_venv_before_final_creation():
    remove = 'rm -rf "${STAGING_DIR}/.venv"'
    create = 'python3 -m venv "${STAGING_DIR}/.venv"'

    assert remove in SCRIPT
    assert create in SCRIPT
    assert SCRIPT.index(remove) < SCRIPT.index(create)
