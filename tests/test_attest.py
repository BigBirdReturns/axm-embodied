"""Attestation queue: proof-of-when, queued offline at seal time."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess

import pytest

from axm_embodied.attest import (
    encode_tsq,
    list_queue,
    queue_attestation,
    verify_entry_matches_shard,
)
from axm_embodied.compile import compile_capsule
from axm_embodied.gate import LawGate
from axm_embodied.recorder import CapsuleRecorder
from axm_embodied.runtime import ShadowRuntime
from axm_embodied.sim import mission_frames

from conftest import RESIDUAL_BYTES, record_mission

_HAS_OPENSSL = shutil.which("openssl") is not None


def test_tsq_matches_openssl_encoding(tmp_path):
    """Our dependency-free DER must be exactly what openssl would produce
    (minus the nonce, which we deliberately omit for reproducibility)."""
    if not _HAS_OPENSSL:
        pytest.skip("openssl not available")
    digest = hashlib.sha256(b"axm attestation test vector").digest()

    ours = encode_tsq(digest)
    theirs = subprocess.run(
        ["openssl", "ts", "-query", "-sha256", "-digest", digest.hex(),
         "-cert", "-no_nonce"],
        capture_output=True, check=True,
    ).stdout
    assert ours == theirs


def test_queue_and_verify_entry(tmp_path, robot_keys):
    cap = record_mission(tmp_path, fault_at=25)
    shard = tmp_path / "shard"
    shard_id = compile_capsule(cap, shard, robot_keys[1])

    entry = queue_attestation(shard, tmp_path / "queue", note="test incident")
    assert entry.shard_id == shard_id
    assert not entry.anchored
    assert verify_entry_matches_shard(entry.path, shard)

    # The record carries what a court needs to join entry -> shard.
    record = json.loads((entry.path / "record.json").read_text())
    assert record["merkle_root"]
    assert record["anchors"] == []

    # Tampering with the manifest copy is detectable.
    (entry.path / "manifest.json").write_bytes(b"{}")
    assert not verify_entry_matches_shard(entry.path)


def test_queue_listing_tracks_anchor_state(tmp_path, robot_keys):
    cap = record_mission(tmp_path, fault_at=25)
    shard = tmp_path / "shard"
    compile_capsule(cap, shard, robot_keys[1])

    queue = tmp_path / "queue"
    entry = queue_attestation(shard, queue)
    assert [e.anchored for e in list_queue(queue)] == [False]

    (entry.path / "manifest.tsr").write_bytes(b"fake-tsa-response")
    assert [e.anchored for e in list_queue(queue)] == [True]


def test_runtime_seal_queues_attestation(bounds_shard, governance, tmp_path, robot_keys):
    """The robot notarizes its own crash: sealing a breach queues the
    timestamp query with no network involved."""
    clearance = LawGate(governance).authorize(bounds_shard)
    recorder = CapsuleRecorder(tmp_path / "flight", robot_id="test-unit")
    rt = ShadowRuntime(clearance, recorder)
    for fr in mission_frames(frames=40, seed=42, fault_at=20,
                             residual_bytes=RESIDUAL_BYTES):
        rt.guard(fr.latents, fr.selected_action, fr.action_distribution,
                 residual=fr.residual, event=fr.event)

    incident = rt.seal(shard_out=tmp_path / "incident", secret_key=robot_keys[1])
    assert incident is not None
    assert incident.attestation_path is not None
    assert verify_entry_matches_shard(incident.attestation_path, incident.shard_path)

    record = json.loads((incident.attestation_path / "record.json").read_text())
    assert record["shard_id"] == incident.shard_id
    assert "envelope breach at frame 20" in record["note"]
    assert rt.envelope.shard_id in record["note"]
