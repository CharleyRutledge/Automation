"""Validate a new test trace against a stored PTAModel."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image

from .equivalence import AdaptiveThresholdCalibrator, TieredEquivalenceChecker
from .model import EssentialState, PTAModel


@dataclass
class StateMatch:
    essential: EssentialState
    matched_at: int       # index in the new trace
    matched_label: str
    distance: int         # phash hamming distance


@dataclass
class StateMiss:
    essential: EssentialState
    reason: str


@dataclass
class ValidationResult:
    test_name: str
    passed: bool
    matched: list[StateMatch]
    missing: list[StateMiss]
    order_violations: list[tuple[StateMatch, StateMatch]]  # (earlier_in_model, arrived_after)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.test_name}"]
        lines.append(f"  Essential states: {len(self.matched)} matched, {len(self.missing)} missing")
        for m in self.matched:
            lines.append(f"    ✓ pos={m.essential.position} '{m.essential.label}' → trace[{m.matched_at}] '{m.matched_label}' (d={m.distance})")
        for miss in self.missing:
            lines.append(f"    ✗ pos={miss.essential.position} '{miss.essential.label}': {miss.reason}")
        for a, b in self.order_violations:
            lines.append(
                f"    ⚠ order violation: '{a.essential.label}' (model pos {a.essential.position}) "
                f"appeared after '{b.essential.label}' (model pos {b.essential.position})"
            )
        return "\n".join(lines)


class TraceValidator:
    """
    Validates a new trace against a PTAModel.

    Checks two things:
    1. Every essential state appears somewhere in the new trace (coverage).
    2. Essential states appear in the correct topological order (sequence).
    """

    def __init__(self, checker: TieredEquivalenceChecker | None = None) -> None:
        self._checker = checker

    def validate(self, trace_dir: Path, model: PTAModel) -> ValidationResult:
        calibrator = AdaptiveThresholdCalibrator.from_fixed(model.ambiguity_low, model.ambiguity_high)
        checker = self._checker or TieredEquivalenceChecker(calibrator)

        new_trace = _load_trace(trace_dir)
        matched: list[StateMatch] = []
        missing: list[StateMiss] = []

        for essential in model.essential_states:
            essential_path = Path(essential.image_path)
            if not essential_path.exists():
                # Fall back to phash comparison only
                best = _find_by_phash(essential.phash, new_trace, model.ambiguity_high)
            else:
                best = _find_by_equivalence(essential_path, new_trace, checker)

            if best is None:
                missing.append(StateMiss(essential=essential, reason="no equivalent state found"))
            else:
                idx, label, dist = best
                matched.append(StateMatch(
                    essential=essential,
                    matched_at=idx,
                    matched_label=label,
                    distance=dist,
                ))

        order_violations = _check_order(matched)
        passed = len(missing) == 0 and len(order_violations) == 0

        return ValidationResult(
            test_name=model.test_name,
            passed=passed,
            matched=matched,
            missing=missing,
            order_violations=order_violations,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _load_trace(directory: Path) -> list[tuple[int, str, Path]]:
    """Return [(index, label, path), ...] sorted by filename."""
    images = sorted(directory.glob("*.png"), key=lambda p: p.name)
    result = []
    for i, img in enumerate(images):
        parts = img.stem.split("_", 1)
        label = parts[1].replace("_", " ") if len(parts) > 1 else img.stem
        result.append((i, label, img))
    return result


def _find_by_equivalence(
    essential_path: Path,
    trace: list[tuple[int, str, Path]],
    checker: TieredEquivalenceChecker,
) -> tuple[int, str, int] | None:
    """Find the best-matching state in the trace. Returns (index, label, distance) or None."""
    best: tuple[int, str, int] | None = None
    for idx, label, path in trace:
        if checker.are_equivalent(essential_path, path):
            dist = checker.phash_distance(essential_path, path)
            if best is None or dist < best[2]:
                best = (idx, label, dist)
    return best


def _find_by_phash(
    stored_phash: str,
    trace: list[tuple[int, str, Path]],
    high_threshold: int,
) -> tuple[int, str, int] | None:
    """Fallback: compare by phash string when the model image file is missing."""
    ref = imagehash.hex_to_hash(stored_phash)
    best: tuple[int, str, int] | None = None
    for idx, label, path in trace:
        dist = ref - imagehash.phash(Image.open(path))
        if dist <= high_threshold:
            if best is None or dist < best[2]:
                best = (idx, label, dist)
    return best


def _check_order(matched: list[StateMatch]) -> list[tuple[StateMatch, StateMatch]]:
    """
    Detect order violations: any pair where a higher model-position state
    appeared earlier in the new trace than a lower model-position state.
    """
    violations = []
    for i, a in enumerate(matched):
        for b in matched[i + 1:]:
            # a.essential.position < b.essential.position (model order)
            # but a.matched_at > b.matched_at (trace order reversed)
            if a.matched_at > b.matched_at:
                violations.append((a, b))
    return violations
