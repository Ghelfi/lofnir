import subprocess
import tomllib
from pathlib import Path

import typer

_SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", "dist", "build"}


def _is_uv_project(pyproject_path: Path) -> bool:
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    has_tool_uv = bool(data.get("tool", {}).get("uv"))
    has_lock = (pyproject_path.parent / "uv.lock").exists()
    return has_tool_uv or has_lock


def _find_git_root(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _find_workspaces(root: Path) -> dict[str, Path]:
    workspaces: dict[str, Path] = {}
    for pyproject in sorted(root.rglob("pyproject.toml")):
        if any(part in _SKIP_DIRS for part in pyproject.parts):
            continue
        project_dir = pyproject.parent
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        name: str = data.get("project", {}).get("name") or project_dir.name
        workspaces[name] = project_dir
    return workspaces


def _uv_sync(project_dir: Path, extra_args: list[str]) -> int:
    # Do a copy to avoid modifying the original list
    args = list(extra_args)
    if "--all-extras" not in args:
        args.append("--all-extras")
    return subprocess.run(["uv", "sync", *args], cwd=project_dir).returncode


def run_install(workspace: str | None, extra_args: list[str] | None = None, cwd: Path | None = None) -> int:
    """Return 0 on success, 1 on any error."""
    cwd = cwd or Path.cwd()
    args = extra_args if extra_args is not None else []
    pyproject = cwd / "pyproject.toml"

    if pyproject.exists():
        if not _is_uv_project(pyproject):
            typer.echo(
                "Error: pyproject.toml found but this does not appear to be a uv-managed project.\n"
                "Hint: add a [tool.uv] section or run `uv lock` to initialise it.",
                err=True,
            )
            return 1
        uv_lock = cwd / "uv.lock"
        if not uv_lock.exists():
            typer.echo(
                "Error: uv.lock not found. Run `uv lock` first to generate it.",
                err=True,
            )
            return 1
        typer.echo(f"Installing {cwd.name}...")
        return _uv_sync(cwd, args)

    git_root = _find_git_root(cwd)
    if git_root is None:
        typer.echo(
            "Error: no pyproject.toml in current directory and not inside a git repository.",
            err=True,
        )
        return 1

    workspaces = _find_workspaces(git_root)
    if not workspaces:
        typer.echo("Error: no projects found in the repository.", err=True)
        return 1

    if workspace is not None:
        name = workspace.lstrip(":")
        if name not in workspaces:
            available = "  ".join(f":{k}" for k in sorted(workspaces))
            typer.echo(
                f"Error: workspace '{name}' not found.\nAvailable: {available}",
                err=True,
            )
            return 1
        targets: dict[str, Path] = {name: workspaces[name]}
    else:
        targets = workspaces

    failed: list[str] = []
    for name, path in targets.items():
        if not (path / "uv.lock").exists():
            typer.echo(f"Skipping {name}: no uv.lock (run `uv lock` inside {path}).")
            continue
        typer.echo(f"Installing {name} ({path})...")
        if _uv_sync(path, args) != 0:
            failed.append(name)

    if failed:
        typer.echo(f"Error: install failed for: {', '.join(failed)}", err=True)
        return 1
    return 0
