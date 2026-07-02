"""Shadow Runtime — enforcement of the signed safety envelope, in the loop.

This is the layer beyond the flight recorder. The flight recorder proves
what happened after the fact; the Shadow Runtime sits between perception
and actuation and *acts* on the proof in real time:

    bounds shard (signed law)          Law Gate (governance)
              \\                         /
               ──────► ShadowRuntime ◄──
                            │
        per-frame guard: latent L∞ vs signed bound
                            │
          ┌─────────────────┴──────────────────┐
      in envelope                         out of envelope
          │                                     │
      PERMIT (motion)                 ESTOP + Flash Freeze
      frame recorded                  breach frame recorded,
                                      residual pre-window flushed,
                                      incident sealed into a shard
                                      that CITES the envelope id

Fail-closed doctrine:

- No clearance from the Law Gate → the runtime never arms.
- A frame whose action class has no signed bound → ESTOP (motion outside
  the certified envelope is not "unknown", it is forbidden).
- A non-finite latent norm → ESTOP (sensor garbage cannot be "in bounds").
- After ESTOP the runtime keeps recording (the hot stream stays gap-free;
  spoliation by power-cut is the only remaining move, and the fsync'd
  pre-trigger bytes already on disk survive it).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from axm_embodied.bounds import latent_l_inf
from axm_embodied.gate import Clearance
from axm_embodied.recorder import CapsuleRecorder


class RuntimeState(Enum):
    ARMED = "ARMED"
    ESTOP = "ESTOP"


class Verdict(Enum):
    PERMIT = "PERMIT"
    ESTOP = "ESTOP"


@dataclass(frozen=True)
class Decision:
    """The runtime's per-frame ruling. ``permitted`` gates the actuators."""
    frame_id: int
    verdict: Verdict
    action: str
    l_inf: float
    bound: Optional[float]
    reason: str

    @property
    def permitted(self) -> bool:
        return self.verdict is Verdict.PERMIT


@dataclass(frozen=True)
class Incident:
    """What a breach leaves behind: a sealed capsule and (optionally) a
    compiled incident shard citing the envelope it violated."""
    capsule_path: Path
    breach_frame: int
    shard_path: Optional[Path] = None
    shard_id: Optional[str] = None
    envelope_shard_id: Optional[str] = None


class ShadowRuntime:
    """Arms with a Law Gate clearance; guards every frame against the
    signed envelope; on breach kills motors and triggers Flash Freeze."""

    def __init__(self, clearance: Clearance, recorder: CapsuleRecorder):
        self.clearance = clearance
        self.envelope = clearance.envelope
        self.recorder = recorder
        self.state = RuntimeState.ARMED
        self.breach_frame: Optional[int] = None
        self._breach_decision: Optional[Decision] = None

    # ── The guard ────────────────────────────────────────────────────────

    def guard(
        self,
        latents: bytes,
        selected_action: str,
        action_distribution: Dict[str, float],
        residual: Optional[bytes] = None,
        event: Optional[Dict[str, Any]] = None,
    ) -> Decision:
        """Rule on one frame BEFORE actuation, and record it regardless.

        The recording is non-negotiable: permitted and forbidden frames
        alike land in the gap-free hot stream. What changes on a breach
        is actuation (killed) and the cold stream (flash-frozen).
        """
        lat = np.frombuffer(latents, dtype=np.float32)
        l_inf = latent_l_inf(lat)

        if self.state is RuntimeState.ESTOP:
            decision = Decision(
                frame_id=self.recorder.frames_recorded,
                verdict=Verdict.ESTOP,
                action="emergency_stop",
                l_inf=l_inf,
                bound=self.envelope.bound_for(selected_action),
                reason="motors killed: prior envelope breach",
            )
            self.recorder.record_frame(
                latents, "emergency_stop", action_distribution,
                residual=residual, event=event,
            )
            return decision

        bound = self.envelope.bound_for(selected_action)
        breach_reason: Optional[str] = None
        if bound is None:
            breach_reason = (
                f"action {selected_action!r} has no signed bound — motion "
                f"outside the certified envelope is forbidden"
            )
        elif not math.isfinite(l_inf):
            breach_reason = "non-finite latent norm (sensor garbage, fail closed)"
        elif l_inf > bound:
            breach_reason = f"latent L∞ {l_inf:.6f} exceeds signed bound {bound:.6f}"

        if breach_reason is None:
            decision = Decision(
                frame_id=self.recorder.frames_recorded,
                verdict=Verdict.PERMIT,
                action=selected_action,
                l_inf=l_inf,
                bound=bound,
                reason="within signed envelope",
            )
            self.recorder.record_frame(
                latents, selected_action, action_distribution,
                residual=residual, event=event,
            )
            return decision

        return self._breach(
            latents, selected_action, action_distribution,
            residual=residual, event=event, l_inf=l_inf, bound=bound,
            reason=breach_reason,
        )

    def _breach(
        self,
        latents: bytes,
        selected_action: str,
        action_distribution: Dict[str, float],
        *,
        residual: Optional[bytes],
        event: Optional[Dict[str, Any]],
        l_inf: float,
        bound: Optional[float],
        reason: str,
    ) -> Decision:
        # Flash Freeze FIRST: the trigger flushes the residual pre-window
        # and opens the post-window, so the breach frame itself is inside
        # the recorded window.
        self.recorder.trigger()
        self.state = RuntimeState.ESTOP

        frame_id = self.recorder.frames_recorded
        breach_event: Dict[str, Any] = {
            "evt": "envelope_breach",
            "action": selected_action,
            "l_inf": round(l_inf, 6) if math.isfinite(l_inf) else "inf",
            "bound": bound if bound is not None else "none",
            "envelope_shard_id": self.envelope.shard_id,
            "reason": reason,
        }
        if event:
            breach_event = {**event, **breach_event}

        self.recorder.record_frame(
            latents, "emergency_stop", action_distribution,
            residual=residual, event=breach_event,
        )
        # The runtime's own ruling is also on the record (Mens Rea of the
        # guard itself, one line after the breach frame).
        self.breach_frame = frame_id
        decision = Decision(
            frame_id=frame_id,
            verdict=Verdict.ESTOP,
            action="emergency_stop",
            l_inf=l_inf,
            bound=bound,
            reason=reason,
        )
        self._breach_decision = decision
        return decision

    # ── Sealing ──────────────────────────────────────────────────────────

    def seal(
        self,
        shard_out: Optional[Path] = None,
        secret_key: Optional[bytes] = None,
        timestamp: Optional[str] = None,
    ) -> Optional[Incident]:
        """Close the capsule; if a breach occurred and key material is
        provided, compile the incident shard citing the envelope.

        Returns None for a clean flight (the capsule stays on disk as an
        ordinary training candidate), an :class:`Incident` otherwise.
        """
        capsule_path = self.recorder.close()
        if self.breach_frame is None:
            return None

        shard_path = None
        shard_id = None
        if shard_out is not None and secret_key is not None:
            from axm_embodied.compile import compile_capsule

            shard_id = compile_capsule(
                capsule_path,
                Path(shard_out),
                secret_key,
                timestamp=timestamp,
                envelope_shard_id=self.envelope.shard_id,
            )
            shard_path = Path(shard_out)

        return Incident(
            capsule_path=capsule_path,
            breach_frame=self.breach_frame,
            shard_path=shard_path,
            shard_id=shard_id,
            envelope_shard_id=self.envelope.shard_id,
        )
