"""Mission simulator — the stand-in for a real VLA + sensor stack.

Produces physically plausible latent frames (float32, bounded magnitude)
instead of raw entropy, so the Drone School envelope means something: a
safe mission's latent L∞ stays under the learned bound, and an injected
fault drives it far outside. Replace this module with the real inference
pipeline on hardware; the runtime, recorder, and compilers do not change.

The fault model is deliberately sinister for the demo: at the fault frame
the *physics* spike (wheel slip) while the VLA confidently keeps selecting
``maintain_speed``. The narrative log alone would say everything is fine.
The Shadow Runtime reads the physics, not the narrative.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Iterator, Optional

import numpy as np

from axm_embodied_core.protocol import LATENT_DIM

VLA_ACTIONS = [
    "maintain_speed", "decelerate", "steer_left", "steer_right", "emergency_stop",
]
SAFE_ACTIONS = ["maintain_speed", "decelerate", "steer_left", "steer_right"]

_FLOATS_PER_FRAME = LATENT_DIM // 4  # 256 payload bytes = 64 float32


def vla_distribution(rng: random.Random, selected: str) -> Dict[str, float]:
    """Simulate a VLA softmax over the action space (selected gets the mass)."""
    conf = round(rng.uniform(0.70, 0.95), 4)
    dist = {selected: conf}
    rem = round(1.0 - conf, 4)
    others = [a for a in VLA_ACTIONS if a != selected]
    for a in others[:-1]:
        val = round(rng.uniform(0, rem), 4)
        dist[a] = val
        rem = round(rem - val, 4)
    dist[others[-1]] = max(0.0, round(rem, 4))  # clamp float drift
    return dist


def nominal_latents(rng: random.Random, scale: float = 0.8) -> bytes:
    """A quiescent latent frame: 64 float32 in [0, scale)."""
    vals = np.array(
        [rng.uniform(0.0, scale) for _ in range(_FLOATS_PER_FRAME)],
        dtype=np.float32,
    )
    return vals.tobytes()


def fault_latents(rng: random.Random, magnitude: float = 8.0) -> bytes:
    """A physics excursion: latent energy far outside any learned envelope."""
    vals = np.array(
        [rng.uniform(magnitude, magnitude * 2) for _ in range(_FLOATS_PER_FRAME)],
        dtype=np.float32,
    )
    return vals.tobytes()


@dataclass(frozen=True)
class Frame:
    latents: bytes
    selected_action: str
    action_distribution: Dict[str, float]
    residual: bytes
    event: Optional[Dict] = None


def mission_frames(
    frames: int = 100,
    seed: Optional[int] = None,
    fault_at: Optional[int] = None,
    residual_bytes: int = 8 * 1024,
    latent_scale: float = 0.8,
    fault_magnitude: float = 8.0,
) -> Iterator[Frame]:
    """Yield one mission's frames. ``fault_at=None`` is a safe mission.

    At the fault frame the latents spike while the VLA still selects
    ``maintain_speed`` with high confidence — the lie the flight recorder
    exists to catch and the Shadow Runtime exists to stop.
    """
    rng = random.Random(seed)
    for frame_id in range(frames):
        # Piecewise-constant, deterministic action schedule: cycles through
        # every safe action class so training runs cover exactly the classes
        # a flight will use (an uncovered class correctly trips the guard).
        action = SAFE_ACTIONS[(frame_id // 10) % len(SAFE_ACTIONS)]

        residual = rng.randbytes(residual_bytes)

        if fault_at is not None and frame_id == fault_at:
            yield Frame(
                latents=fault_latents(rng, fault_magnitude),
                selected_action="maintain_speed",
                action_distribution=vla_distribution(rng, "maintain_speed"),
                residual=residual,
                event={"evt": "wheel_slip", "lvl": "WARN", "surface": "ice"},
            )
            continue

        yield Frame(
            latents=nominal_latents(rng, latent_scale),
            selected_action=action,
            action_distribution=vla_distribution(rng, action),
            residual=residual,
            event=None,
        )
