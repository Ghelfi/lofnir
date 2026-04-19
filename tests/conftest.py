from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()

MINIMAL_PYPROJECT = """\
[project]
name = "myapp"
version = "0.1.0"
"""

UV_PYPROJECT = """\
[project]
name = "myapp"
version = "0.1.0"

[tool.uv]
dev-dependencies = []
"""

PYPROJECT = """\
[project]
name = "{name}"
version = "{version}"
dependencies = [{deps}]

[tool.uv]
dev-dependencies = []
"""

PYPROJECT_WITH_SOURCE = """\
[project]
name = "{name}"
version = "{version}"
dependencies = ["{dep_name}"]

[tool.uv]
dev-dependencies = []

[tool.uv.sources]
{dep_name} = {{ path = "{dep_path}", editable = true }}
"""


def make_project(root: Path, name: str, version: str = "0.1.0", *, with_lock: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "pyproject.toml").write_text(PYPROJECT.format(name=name, version=version, deps=""))
    if with_lock:
        (d / "uv.lock").touch()
    return d


def make_project_with_dep(root: Path, name: str, dep_path: Path, dep_name: str, version: str = "0.1.0") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    rel = Path("..") / dep_path.name
    (d / "pyproject.toml").write_text(
        PYPROJECT_WITH_SOURCE.format(name=name, version=version, dep_name=dep_name, dep_path=str(rel))
    )
    (d / "uv.lock").touch()
    return d
