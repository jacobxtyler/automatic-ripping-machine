# Repository Guidelines

## Project Structure & Module Organization

ARM is a Python application for automated optical disc ripping. Core application code lives in `arm/`: ripping logic is under `arm/ripper/`, Flask UI code under `arm/ui/`, configuration helpers under `arm/config/`, SQLAlchemy models under `arm/models/`, and Alembic migrations under `arm/migrations/`. Unit tests live in `test/unittest/` and follow the module area they exercise, such as `test_ripper_ARMInfo.py`. Operational files are grouped by purpose: `scripts/` for install, Docker, and wrapper scripts; `setup/` for service, udev, and sample config files; `devtools/` for local contributor utilities; `docs/` and `arm_wiki/` for documentation.

## Build, Test, and Development Commands

- `python -m pip install -r requirements.txt`: install Python dependencies, including the `arm-dependencies` submodule requirements.
- `flake8 . --max-complexity=15 --max-line-length=120 --show-source --statistics`: run the same lint command used by CI.
- `python3 -m unittest discover -s test/unittest -p 'test_*.py' -v`: run the repository unit tests.
- `python3 devtools/armdevtools.py -qa`: run development-tool quality checks against `arm/`, `test/`, and `devtools/`.
- `docker build -t arm-local .`: build the Docker image when changing runtime packaging or system dependencies.

## Coding Style & Naming Conventions

Use Python 3.9 through 3.12 compatible code. Follow existing Python style: 4-space indentation, descriptive snake_case functions and variables, PascalCase classes, and module names that match their feature area. CI enforces flake8 with 120-character lines; `setup.cfg` also excludes migrations from standard flake8 checks. Keep logging compatible with the configured pylint preference for `{}`-style formatting, and avoid broad exception handling unless the surrounding code already requires it.

## Testing Guidelines

Tests use the standard `unittest` framework with `unittest.mock` for external commands, files, and system state. Add tests under `test/unittest/` with filenames beginning `test_` and test methods beginning `test_`. Prefer focused tests around ripping decisions, utility behavior, configuration parsing, and UI-adjacent logic that can run without real optical drives or external services.

## Commit & Pull Request Guidelines

Recent history uses short imperative messages and tagged fixes such as `[BUGFIX] Fix makemkv job progress (#1736)`. Keep commits scoped to one concern. The project PR template expects a summary, linked issue, change type, test evidence, checklist completion, changelog notes, and relevant logs. Update `README.md`, `docs/`, or `arm_wiki/` when behavior, setup, or user-facing configuration changes.

## Security & Configuration Tips

Do not commit local secrets, API keys, media paths, or machine-specific config. Use `setup/arm.yaml` and `setup/apprise.yaml` as examples, and keep runtime overrides outside the repository.
