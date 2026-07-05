# Repository Guidelines

## Project Structure & Module Organization
This is a Python 3.10+ project for a Minecraft HoloQuiz helper. Core source code lives in `holoquiz/`, including GUI logic, bot runner behavior, configuration handling, OCR utilities, browser search, and quiz memory. Top-level launch shims are `holoquiz_gui.py` for the control panel and `holoquiz_bot.py` for non-GUI use. Tests live in `tests/`; image/OCR fixtures belong in `tests/fixtures/`. User configuration starts from `config.example.json`, while local runtime files such as `config.json` and `quiz_memory.json` should remain machine-specific.

## Build, Test, and Development Commands
- `python -m pip install -e ".[dev]"`: install the package locally with pytest.
- `python -m pytest`: run the full test suite.
- `python -m pytest tests/test_screen_phrase_watcher.py`: run a focused test file while working on OCR watcher behavior.
- `python holoquiz_gui.py`: launch the Tkinter GUI.
- `python holoquiz_bot.py`: run the bot without the GUI.
- `python -m py_compile holoquiz/*.py`: quick syntax check for package modules.

## Coding Style & Naming Conventions
Use 4-space indentation, type hints where practical, and small functions with clear side-effect boundaries. Follow Python naming conventions: `snake_case` for modules, functions, and variables; `PascalCase` for classes. Prefer dataclasses or typed dictionaries for structured state and config. Keep user-facing text short and specific. Preserve ASCII in source and docs unless the file already uses another character set or Minecraft/OCR text requires it.

## Testing Guidelines
Pytest is the test framework, configured in `pyproject.toml` with `tests/` as the test root. Name tests `test_<behavior>` and place them near the module or feature they cover, such as config persistence, GUI state, OCR normalization, or watcher matching. For OCR regressions, add small fixture images under `tests/fixtures/` and assert the normalized text, not only raw Tesseract output. Run `python -m pytest` before handing off code changes.

## Commit & Pull Request Guidelines
Recent commits use Conventional Commit-style subjects such as `feat: added GUI` and `fix: unable to search`; continue with short, imperative `feat:`, `fix:`, `test:`, or `docs:` subjects. Pull requests should explain the user-visible change, list config or dependency updates, and include test evidence. Add screenshots or short screen recordings for GUI changes, especially crop-selection and OCR-debug behavior.

## Security & Configuration Tips
Do not commit local `config.json`, `quiz_memory.json`, Minecraft logs, screenshots containing private data, or secrets. Keep dry-run enabled while testing chat automation. When adding new settings, update `config.example.json`, defaults in code, and any tests that cover config loading or persistence.
