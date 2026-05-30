"""Build and persist the PTA model for a named test."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import imagehash
from PIL import Image

from .equivalence import AdaptiveThresholdCalibrator, TieredEquivalenceChecker


@dataclass
class EssentialState:
    """A state that appears in every training trace — must be present in any valid run."""

    position: int
    label: str
    phash: str
    image_path: str  # representative screenshot from training


@dataclass
class PTAModel:
    test_name: str
    essential_states: list[EssentialState]
    ambiguity_low: int
    ambiguity_high: int
    training_traces: int

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "test_name": self.test_name,
            "essential_states": [asdict(s) for s in self.essential_states],
            "ambiguity_low": self.ambiguity_low,
            "ambiguity_high": self.ambiguity_high,
            "training_traces": self.training_traces,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Model saved → {path}  ({len(self.essential_states)} essential states)")

    @classmethod
    def load(cls, path: Path) -> "PTAModel":
        data = json.loads(path.read_text(encoding="utf-8"))
        states = [EssentialState(**s) for s in data["essential_states"]]
        return cls(
            test_name=data["test_name"],
            essential_states=states,
            ambiguity_low=data["ambiguity_low"],
            ambiguity_high=data["ambiguity_high"],
            training_traces=data["training_traces"],
        )

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        test_name: str,
        trace_dirs: list[Path],
        checker: Optional[TieredEquivalenceChecker] = None,
    ) -> "PTAModel":
        """
        Build a model from multiple passing-run trace directories.

        Each trace_dir must contain ordered PNGs like:
            000_Open_home.png
            001_Click_login.png
            ...

        Essential states are those where all traces have an equivalent screenshot
        at (approximately) the same position.
        """
        if len(trace_dirs) < 2:
            raise ValueError("Need at least 2 passing traces to build a reliable model.")

        traces = [_load_trace(d) for d in trace_dirs]
        _validate_traces(traces, trace_dirs)

        calibrator = AdaptiveThresholdCalibrator()
        if checker is None:
            checker = TieredEquivalenceChecker(calibrator)
        else:
            calibrator = checker.calibrator

        # Calibrate thresholds
        _calibrate(traces, calibrator)

        # Find essential states: positions where all traces agree
        essential: list[EssentialState] = []
        n_positions = min(len(t) for t in traces)

        for pos in range(n_positions):
            # Check if all traces have an equivalent screenshot at this position
            ref_path = traces[0][pos][1]
            all_match = all(
                checker.are_equivalent(ref_path, traces[i][pos][1])
                for i in range(1, len(traces))
            )
            if all_match:
                label, path = traces[0][pos]
                ph = str(imagehash.phash(Image.open(path)))
                essential.append(EssentialState(
                    position=pos,
                    label=label,
                    phash=ph,
                    image_path=str(path),
                ))

        low, high = calibrator.ambiguity_band
        print(f"Calibrated band: hamming ≤{low} → same, >{high} → different, [{low}–{high}] → Claude")
        print(checker.cost_report())

        return cls(
            test_name=test_name,
            essential_states=essential,
            ambiguity_low=low,
            ambiguity_high=high,
            training_traces=len(traces),
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _load_trace(directory: Path) -> list[tuple[str, Path]]:
    """Return [(label, path), ...] sorted by step index."""
    images = sorted(directory.glob("*.png"), key=lambda p: p.name)
    if not images:
        raise FileNotFoundError(f"No PNG files found in {directory}")
    result = []
    for img in images:
        parts = img.stem.split("_", 1)
        label = parts[1].replace("_", " ") if len(parts) > 1 else img.stem
        result.append((label, img))
    return result


def _validate_traces(traces: list[list], dirs: list[Path]) -> None:
    lengths = [len(t) for t in traces]
    if max(lengths) - min(lengths) > 3:
        print(
            f"Warning: trace lengths vary significantly: "
            + ", ".join(f"{d.name}={l}" for d, l in zip(dirs, lengths))
        )


def _calibrate(
    traces: list[list[tuple[str, Path]]],
    calibrator: AdaptiveThresholdCalibrator,
) -> None:
    """
    Feed the calibrator:
    - Same-state pairs: same position index across different traces (should match)
    - Different-state pairs: adjacent positions within the same trace (should differ)
    """
    import imagehash
    from PIL import Image

    # Same-state: position i across trace 0 vs trace j
    for pos in range(min(len(t) for t in traces)):
        ref_path = traces[0][pos][1]
        ref_hash = imagehash.phash(Image.open(ref_path))
        for j in range(1, len(traces)):
            other_hash = imagehash.phash(Image.open(traces[j][pos][1]))
            calibrator.observe_same(ref_hash - other_hash)

    # Different-state: adjacent steps within each trace
    for trace in traces:
        for i in range(len(trace) - 1):
            h1 = imagehash.phash(Image.open(trace[i][1]))
            h2 = imagehash.phash(Image.open(trace[i + 1][1]))
            calibrator.observe_diff(h1 - h2)
