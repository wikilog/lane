# Contributing

1. Keep `SKILL.md` under ~80 lines. Put CLI recipes in `references/dispatch.md`.
2. Classifier and gates live in `scripts/plan.py`. Do not restate them in prose.
3. Run `python3 scripts/test_plan.py` and `python3 scripts/test_refresh_models.py` before opening a PR.
4. Do not commit `~/.config/lane/config.json`, secrets, or `__pycache__`.
5. Point host skill roots and always-on rules at this clone with `scripts/install-links.sh`. Do not keep a second copy under `~/skills/library/lane`.
6. Unique run dirs only. Never `--run-dir current`. Pass `--cwd <project>` when invoking `run.py` from this repo.
7. Prompt delivery is file or stdin. Do not add command-substitution recipes to `dispatch.md`.
