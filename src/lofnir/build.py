import contextlib
import re
import subprocess
import tomllib
from collections.abc import Generator
from pathlib import Path

import typer

from lofnir.install import _find_git_root, _find_workspaces


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]", "-", name).lower()


def _read_name_version(pyproject_path: Path) -> tuple[str, str]:
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    project = data.get("project", {})
    return project.get("name", ""), project.get("version", "0.0.0")


def _local_workspace_sources(pyproject_path: Path, all_workspaces: dict[str, Path]) -> dict[str, Path]:
    """Return {dep_pkg_name: workspace_path} for uv.sources path entries that resolve to a known workspace."""
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    result: dict[str, Path] = {}
    for pkg_name, source in sources.items():
        if "path" not in source:
            continue
        resolved = (pyproject_path.parent / source["path"]).resolve()
        for ws_path in all_workspaces.values():
            if resolved == ws_path.resolve():
                result[pkg_name] = ws_path
                break
    return result


def _topo_sort(targets: dict[str, Path], all_workspaces: dict[str, Path]) -> list[str]:
    """Return target workspace names in dependency-first order. Raises ValueError on cycles."""
    pkg_to_ws: dict[str, str] = {}
    for ws_name, ws_path in all_workspaces.items():
        pyproject = ws_path / "pyproject.toml"
        if pyproject.exists():
            pkg_name, _ = _read_name_version(pyproject)
            pkg_to_ws[_normalize(pkg_name)] = ws_name

    dep_graph: dict[str, set[str]] = {}
    for ws_name, ws_path in targets.items():
        pyproject = ws_path / "pyproject.toml"
        if not pyproject.exists():
            dep_graph[ws_name] = set()
            continue
        local_srcs = _local_workspace_sources(pyproject, all_workspaces)
        deps: set[str] = set()
        for dep_pkg in local_srcs:
            ws = pkg_to_ws.get(_normalize(dep_pkg))
            if ws and ws in targets:
                deps.add(ws)
        dep_graph[ws_name] = deps

    order: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"Circular dependency detected involving workspace '{name}'")
        if name in visited:
            return
        visiting.add(name)
        for dep in dep_graph.get(name, set()):
            visit(dep)
        visiting.discard(name)
        visited.add(name)
        order.append(name)

    for name in targets:
        visit(name)

    return order


def _replace_source_entry(content: str, pkg_name: str, wheel_path: Path) -> str:
    """Replace the { … } block for pkg_name in [tool.uv.sources] with a wheel path reference."""
    pattern = re.compile(r"^(" + re.escape(pkg_name) + r"\s*=\s*)\{[^}]*\}", re.MULTILINE)
    return pattern.sub(r'\1{ path = "' + str(wheel_path) + r'" }', content)


def _pin_dep_version(content: str, pkg_name: str, version: str) -> str:
    """Replace any version specifier for pkg_name in dependencies with an exact ==version pin."""
    parts = re.split(r"[-_.]", pkg_name)
    name_pat = r"[-_.]".join(re.escape(p) for p in parts)
    pattern = re.compile(r'"(' + name_pat + r')[^"]*"', re.IGNORECASE)
    return pattern.sub(f'"{pkg_name}=={version}"', content)


@contextlib.contextmanager
def _patched_pyproject(
    pyproject_path: Path,
    patches: dict[str, tuple[str, Path]],
) -> Generator[None]:
    """Temporarily patch pyproject.toml and uv.lock for building with pinned local deps.

    patches: {dep_pkg_name: (dep_version, wheel_path)}
    Restores both files unconditionally on exit, even if an error occurs.
    """
    original_toml = pyproject_path.read_text()
    uv_lock = pyproject_path.parent / "uv.lock"
    original_lock: str | None = uv_lock.read_text() if uv_lock.exists() else None

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        content = original_toml
        for dep_pkg, (dep_version, wheel_path) in patches.items():
            sources = data.get("tool", {}).get("uv", {}).get("sources", {})
            if dep_pkg in sources and "path" in sources[dep_pkg]:
                content = _replace_source_entry(content, dep_pkg, wheel_path)
            content = _pin_dep_version(content, dep_pkg, dep_version)

        pyproject_path.write_text(content)

        result = subprocess.run(["uv", "lock"], cwd=pyproject_path.parent, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"uv lock failed after patching {pyproject_path.name}")

        yield
    finally:
        pyproject_path.write_text(original_toml)
        if original_lock is not None:
            uv_lock.write_text(original_lock)
        elif uv_lock.exists():
            uv_lock.unlink()


def _uv_build(project_dir: Path, out_dir: Path) -> tuple[int, list[Path]]:
    before = set(out_dir.glob("*.whl"))
    result = subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out_dir)], cwd=project_dir)
    after = set(out_dir.glob("*.whl"))
    return result.returncode, sorted(after - before)


def run_build(
    workspace: str | None,
    out_dir: Path | None = None,
    cwd: Path | None = None,
) -> int:
    """Return 0 on success, 1 on any error."""
    cwd = cwd or Path.cwd()

    if not (cwd / "pyproject.toml").exists():
        git_root = _find_git_root(cwd)
        if git_root is None:
            typer.echo("Error: not in a git repository and no pyproject.toml found.", err=True)
            return 1
    else:
        git_root = _find_git_root(cwd) or cwd

    all_workspaces = _find_workspaces(git_root)
    if not all_workspaces:
        typer.echo("Error: no projects found in the repository.", err=True)
        return 1

    resolved_out = out_dir or (git_root / "dist")
    resolved_out.mkdir(parents=True, exist_ok=True)

    if workspace is not None:
        name = workspace.lstrip(":")
        if name not in all_workspaces:
            available = "  ".join(f":{k}" for k in sorted(all_workspaces))
            typer.echo(f"Error: workspace '{name}' not found.\nAvailable: {available}", err=True)
            return 1
        targets: dict[str, Path] = {name: all_workspaces[name]}
    else:
        targets = all_workspaces

    try:
        build_order = _topo_sort(targets, all_workspaces)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        return 1

    built: dict[str, tuple[str, Path]] = {}  # normalized_pkg_name -> (version, wheel_path)
    failed: list[str] = []

    for ws_name in build_order:
        ws_path = targets[ws_name]
        pyproject_path = ws_path / "pyproject.toml"

        if not pyproject_path.exists():
            typer.echo(f"Skipping {ws_name}: no pyproject.toml.")
            continue

        local_srcs = _local_workspace_sources(pyproject_path, all_workspaces)
        patches: dict[str, tuple[str, Path]] = {}
        for dep_pkg in local_srcs:
            entry = built.get(_normalize(dep_pkg))
            if entry:
                patches[dep_pkg] = entry

        typer.echo(f"Building {ws_name} ({ws_path})...")
        if patches:
            pins = ", ".join(f"{k}=={v}" for k, (v, _) in patches.items())
            typer.echo(f"  Pinning local deps: {pins}")

        try:
            if patches:
                with _patched_pyproject(pyproject_path, patches):
                    code, wheels = _uv_build(ws_path, resolved_out)
            else:
                code, wheels = _uv_build(ws_path, resolved_out)
        except Exception as exc:
            typer.echo(f"  Error: {exc}", err=True)
            failed.append(ws_name)
            continue

        if code != 0:
            failed.append(ws_name)
            continue

        pkg_name, version = _read_name_version(pyproject_path)
        if wheels:
            built[_normalize(pkg_name)] = (version, wheels[0])
            typer.echo(f"  -> {wheels[0].name}")

    if failed:
        typer.echo(f"Error: build failed for: {', '.join(failed)}", err=True)
        return 1
    return 0
