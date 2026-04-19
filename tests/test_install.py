from pathlib import Path
from unittest.mock import call, patch

from .conftest import MINIMAL_PYPROJECT, UV_PYPROJECT, make_project, runner

from lofnir.cli import app
from lofnir.install import _find_git_root, _find_workspaces, _is_uv_project, _uv_sync, run_install


def test__is_uv_project__via_tool_uv(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT)
    assert _is_uv_project(tmp_path / "pyproject.toml") is True


def test__is_uv_project__via_lock_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
    (tmp_path / "uv.lock").touch()
    assert _is_uv_project(tmp_path / "pyproject.toml") is True


def test__is_uv_project__false(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
    assert _is_uv_project(tmp_path / "pyproject.toml") is False


def test__find_git_root__direct(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert _find_git_root(tmp_path) == tmp_path


def test__find_git_root__nested(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert _find_git_root(nested) == tmp_path


def test__find_git_root__none(tmp_path: Path) -> None:
    assert _find_git_root(tmp_path) is None


def test__find_workspaces__single(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
    ws = _find_workspaces(tmp_path)
    assert "myapp" in ws
    assert ws["myapp"] == tmp_path


def test__find_workspaces__multiple(tmp_path: Path) -> None:
    for name in ("alpha", "beta"):
        d = tmp_path / name
        d.mkdir()
        (d / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
    ws = _find_workspaces(tmp_path)
    assert set(ws) == {"alpha", "beta"}


def test__find_workspaces__skips_venv(tmp_path: Path) -> None:
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
    ws = _find_workspaces(tmp_path)
    assert not ws


def test__find_workspaces__fallback_name(tmp_path: Path) -> None:
    sub = tmp_path / "mydir"
    sub.mkdir()
    (sub / "pyproject.toml").write_text("[build-system]\nrequires=[]\n")
    ws = _find_workspaces(tmp_path)
    assert "mydir" in ws


def test__uv_sync__adds_all_extras_by_default(tmp_path: Path) -> None:
    with patch("lofnir.install.subprocess.run", return_value=type("R", (), {"returncode": 0})()) as mock_run:
        _uv_sync(tmp_path, [])
    cmd = mock_run.call_args[0][0]
    assert "--all-extras" in cmd


def test__uv_sync__does_not_duplicate_all_extras(tmp_path: Path) -> None:
    with patch("lofnir.install.subprocess.run", return_value=type("R", (), {"returncode": 0})()) as mock_run:
        _uv_sync(tmp_path, ["--all-extras"])
    cmd = mock_run.call_args[0][0]
    assert cmd.count("--all-extras") == 1


def test__uv_sync__forwards_extra_args(tmp_path: Path) -> None:
    with patch("lofnir.install.subprocess.run", return_value=type("R", (), {"returncode": 0})()) as mock_run:
        _uv_sync(tmp_path, ["--frozen", "--no-dev"])
    cmd = mock_run.call_args[0][0]
    assert "--frozen" in cmd
    assert "--no-dev" in cmd
    assert "--all-extras" in cmd


def test__run_install__single_project_success(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT)
    (tmp_path / "uv.lock").touch()

    with patch("lofnir.install._uv_sync", return_value=0) as mock_sync:
        assert run_install(None, cwd=tmp_path) == 0
        mock_sync.assert_called_once_with(tmp_path, [])


def test__run_install__single_project_uv_sync_failure(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT)
    (tmp_path / "uv.lock").touch()

    with patch("lofnir.install._uv_sync", return_value=1):
        assert run_install(None, cwd=tmp_path) == 1


def test__run_install__not_uv_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
    assert run_install(None, cwd=tmp_path) == 1


def test__run_install__missing_lock_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT)
    assert run_install(None, cwd=tmp_path) == 1


def test__run_install__extra_args_forwarded(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT)
    (tmp_path / "uv.lock").touch()

    with patch("lofnir.install._uv_sync", return_value=0) as mock_sync:
        assert run_install(None, extra_args=["--frozen", "--no-dev"], cwd=tmp_path) == 0
        mock_sync.assert_called_once_with(tmp_path, ["--frozen", "--no-dev"])


def test__run_install__all_workspaces(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    alpha = make_project(tmp_path, "alpha")
    beta = make_project(tmp_path, "beta")

    with patch("lofnir.install._uv_sync", return_value=0) as mock_sync:
        assert run_install(None, cwd=tmp_path) == 0
    assert mock_sync.call_count == 2
    mock_sync.assert_any_call(alpha, [])
    mock_sync.assert_any_call(beta, [])


def test__run_install__specific_workspace(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    alpha = make_project(tmp_path, "alpha")
    make_project(tmp_path, "beta")

    with patch("lofnir.install._uv_sync", return_value=0) as mock_sync:
        assert run_install(":alpha", cwd=tmp_path) == 0
    mock_sync.assert_called_once_with(alpha, [])


def test__run_install__specific_workspace_without_colon(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    alpha = make_project(tmp_path, "alpha")

    with patch("lofnir.install._uv_sync", return_value=0) as mock_sync:
        assert run_install("alpha", cwd=tmp_path) == 0
    mock_sync.assert_called_once_with(alpha, [])


def test__run_install__unknown_workspace(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    make_project(tmp_path, "alpha")
    assert run_install(":unknown", cwd=tmp_path) == 1


def test__run_install__no_pyproject_no_git(tmp_path: Path) -> None:
    assert run_install(None, cwd=tmp_path) == 1


def test__run_install__skips_workspace_without_lock(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    make_project(tmp_path, "alpha", with_lock=False)
    make_project(tmp_path, "beta", with_lock=True)

    with patch("lofnir.install._uv_sync", return_value=0) as mock_sync:
        assert run_install(None, cwd=tmp_path) == 0
    mock_sync.assert_called_once()


def test__run_install__partial_failure(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    make_project(tmp_path, "alpha")
    make_project(tmp_path, "beta")

    def fail_alpha(path: Path, _: list[str]) -> int:
        return 1 if path.name == "alpha" else 0

    with patch("lofnir.install._uv_sync", side_effect=fail_alpha):
        assert run_install(None, cwd=tmp_path) == 1


def test__run_install__extra_args_forwarded_to_all_workspaces(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    alpha = make_project(tmp_path, "alpha")
    beta = make_project(tmp_path, "beta")

    with patch("lofnir.install._uv_sync", return_value=0) as mock_sync:
        assert run_install(None, extra_args=["--frozen"], cwd=tmp_path) == 0
    mock_sync.assert_has_calls([call(alpha, ["--frozen"]), call(beta, ["--frozen"])], any_order=True)


def test__cli_install__help() -> None:
    result = runner.invoke(app, ["install", "--help"])
    assert result.exit_code == 0
    assert "uv sync" in result.output


def test__cli_install__not_uv_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
    with patch("lofnir.install.Path.cwd", return_value=tmp_path):
        result = runner.invoke(app, ["install"])
    assert result.exit_code == 1
    assert "uv-managed" in result.output


def test__cli_install__success(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT)
    (tmp_path / "uv.lock").touch()
    with patch("lofnir.install.Path.cwd", return_value=tmp_path), patch("lofnir.install._uv_sync", return_value=0):
        result = runner.invoke(app, ["install"])
    assert result.exit_code == 0
    assert "Installing" in result.output


def test__cli_install__extra_args_forwarded(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT)
    (tmp_path / "uv.lock").touch()
    with (
        patch("lofnir.install.Path.cwd", return_value=tmp_path),
        patch("lofnir.install._uv_sync", return_value=0) as mock_sync,
    ):
        result = runner.invoke(app, ["install", "--frozen", "--no-dev"])
    assert result.exit_code == 0
    mock_sync.assert_called_once_with(tmp_path, ["--frozen", "--no-dev"])
