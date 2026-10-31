"""RAGnoz CLI, split into stage-based submodules: demo, golden, pipeline (import/eval/run/compare),
diagnosis (diagnose/triage/report), experiment (ablate/experiment run). Each submodule registers its
commands on the shared `app`/`demo_cli`/`golden_cli`/`experiment_cli` Typer instances from `_shared`
as an import side effect.
"""

from __future__ import annotations

import importlib

from ragnoz.cli._shared import app

# Imported in this exact order so commands register (and so appear in --help) in the same
# sequence the original single-file cli.py defined them: demo, golden, then the rest.
# `architecture` (inspect/architecture approve) is new in Faz 3 and registers last.
for _module_name in ("demo", "golden", "pipeline", "diagnosis", "experiment", "architecture"):
    importlib.import_module(f"ragnoz.cli.{_module_name}")

__all__ = ["app"]

if __name__ == "__main__":
    app()
