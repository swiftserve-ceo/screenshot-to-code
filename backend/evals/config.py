"""Eval-tooling paths. Reads from the typed settings; tests may still
``monkeypatch.setattr(evals.config, "EVALS_DIR", ...)``.
"""

from config import settings

EVALS_DIR = settings.evals_dir
