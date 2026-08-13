## What and why

<!-- What changed, and what problem it solves. The diff already says what the
     code does; use this space for the reasoning a reviewer cannot reconstruct. -->

Closes #

## How it was verified

<!-- Be specific. "Tested locally" tells a reviewer nothing. Name the endpoint
     you called, the page you loaded, the input you used. If an endpoint has no
     automated coverage, exercise it against http://localhost:8000/docs and say
     what you checked. -->

- [ ] `cd backend && ruff check . && python -m compileall -q -x "venv|data" . && pytest && ruff format --check .`
- [ ] `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`

<!-- Stop the dev server before running the frontend build: they share .next
     and will corrupt each other. -->

## Screenshots

<!-- Required for any UI change. Before and after where it helps. -->

## Configuration

<!-- Delete this section if nothing here applies. -->

- **New environment variable:** name, default, and what happens when it is
  absent. A feature whose key is missing must switch off, not crash.
- **New dependency:** which requirements file and why. Anything imported at
  module scope belongs in `requirements-base.txt`; only large packages that can
  be imported lazily go in `requirements.txt`.
- **New migration:** the file under `supabase/migrations/`, and a note that it
  must be applied by hand.

## Notes for the reviewer

<!-- Anything you are unsure about, chose between, or deliberately left out. -->
