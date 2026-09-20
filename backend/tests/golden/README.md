# Golden tests — manual regeneration

The golden tests under `tests/golden/` compare the byte-for-byte SVG output of
`backend/app/domain/render.py::render_svg` against committed reference files.
There is **no `pytest --snapshot-update` plugin** in `pyproject.toml`; the
golden files are committed plain `.svg` artifacts.

## When to regenerate

Regenerate the goldens whenever you intentionally change the SVG renderer in a
way that produces a new correct output (layout, colour, attribute order,
diagnostic marker shape, etc.). The renderer is deterministic by design
(`f"{v:.2f}"` floats, fixed attribute order, sorted iteration), so a fresh
golden run is byte-exact and diffable.

## How to regenerate

The Renderer module exposes the rendering functions used by the tests; the
goldens themselves are produced by a small helper script:

```bash
# From repo root:
cd backend

# 1) Run the golden tests once to confirm the current goldens fail (or pass —
#    if they pass, no regeneration needed).

# 2) Regenerate every golden file by re-running the generator and committing
#    the new outputs. There is no Makefile target here by design — the
#    `update-golden` target at the repo root just prints this message.
DYLD_LIBRARY_PATH=/opt/homebrew/opt/cairo/lib uv run python -m tests.golden.regenerate

# 3) Visually diff the changed files (`git diff backend/tests/golden/`) and
#    commit them alongside the renderer change. Do NOT regenerate goldens as
#    part of an unrelated commit.
```

## Adding a new fixture

1. Drop the new fixture JSON under `backend/tests/fixtures/NN-name.json`.
2. Add the corresponding `.expected.json` (maxErrors / requiredDiagnosticCodes /
   forbiddenDiagnosticCodes per main spec §13.2).
3. Run the golden tests; the new fixture will fail with "golden not found".
4. If the layout is correct, commit the freshly generated `.svg` file under
   `backend/tests/golden/NN-name.svg`.
5. Update `backend/tests/golden/test_*.py` (or whichever test file the project
   uses) to enumerate the new fixture.

## CI gating

CI fails the build when a committed `.svg` does not match the renderer's
output for the matching fixture. If CI reports a golden mismatch after a
legitimate renderer change, follow the regeneration steps above; do **not**
relax the assertion or skip the test.