"""Three-tier state equivalence detection: phash → ambiguity band → Claude vision."""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import imagehash
    from PIL import Image
except ImportError as e:
    raise ImportError("Run: pip install imagehash Pillow") from e


class AdaptiveThresholdCalibrator:
    """
    Calibrates phash hamming-distance thresholds from observed pairs.

    Feed it same-state pairs (screenshots from the same logical step across
    multiple runs) and different-state pairs (adjacent steps in the same run).
    It computes where the two distributions meet and derives the ambiguity band
    that triggers the Claude fallback.
    """

    def __init__(self) -> None:
        self._same: list[int] = []
        self._diff: list[int] = []

    def observe_same(self, distance: int) -> None:
        self._same.append(distance)

    def observe_diff(self, distance: int) -> None:
        self._diff.append(distance)

    @property
    def threshold(self) -> int:
        if not self._same or not self._diff:
            return 10
        return int((np.mean(self._same) + np.mean(self._diff)) / 2)

    @property
    def ambiguity_band(self) -> tuple[int, int]:
        """(low, high): scores ≤ low → same; > high → different; in between → LLM."""
        if not self._same or not self._diff:
            return (8, 12)
        low = int(np.percentile(self._diff, 90))
        high = int(np.percentile(self._same, 10))
        if low >= high:
            t = self.threshold
            low, high = max(0, t - 2), t + 2
        return (low, high)

    def as_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "ambiguity_low": self.ambiguity_band[0],
            "ambiguity_high": self.ambiguity_band[1],
            "same_count": len(self._same),
            "diff_count": len(self._diff),
        }

    @classmethod
    def from_fixed(cls, low: int, high: int) -> "AdaptiveThresholdCalibrator":
        """Create a calibrator with fixed band (used when loading a saved model)."""
        c = cls()
        # Synthesise enough observations to fix the band
        for _ in range(10):
            c.observe_same(max(0, low - 3))
            c.observe_diff(high + 3)
        return c


class TieredEquivalenceChecker:
    """
    Decides whether two screenshots represent the same application state.

    Tier 1 — phash hamming distance with adaptive threshold (fast, free).
    Tier 2 — Claude vision API for the ambiguous middle band (slow, costs tokens).

    Results are cached by hash pair so each unique comparison is paid once.
    """

    def __init__(
        self,
        calibrator: Optional[AdaptiveThresholdCalibrator] = None,
        anthropic_api_key: Optional[str] = None,
    ) -> None:
        self.calibrator = calibrator or AdaptiveThresholdCalibrator()
        self._api_key = anthropic_api_key
        self._client = None  # lazy-init
        self._cache: dict[tuple[str, str], bool] = {}
        self.tier1_hits = 0
        self.tier2_hits = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def phash_distance(self, path_a: Path, path_b: Path) -> int:
        ha = imagehash.phash(Image.open(path_a))
        hb = imagehash.phash(Image.open(path_b))
        return ha - hb

    def are_equivalent(self, path_a: Path, path_b: Path) -> bool:
        ha = imagehash.phash(Image.open(path_a))
        hb = imagehash.phash(Image.open(path_b))
        key = self._cache_key(ha, hb)

        if key in self._cache:
            return self._cache[key]

        dist = ha - hb
        low, high = self.calibrator.ambiguity_band

        if dist <= low:
            self.tier1_hits += 1
            result = True
        elif dist > high:
            self.tier1_hits += 1
            result = False
        else:
            result = self._llm_compare(path_a, path_b)
            self.tier2_hits += 1

        self._cache[key] = result
        return result

    def cost_report(self) -> str:
        total = self.tier1_hits + self.tier2_hits
        if total == 0:
            return "No comparisons made."
        pct = 100 * self.tier2_hits / total
        return (
            f"Tier 1 (phash): {self.tier1_hits}/{total} ({100 - pct:.0f}%)\n"
            f"Tier 2 (Claude): {self.tier2_hits}/{total} ({pct:.0f}%)"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(ha: "imagehash.ImageHash", hb: "imagehash.ImageHash") -> tuple[str, str]:
        a, b = str(ha), str(hb)
        return (a, b) if a <= b else (b, a)

    def _llm_compare(self, path_a: Path, path_b: Path) -> bool:
        client = self._get_client()
        if client is None:
            return False  # conservative: treat as different when no LLM available

        img_a = Image.open(path_a).resize((512, 512))
        img_b = Image.open(path_b).resize((512, 512))

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": self._encode(img_a)}},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": self._encode(img_b)}},
                    {
                        "type": "text",
                        "text": (
                            "These two screenshots are from a UI automation test. "
                            "Do they represent the same logical application state? "
                            "Minor differences (timestamps, cursor position, highlight colour) are OK. "
                            "Reply with exactly one word: YES or NO."
                        ),
                    },
                ],
            }],
        )
        return response.content[0].text.strip().upper().startswith("Y")

    @staticmethod
    def _encode(img: "Image.Image") -> str:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.standard_b64encode(buf.getvalue()).decode()

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            try:
                import os
                self._api_key = os.environ["ANTHROPIC_API_KEY"]
            except KeyError:
                return None
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        except Exception:
            return None
        return self._client
