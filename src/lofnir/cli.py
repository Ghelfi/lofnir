import typer

app = typer.Typer(
    name="lofnir",
    help="Python project lifecycle tool — install, fmt, lint, typecheck, build, test.",
    no_args_is_help=True,
)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def install(ctx: typer.Context) -> None:
    """Install project dependencies via uv sync.

    Optionally target a specific workspace: lofnir install :my_workspace

    When run inside a project directory (has pyproject.toml + uv.lock), installs
    that project. When run from a git repo root without a pyproject.toml, discovers
    and installs all sub-workspaces.

    Any extra arguments are forwarded to uv sync (e.g. --frozen, --no-dev).
    --all-extras is always passed unless already specified.
    """
    from lofnir.install import run_install

    args = ctx.args
    # First non-option arg (doesn't start with -) is the workspace selector.
    workspace: str | None = None
    if args and not args[0].startswith("-"):
        workspace = args[0]
        args = args[1:]

    raise typer.Exit(run_install(workspace, extra_args=args))


@app.command()
def fmt() -> None:
    """Format source code with ruff."""
    typer.echo("fmt: not yet implemented")


@app.command()
def lint() -> None:
    """Lint source code with ruff."""
    typer.echo("lint: not yet implemented")


@app.command()
def typecheck() -> None:
    """Run type checking with mypy."""
    typer.echo("typecheck: not yet implemented")


@app.command()
def build() -> None:
    """Build the project with uv."""
    typer.echo("build: not yet implemented")


@app.command()
def test() -> None:
    """Run tests with pytest."""
    typer.echo("test: not yet implemented")


if __name__ == "__main__":
    app()
