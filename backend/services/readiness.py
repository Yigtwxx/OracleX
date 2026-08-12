"""
Startup readiness tracking.

The frontend holds its first paint until the backend reports itself ready, so
that a cold start shows one splash instead of a screen that assembles itself
panel by panel over half a minute.

This module only observes. `main.py` marks each step as it already runs it; the
startup sequence itself is unchanged, which keeps the two from drifting apart in
the way a duplicated startup list would.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Steps that must succeed before the app is usable at all. An optional step that
# fails degrades a feature — no news, no local model — but the screen still opens
# with everything else.
REQUIRED = True
OPTIONAL = False

# Ceiling on the whole warm-up, measured from process start. Past it the app
# reports itself ready regardless, so one hung dependency cannot keep the UI
# shut indefinitely.
DEADLINE_SECONDS = 60.0


@dataclass
class Step:
    """One startup task, and how it turned out."""

    key: str
    label: str
    required: bool
    state: str = "pending"  # pending | running | ok | failed
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None

    @property
    def settled(self) -> bool:
        """True once the step can no longer change the readiness verdict."""
        return self.state in ("ok", "failed")

    def as_dict(self) -> dict[str, Any]:
        duration_ms = None
        if self.started_at is not None and self.finished_at is not None:
            duration_ms = round((self.finished_at - self.started_at) * 1000)
        return {
            "key": self.key,
            "label": self.label,
            "required": self.required,
            "state": self.state,
            "duration_ms": duration_ms,
            "error": self.error,
        }


@dataclass
class Readiness:
    """The startup steps of one application process."""

    deadline_seconds: float = DEADLINE_SECONDS
    started_at: float = field(default_factory=time.monotonic)
    _steps: dict[str, Step] = field(default_factory=dict)

    # ── recording ───────────────────────────────────────────────────────────

    def register(self, key: str, label: str, required: bool) -> None:
        """Declare a step up front so it shows on the splash before it runs."""
        self._steps[key] = Step(key=key, label=label, required=required)

    def start(self, key: str) -> None:
        step = self._steps.get(key)
        if step is None:
            return
        step.state = "running"
        step.started_at = time.monotonic()

    def succeed(self, key: str) -> None:
        step = self._steps.get(key)
        if step is None:
            return
        step.state = "ok"
        step.finished_at = time.monotonic()
        step.error = None

    def fail(self, key: str, error: object) -> None:
        """Record a failure. The reason is trimmed to one short line for the UI."""
        step = self._steps.get(key)
        if step is None:
            return
        step.state = "failed"
        step.finished_at = time.monotonic()
        # A bare ConnectError stringifies to nothing, so the type is what
        # actually identifies the failure. Bounded because this reaches a
        # browser, and upstream errors can carry very long bodies.
        detail = " ".join(str(error).split())[:200]
        step.error = f"{type(error).__name__}: {detail}" if detail else type(error).__name__

    def reset(self) -> None:
        """Clear every step and restart the clock. For tests."""
        self._steps.clear()
        self.started_at = time.monotonic()

    # ── reporting ───────────────────────────────────────────────────────────

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def expired(self) -> bool:
        return self.elapsed >= self.deadline_seconds

    @property
    def ready(self) -> bool:
        """
        True when the UI can be shown: every required step has succeeded.

        Optional steps are reported but never gate, not even while running.
        They used to — the rule was "every optional step must have settled" —
        and measuring a real cold start showed what that cost: the news warm-up
        takes ~206s, so `ready` stayed false until the 60s deadline fired and
        opened the screen regardless, with news still running. The splash was
        pinned at a full minute and then revealed exactly the screen it could
        have shown at four seconds.

        So the wait bought nothing. Optional means optional: news, the heatmap
        and the local model fill in behind a screen that is already usable, the
        same way every other panel in this app loads. The deadline stays as the
        backstop for a required step that hangs.
        """
        steps = list(self._steps.values())
        if not steps:
            return False
        if self.expired:
            return True
        return all(s.state == "ok" for s in steps if s.required)

    @property
    def degraded(self) -> bool:
        """
        Ready, but something is actually wrong — the UI marks which step.

        An optional step that is merely still running is not a degradation, or
        every boot would report itself degraded for the minutes news takes. Only
        an outright failure counts, plus anything left unfinished when the
        deadline forced the screen open.
        """
        if not self.ready:
            return False
        steps = list(self._steps.values())
        if any(s.state == "failed" for s in steps):
            return True
        return self.expired and any(not s.settled for s in steps)

    @property
    def blocked(self) -> bool:
        """A required step failed outright: waiting longer will not help."""
        return any(s.required and s.state == "failed" for s in self._steps.values())

    def snapshot(self) -> dict[str, Any]:
        """The payload served to the frontend's boot gate."""
        return {
            "ready": self.ready,
            "degraded": self.degraded,
            "blocked": self.blocked,
            "elapsed_ms": round(self.elapsed * 1000),
            "deadline_ms": round(self.deadline_seconds * 1000),
            "steps": [step.as_dict() for step in self._steps.values()],
        }


# The process-wide instance. Steps are declared here rather than at the call
# sites so the splash can list everything that is coming before any of it starts.
readiness = Readiness()


def register_startup_steps() -> None:
    """Declare the startup steps, in the order the splash should show them."""
    readiness.reset()
    readiness.register("registry", "Varlık kaydı", REQUIRED)
    readiness.register("liquidations", "Likidasyon akışı", REQUIRED)
    readiness.register("news", "Haber akışı", OPTIONAL)
    readiness.register("heatmap", "Isı haritası", OPTIONAL)
    readiness.register("macro", "Makro panosu", OPTIONAL)
    readiness.register("ownership", "Varlık sahiplikleri", OPTIONAL)
    readiness.register("llm", "Yerel model", OPTIONAL)
    readiness.register("rag", "RAG embedding modeli", OPTIONAL)
