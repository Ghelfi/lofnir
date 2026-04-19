from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from .conftest import PYPROJECT_WITH_SOURCE, make_project, make_project_with_dep, runner

from lofnir.build import (
    _local_workspace_sources,
    _normalize,
    _patched_pyproject,
    _pin_dep_version,
    _read_name_version,
    _replace_source_entry,
    _topo_sort,
    _uv_build,
    run_build,
)
from lofnir.cli import app


def test__normalize__hyphens_underscores_dots() -> None:
    assert _normalize("my-pkg") == "my-pkg"
    assert _normalize("my_pkg") == "my-pkg"
    assert _normalize("my.pkg") == "my-pkg"
    assert _normalize("My-Pkg") == "my-pkg"


def test__read_name_version__happy_path(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\nversion = "1.2.3"\n')
    assert _read_name_version(tmp_path / "pyproject.toml") == ("foo", "1.2.3")


def test__read_name_version__missing_fields(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    name, version = _read_name_version(tmp_path / "pyproject.toml")
    assert name == ""
    assert version == "0.0.0"


def test__local_workspace_sources__finds_path_dep(tmp_path: Path) -> None:
    dep = make_project(tmp_path, "dep-pkg")
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        PYPROJECT_WITH_SOURCE.format(name="consumer", version="0.1.0", dep_name="dep-pkg", dep_path="../dep-pkg")
    )
    all_ws = {"dep-pkg": dep, "consumer": consumer}
    result = _local_workspace_sources(consumer / "pyproject.toml", all_ws)
    assert result == {"dep-pkg": dep}


def test__local_workspace_sources__ignores_non_path_source(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        '[project]\nname = "consumer"\nversion = "0.1.0"\n'
        '[tool.uv.sources]\nexternal = { git = "https://github.com/foo/bar" }\n'
    )
    result = _local_workspace_sources(consumer / "pyproject.toml", {})
    assert result == {}


def test__local_workspace_sources__ignores_path_not_in_workspaces(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (consumer / "pyproject.toml").write_text(
        PYPROJECT_WITH_SOURCE.format(name="consumer", version="0.1.0", dep_name="other", dep_path="../other")
    )
    # other is not in all_workspaces
    result = _local_workspace_sources(consumer / "pyproject.toml", {})
    assert result == {}


def test__topo_sort__independent_workspaces(tmp_path: Path) -> None:
    a = make_project(tmp_path, "alpha")
    b = make_project(tmp_path, "beta")
    ws = {"alpha": a, "beta": b}
    order = _topo_sort(ws, ws)
    assert set(order) == {"alpha", "beta"}


def test__topo_sort__dependency_comes_first(tmp_path: Path) -> None:
    dep = make_project(tmp_path, "dep")
    consumer = make_project_with_dep(tmp_path, "consumer", dep, "dep")
    ws = {"dep": dep, "consumer": consumer}
    order = _topo_sort(ws, ws)
    assert order.index("dep") < order.index("consumer")


def test__topo_sort__detects_cycle(tmp_path: Path) -> None:
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    (a / "pyproject.toml").write_text(
        PYPROJECT_WITH_SOURCE.format(name="alpha", version="0.1.0", dep_name="beta", dep_path="../beta")
    )
    (b / "pyproject.toml").write_text(
        PYPROJECT_WITH_SOURCE.format(name="beta", version="0.1.0", dep_name="alpha", dep_path="../alpha")
    )
    ws = {"alpha": a, "beta": b}
    with pytest.raises(ValueError, match="Circular"):
        _topo_sort(ws, ws)


def test__topo_sort__specific_workspace_only(tmp_path: Path) -> None:
    dep = make_project(tmp_path, "dep")
    consumer = make_project_with_dep(tmp_path, "consumer", dep, "dep")
    unrelated = make_project(tmp_path, "unrelated")
    all_ws = {"dep": dep, "consumer": consumer, "unrelated": unrelated}
    order = _topo_sort({"consumer": consumer}, all_ws)
    assert order == ["consumer"]


def test__replace_source_entry__replaces_path_and_editable(tmp_path: Path) -> None:
    content = 'dep-pkg = { path = "../dep-pkg", editable = true }\n'
    wheel = tmp_path / "dep_pkg-1.0.0-py3-none-any.whl"
    result = _replace_source_entry(content, "dep-pkg", wheel)
    assert f'dep-pkg = {{ path = "{wheel}" }}' in result
    assert "editable" not in result


def test__replace_source_entry__replaces_path_without_editable(tmp_path: Path) -> None:
    content = 'dep-pkg = { path = "../dep-pkg" }\n'
    wheel = tmp_path / "dep_pkg-1.0.0-py3-none-any.whl"
    result = _replace_source_entry(content, "dep-pkg", wheel)
    assert f'dep-pkg = {{ path = "{wheel}" }}' in result


def test__replace_source_entry__only_replaces_matching_key(tmp_path: Path) -> None:
    content = 'other = { path = "../other" }\ndep-pkg = { path = "../dep-pkg" }\n'
    wheel = tmp_path / "dep_pkg-1.0.0-py3-none-any.whl"
    result = _replace_source_entry(content, "dep-pkg", wheel)
    assert 'other = { path = "../other" }' in result


def test__pin_dep_version__no_specifier() -> None:
    content = 'dependencies = ["dep-pkg"]\n'
    result = _pin_dep_version(content, "dep-pkg", "1.2.3")
    assert '"dep-pkg==1.2.3"' in result


def test__pin_dep_version__existing_specifier() -> None:
    content = 'dependencies = ["dep-pkg>=0.1.0"]\n'
    result = _pin_dep_version(content, "dep-pkg", "1.2.3")
    assert '"dep-pkg==1.2.3"' in result
    assert ">=" not in result


def test__pin_dep_version__underscore_variant() -> None:
    content = 'dependencies = ["dep_pkg"]\n'
    result = _pin_dep_version(content, "dep-pkg", "1.2.3")
    assert '"dep-pkg==1.2.3"' in result


def test__patched_pyproject__patches_and_restores(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    uv_lock = tmp_path / "uv.lock"
    original_content = PYPROJECT_WITH_SOURCE.format(
        name="consumer", version="0.1.0", dep_name="dep-pkg", dep_path="../dep-pkg"
    )
    pyproject.write_text(original_content)
    uv_lock.write_text("original lock")

    wheel = tmp_path / "dep_pkg-1.0.0-py3-none-any.whl"
    wheel.touch()

    with (
        patch("lofnir.build.subprocess.run", return_value=MagicMock(returncode=0)),
        _patched_pyproject(pyproject, {"dep-pkg": ("1.0.0", wheel)}),
    ):
        patched = pyproject.read_text()
        assert str(wheel) in patched
        assert '"dep-pkg==1.0.0"' in patched

    assert pyproject.read_text() == original_content
    assert uv_lock.read_text() == "original lock"


def test__patched_pyproject__restores_on_exception(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    original_content = PYPROJECT_WITH_SOURCE.format(
        name="consumer", version="0.1.0", dep_name="dep-pkg", dep_path="../dep-pkg"
    )
    pyproject.write_text(original_content)
    wheel = tmp_path / "dep_pkg-1.0.0-py3-none-any.whl"
    wheel.touch()

    with (
        patch("lofnir.build.subprocess.run", return_value=MagicMock(returncode=0)),
        pytest.raises(RuntimeError),
        _patched_pyproject(pyproject, {"dep-pkg": ("1.0.0", wheel)}),
    ):
        raise RuntimeError("simulated failure")

    assert pyproject.read_text() == original_content


def test__patched_pyproject__raises_on_lock_failure(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        PYPROJECT_WITH_SOURCE.format(name="consumer", version="0.1.0", dep_name="dep-pkg", dep_path="../dep-pkg")
    )
    wheel = tmp_path / "dep_pkg-1.0.0-py3-none-any.whl"
    wheel.touch()

    with (
        patch("lofnir.build.subprocess.run", return_value=MagicMock(returncode=1)),
        pytest.raises(RuntimeError, match="uv lock failed"),
        _patched_pyproject(pyproject, {"dep-pkg": ("1.0.0", wheel)}),
    ):
        pass  # pragma: no cover

    assert pyproject.read_text() == PYPROJECT_WITH_SOURCE.format(
        name="consumer", version="0.1.0", dep_name="dep-pkg", dep_path="../dep-pkg"
    )


def test__patched_pyproject__removes_lock_if_none_existed(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        PYPROJECT_WITH_SOURCE.format(name="consumer", version="0.1.0", dep_name="dep-pkg", dep_path="../dep-pkg")
    )
    uv_lock = tmp_path / "uv.lock"
    wheel = tmp_path / "dep_pkg-1.0.0-py3-none-any.whl"
    wheel.touch()

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if cmd[1] == "lock":
            uv_lock.write_text("new lock")
        return MagicMock(returncode=0)

    with (
        patch("lofnir.build.subprocess.run", side_effect=fake_run),
        _patched_pyproject(pyproject, {"dep-pkg": ("1.0.0", wheel)}),
    ):
        pass

    assert not uv_lock.exists()


def test__uv_build__returns_new_wheels(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    new_wheel = out_dir / "mypkg-1.0.0-py3-none-any.whl"

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        new_wheel.touch()
        return MagicMock(returncode=0)

    with patch("lofnir.build.subprocess.run", side_effect=fake_run):
        code, wheels = _uv_build(tmp_path, out_dir)

    assert code == 0
    assert wheels == [new_wheel]


def test__uv_build__does_not_return_preexisting_wheels(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    existing = out_dir / "old-1.0.0-py3-none-any.whl"
    existing.touch()

    with patch("lofnir.build.subprocess.run", return_value=MagicMock(returncode=0)):
        _, wheels = _uv_build(tmp_path, out_dir)

    assert wheels == []


def test__run_build__single_project(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    proj = make_project(tmp_path, "myapp")
    out = tmp_path / "dist"

    with patch("lofnir.build._uv_build", return_value=(0, [])) as mock_build:
        assert run_build(None, out_dir=out, cwd=proj) == 0
    mock_build.assert_called_once_with(proj, out)


def test__run_build__no_git_no_pyproject(tmp_path: Path) -> None:
    assert run_build(None, cwd=tmp_path) == 1


def test__run_build__unknown_workspace(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    make_project(tmp_path, "alpha")
    out = tmp_path / "dist"
    assert run_build(":unknown", out_dir=out, cwd=tmp_path) == 1


def test__run_build__multi_workspace_correct_order(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    dep = make_project(tmp_path, "dep")
    consumer = make_project_with_dep(tmp_path, "consumer", dep, "dep")
    out = tmp_path / "dist"
    call_order: list[Path] = []

    def fake_build(project_dir: Path, out_dir: Path) -> tuple[int, list[Path]]:
        call_order.append(project_dir)
        wheel = out_dir / f"{project_dir.name}-0.1.0-py3-none-any.whl"
        wheel.parent.mkdir(parents=True, exist_ok=True)
        wheel.touch()
        return 0, [wheel]

    with (
        patch("lofnir.build._uv_build", side_effect=fake_build),
        patch("lofnir.build.subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        assert run_build(None, out_dir=out, cwd=tmp_path) == 0

    assert call_order.index(dep) < call_order.index(consumer)


def test__run_build__patches_local_dep(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    dep = make_project(tmp_path, "dep", version="1.2.0")
    consumer = make_project_with_dep(tmp_path, "consumer", dep, "dep")
    out = tmp_path / "dist"
    out.mkdir()

    dep_wheel = out / "dep-1.2.0-py3-none-any.whl"
    dep_wheel.touch()

    build_calls: list[Path] = []

    def fake_build(project_dir: Path, out_dir: Path) -> tuple[int, list[Path]]:
        build_calls.append(project_dir)
        if project_dir == dep:
            return 0, [dep_wheel]
        return 0, []

    with (
        patch("lofnir.build._uv_build", side_effect=fake_build),
        patch("lofnir.build.subprocess.run", return_value=MagicMock(returncode=0)) as mock_lock,
    ):
        assert run_build(None, out_dir=out, cwd=tmp_path) == 0

    # uv lock should have been called for consumer (the patched one)
    lock_calls = [c for c in mock_lock.call_args_list if c.args[0][:2] == ["uv", "lock"]]
    assert len(lock_calls) == 1

    # consumer's pyproject should be restored to original after build
    consumer_toml = (consumer / "pyproject.toml").read_text()
    assert "../dep" in consumer_toml
    assert "dep==1.2.0" not in consumer_toml


def test__run_build__build_failure(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    make_project(tmp_path, "alpha")
    make_project(tmp_path, "beta")
    out = tmp_path / "dist"

    def fail_alpha(project_dir: Path, out_dir: Path) -> tuple[int, list[Path]]:
        return (1, []) if project_dir.name == "alpha" else (0, [])

    with patch("lofnir.build._uv_build", side_effect=fail_alpha):
        assert run_build(None, out_dir=out, cwd=tmp_path) == 1


def test__run_build__cycle_error(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    (a / "pyproject.toml").write_text(
        PYPROJECT_WITH_SOURCE.format(name="alpha", version="0.1.0", dep_name="beta", dep_path="../beta")
    )
    (b / "pyproject.toml").write_text(
        PYPROJECT_WITH_SOURCE.format(name="beta", version="0.1.0", dep_name="alpha", dep_path="../alpha")
    )
    out = tmp_path / "dist"
    assert run_build(None, out_dir=out, cwd=tmp_path) == 1


def test__run_build__creates_out_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    proj = make_project(tmp_path, "myapp")
    out = tmp_path / "nested" / "dist"

    with patch("lofnir.build._uv_build", return_value=(0, [])):
        run_build(None, out_dir=out, cwd=proj)

    assert out.exists()


def test__run_build__specific_workspace(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    alpha = make_project(tmp_path, "alpha")
    make_project(tmp_path, "beta")
    out = tmp_path / "dist"

    with patch("lofnir.build._uv_build", return_value=(0, [])) as mock_build:
        assert run_build(":alpha", out_dir=out, cwd=tmp_path) == 0
    mock_build.assert_called_once_with(alpha, out)


def test__cli_build__help() -> None:
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "uv build" in result.output


def test__cli_build__success(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    make_project(tmp_path, "myapp")
    with (
        patch("lofnir.build._find_git_root", return_value=tmp_path),
        patch("lofnir.build._uv_build", return_value=(0, [])),
    ):
        result = runner.invoke(app, ["build"])
    assert result.exit_code == 0


def test__cli_build__with_out_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    make_project(tmp_path, "myapp")
    out = tmp_path / "custom-dist"

    with (
        patch("lofnir.build._find_git_root", return_value=tmp_path),
        patch("lofnir.build._uv_build", return_value=(0, [])) as mock_build,
    ):
        result = runner.invoke(app, ["build", "--out-dir", str(out)])

    assert result.exit_code == 0
    mock_build.assert_called_once_with(tmp_path / "myapp", out)
