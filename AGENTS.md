# Repository guidance

- Scientific configuration and evaluation code are lead-authored. Do not change model, dispatch, or evaluation assumptions without lead authorization.
- Keep `results.csv`, `suppression.csv`, existing plots, and historical script outputs unchanged. Never overwrite an existing run or rendered output.
- Write each new study into a fresh `research-runs/<run-id>` directory. Do not rerun a study already running or frozen.
- Render only from an existing captured `summary.csv`; do not import or rerun scientific scripts from the renderer.
- Treat all synthetic results as non-field-validated. Do not claim forecast weather availability, detector accuracy, or real-world performance without appropriate evidence.
- Do not add real-flight control or bundle/download datasets, processed footage, or model weights.

## Verification

- `.venv/bin/python -m unittest discover -v`
- `.venv/bin/python sweep.py --check`
- `.venv/bin/python suppression.py --check`
- `.venv/bin/python sensitivity.py --check`
- `.venv/bin/python render_study.py --help`
