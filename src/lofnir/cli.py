import typer

app = typer.Typer(
    name="lofnir",
    help="Python project lifecycle tool — install, fmt, lint, typecheck, build, test.",
    no_args_is_help=True,
)


@app.command()
def install() -> None:
    """Install project dependencies."""
    typer.echo("install: not yet implemented")


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
