# lofnir

A code lifecycle tool for Python projects — install, format, lint, typecheck, build, and test from a single CLI.

## Installation

```bash
uv tool install lofnir
```

## Usage

```
lofnir <command> [options]
```

### `install`

Installs project dependencies using `uv sync`.

**Single project** — run from a directory that contains a `pyproject.toml`:

```bash
lofnir install
```

Requirements:
- `pyproject.toml` must be present.
- The project must be uv-managed (has a `[tool.uv]` section or a `uv.lock` file).
- `uv.lock` must exist (run `uv lock` first if it doesn't).

**Multi-workspace** — run from a git repository root (or any subdirectory) without a local `pyproject.toml`. lofnir will discover all sub-projects and install them all:

```bash
lofnir install
```

To install a single workspace by name:

```bash
lofnir install :my_workspace
```

### Coming soon

| Command      | Description                        |
|--------------|------------------------------------|
| `fmt`        | Format source code with ruff       |
| `lint`       | Lint source code with ruff         |
| `typecheck`  | Type-check with mypy               |
| `build`      | Build with uv                      |
| `test`       | Run tests with pytest              |

## Configuration

lofnir reads configuration from your project's `pyproject.toml`. Default tool settings ship with lofnir so you get sensible defaults with zero configuration.

## Requirements

- Python >= 3.11
- [uv](https://github.com/astral-sh/uv) installed and on `PATH`
