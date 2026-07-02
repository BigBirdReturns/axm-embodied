"""axm-runtime — drive the Shadow Runtime end to end.

Commands mirror the life of an embodied deployment:

    axm-runtime record-training OUT --runs 3          # safe capsules
    axm-bounds OUT bounds_shard/ --key school.key     # (axm-bounds CLI)
    axm-runtime enroll school.pub --governance gov/   # trust the publisher
    axm-runtime fly bounds_shard/ flight/ --governance gov/ [--inject-fault]

`fly` exit codes: 0 clean flight, 3 envelope breach (incident sealed),
1 the Law Gate refused to arm or another failure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from axm_embodied.gate import GateError, LawGate, enroll_key
from axm_embodied.keys import load_secret_key
from axm_embodied.recorder import CapsuleRecorder, RecorderConfig
from axm_embodied.runtime import ShadowRuntime
from axm_embodied.sim import mission_frames


@click.group()
def main() -> None:
    """Shadow Runtime: signed-envelope enforcement for embodied AI."""


@main.command("record-training")
@click.argument("out", type=click.Path(path_type=Path))
@click.option("--runs", default=3, show_default=True, help="Safe missions to record.")
@click.option("--frames", default=100, show_default=True)
@click.option("--seed", default=None, type=int, help="Base RNG seed (per-run offset added).")
@click.option("--robot-id", default="sim-unit-7", show_default=True)
def record_training(out: Path, runs: int, frames: int, seed: Optional[int], robot_id: str) -> None:
    """Record safe training capsules (Drone School input)."""
    for run in range(runs):
        run_seed = None if seed is None else seed + run
        with CapsuleRecorder(out, robot_id=robot_id) as rec:
            for fr in mission_frames(frames=frames, seed=run_seed):
                rec.record_frame(
                    fr.latents, fr.selected_action, fr.action_distribution,
                    residual=fr.residual, event=fr.event,
                )
        click.echo(f"  capsule: {rec.path}  ({rec.frames_recorded} frames, safe)")
    click.echo(f"PASS: {runs} safe training capsules in {out}")


@main.command("enroll")
@click.argument("pub_key", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--governance", required=True, type=click.Path(path_type=Path),
              help="Robot governance directory (trust_store.json lives here).")
@click.option("--name", default=None, help="Anchor name (defaults to the key filename).")
def enroll(pub_key: Path, governance: Path, name: Optional[str]) -> None:
    """Enroll a publisher public key as a trust anchor."""
    fp = enroll_key(governance, pub_key, name=name)
    click.echo(f"PASS: enrolled {pub_key.name} (sha256 {fp[:16]}…) in {governance}")


@main.command("fly")
@click.argument("bounds_shard", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("out", type=click.Path(path_type=Path))
@click.option("--governance", required=True, type=click.Path(exists=True, path_type=Path),
              help="Robot governance directory (Law Gate).")
@click.option("--inject-fault", is_flag=True, default=False,
              help="Inject a physics excursion mid-mission.")
@click.option("--fault-at", default=50, show_default=True)
@click.option("--frames", default=100, show_default=True)
@click.option("--seed", default=None, type=int)
@click.option("--robot-id", default="sim-unit-7", show_default=True)
@click.option("--key", "key_path", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Incident-publisher secret key; when set, a breach is "
                   "auto-compiled into a shard citing the envelope.")
def fly(bounds_shard: Path, out: Path, governance: Path, inject_fault: bool,
        fault_at: int, frames: int, seed: Optional[int], robot_id: str,
        key_path: Optional[Path]) -> None:
    """Arm under a signed envelope and fly a (simulated) mission."""
    # ── Law Gate: no proof, no motion ─────────────────────────────────────
    try:
        gate = LawGate(governance)
        clearance = gate.authorize(bounds_shard)
    except GateError as e:
        click.echo(f"REFUSED TO ARM: {e}")
        raise SystemExit(1)

    env = clearance.envelope
    click.echo(f"ARMED under envelope {env.shard_id}")
    click.echo(f"  publisher:   {env.publisher_id} (sha256 {env.publisher_fingerprint[:16]}…)")
    click.echo(f"  policy tier: ≤{clearance.max_actuation_tier}")
    for action, bound in sorted(env.bounds.items()):
        click.echo(f"  bound: {action:<16} L∞ ≤ {bound:.6f}")

    recorder = CapsuleRecorder(out, robot_id=robot_id, config=RecorderConfig())
    runtime = ShadowRuntime(clearance, recorder)

    permitted = 0
    for fr in mission_frames(
        frames=frames, seed=seed, fault_at=fault_at if inject_fault else None,
    ):
        decision = runtime.guard(
            fr.latents, fr.selected_action, fr.action_distribution,
            residual=fr.residual, event=fr.event,
        )
        if decision.permitted:
            permitted += 1
        elif runtime.breach_frame == decision.frame_id:
            click.echo(f"\nESTOP at frame {decision.frame_id}: {decision.reason}")
            click.echo("  motors killed, Flash Freeze triggered")

    secret_key = load_secret_key(key_path) if key_path else None
    incident = runtime.seal(
        shard_out=out / "incident-shard" if secret_key else None,
        secret_key=secret_key,
    )

    click.echo(f"\nMission over: {permitted}/{recorder.frames_recorded} frames permitted")
    click.echo(f"  capsule: {recorder.path}")
    if incident is None:
        click.echo("PASS: clean flight — no breach, cold stream stayed empty")
        return
    if incident.shard_id:
        click.echo(f"  incident shard: {incident.shard_path}")
        click.echo(f"  shard id:       {incident.shard_id}")
        click.echo(f"  cites envelope: {incident.envelope_shard_id}")
        click.echo(f"  attestation:    {incident.attestation_path} (queued; "
                   f"anchor with `axm-runtime attest-flush`)")
    else:
        click.echo("  (no --key given: capsule sealed, shard not compiled)")
    click.echo(f"BREACH at frame {incident.breach_frame}: incident evidence sealed")
    raise SystemExit(3)


@main.command("attest")
@click.argument("shard", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--queue", "queue_dir", required=True, type=click.Path(path_type=Path),
              help="Attestation queue directory.")
@click.option("--note", default="", help="Free-text note stored in the record.")
def attest(shard: Path, queue_dir: Path, note: str) -> None:
    """Queue a shard for out-of-band timestamp anchoring (offline, ~2 KB).

    Pins the manifest bytes (which commit to every byte of the shard) and
    pre-encodes the RFC 3161 query. Anchor later with attest-flush.
    """
    from axm_embodied.attest import queue_attestation
    entry = queue_attestation(shard, queue_dir, note=note)
    click.echo(f"QUEUED: {entry.shard_id}")
    click.echo(f"  entry:  {entry.path}")
    click.echo(f"  sha256: {entry.manifest_sha256}")


@main.command("attest-flush")
@click.argument("queue_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--tsa", "tsa_url", default=None,
              help="RFC 3161 TSA URL (default: freetsa.org, as used for the "
                   "kernel's gold-shard attestation).")
def attest_flush(queue_dir: Path, tsa_url: str | None) -> None:
    """Anchor every pending attestation at a time-stamping authority.

    Best-effort: entries that fail stay queued for the next flush. Verify
    an anchored entry with:

    \b
      openssl ts -verify -queryfile <entry>/manifest.tsq \\
        -in <entry>/manifest.tsr -CAfile <tsa-ca>.pem
    """
    from axm_embodied.attest import DEFAULT_TSA_URL, flush_queue, list_queue
    results = flush_queue(queue_dir, tsa_url=tsa_url or DEFAULT_TSA_URL)
    if not results:
        anchored = sum(1 for e in list_queue(queue_dir) if e.anchored)
        click.echo(f"Nothing pending ({anchored} already anchored).")
        return
    failed = 0
    for r in results:
        if r["status"] == "ANCHORED":
            click.echo(f"ANCHORED: {r['shard_id']} @ {r['tsa']}")
        else:
            failed += 1
            click.echo(f"PENDING:  {r['shard_id']} — {r.get('error', 'unknown error')}")
    if failed:
        click.echo(f"{failed} entr{'y' if failed == 1 else 'ies'} still pending; "
                   f"re-run attest-flush when connectivity returns.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
