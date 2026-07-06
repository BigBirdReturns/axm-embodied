"""Embodied Frame Capture v0 — end to end.

    camera (opaque frames)
      -> observe continuously, KEEP only a pre/post window around an explicit
         trigger (a motion sensor, a doorbell — declared, never inferred)
      -> continuity hash chain over every kept frame; disk is truth
      -> compile to a genesis-verifiable shard (frames sealed VERBATIM)
      -> verify with an out-of-band key.

No vision, no OCR, no filtering: the sensor's bytes are hashed and sealed as
they were emitted, at the explicit ``physical_capture`` tier. The "useful
dataset" — who/what/when — is a later, bounded, human-gated annotation layer,
never this recorder.

    python examples/frame_capture_demo.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from axm_build.sign import hybrid1_keygen
from axm_verify.logic import verify_shard

from axm_embodied.frame_capture import FrameCaptureConfig, FrameCaptureRecorder, FrameJudge
from axm_embodied.frame_compile import compile_frame_capsule


def _fake_camera(n: int):
    """A stand-in camera. Real deployments feed encoded frame bytes straight
    from the sensor; the recorder never looks inside them."""
    for i in range(n):
        yield hashlib.sha256(f"frame-{i}".encode()).digest() * 32  # 1 KiB opaque


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="frame_capture_demo_"))
    pub, key = hybrid1_keygen()

    # 1) record: motion fires once, mid-session
    with FrameCaptureRecorder(work, sensor_id="doorcam-01",
                              config=FrameCaptureConfig(pre_window_frames=6, post_window_frames=6)) as rec:
        for i, frame in enumerate(_fake_camera(40)):
            if i == 18:
                rec.trigger(reason="motion", source="pir-sensor-3")
            rec.observe_frame(frame)
    cap = rec.path
    manifest = json.loads((cap / "capture_manifest.json").read_text())

    # 2) judge (disk is truth) + 3) compile to a sealed shard
    out = work / "shard"
    shard_id = compile_frame_capsule(cap, out, key, timestamp="2026-07-06T00:00:00Z")

    # 4) verify with the out-of-band key
    pub_path = work / "trusted.pub"
    pub_path.write_bytes(pub)
    result = verify_shard(out, trusted_key_path=pub_path)

    receipt = {
        "artifact": "AXM Embodied Frame Capture v0",
        "evidence_tier": manifest["evidence_tier"],
        "evidence_tier_limits": manifest["evidence_tier_limits"],
        "sensor_id": manifest["sensor_id"],
        "frames_observed": manifest["frames_observed"],
        "frames_kept": manifest["frames_kept"],
        "triggers": manifest["triggers"],
        "kept_frame_ids": [r["frame_id"] for r in FrameJudge(cap).verify()],
        "shard_id": shard_id,
        "verification": result["status"],
        "profiles_checked": result.get("profiles_checked", []),
        "frames_sealed_verbatim": (out / "content" / "frames.bin").read_bytes()
        == (cap / "frames.bin").read_bytes(),
    }
    print(json.dumps(receipt, indent=2))
    ok = result["status"] == "PASS" and receipt["frames_sealed_verbatim"]
    print(f"[frame capture v0: {'OK' if ok else 'INCOMPLETE'} — kept "
          f"{receipt['frames_kept']}/{receipt['frames_observed']} frames]")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
