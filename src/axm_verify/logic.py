"""AXM Embodied — Shard verification logic.

Uses the canonical axm-core crypto layer (suite-aware Merkle + signature).
Adapted for the embodied shard structure: no content/ dir, trust anchor is
governance/trust_store.json or a caller-supplied trusted key path.
"""
from __future__ import annotations

import json
from pathlib import Path

from .const import ERRORS
from .crypto import compute_merkle_root, verify_manifest_signature, SUITE_SIZES

CANONICAL_JSON_KW = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False}


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_shard(shard_dir: Path, repo_root: Path | None = None) -> dict:
    errors = []

    # Resolve repo root for governance lookup
    if repo_root is None:
        cur = shard_dir.resolve()
        found: Path | None = None
        for p in (cur,) + tuple(cur.parents):
            if (p / "governance" / "trust_store.json").exists() or (p / "pyproject.toml").exists():
                found = p
                break
        repo_root = found or cur

    manifest_path = shard_dir / "manifest.json"
    sig_path = shard_dir / "sig" / "manifest.sig"
    pub_path = shard_dir / "sig" / "publisher.pub"
    gov_trust = repo_root / "governance" / "trust_store.json"

    for p in [manifest_path, sig_path, pub_path]:
        if not p.exists():
            errors.append({
                "code": "E_LAYOUT_MISSING",
                "message": ERRORS["E_LAYOUT_MISSING"],
                "path": str(p),
            })
            return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    # ── Load manifest ─────────────────────────────────────────────────────
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_obj = json.loads(manifest_bytes)
    except Exception as e:
        errors.append({"code": "E_MANIFEST_JSON", "message": ERRORS["E_MANIFEST_JSON"], "detail": str(e)})
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    # Suite detection — "ed25519" if absent (v1.0 shards), explicit otherwise
    suite = manifest_obj.get("suite", "ed25519")
    if suite not in SUITE_SIZES:
        errors.append({"code": "E_SIG_INVALID", "message": f"Unknown suite: {suite!r}"})
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    # ── Signature ─────────────────────────────────────────────────────────
    pub = pub_path.read_bytes()
    expected_pk = SUITE_SIZES[suite]["pk"]
    if len(pub) != expected_pk:
        errors.append({
            "code": "E_SIG_INVALID",
            "message": ERRORS["E_SIG_INVALID"],
            "detail": f"Public key size {len(pub)} doesn't match suite {suite} (expected {expected_pk})",
        })
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    try:
        sig_ok = verify_manifest_signature(manifest_bytes, sig_path, pub_path, suite=suite)
    except RuntimeError as e:
        errors.append({"code": "E_SIG_INVALID", "message": str(e)})
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    if not sig_ok:
        errors.append({"code": "E_SIG_INVALID", "message": ERRORS["E_SIG_INVALID"]})
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    # ── Merkle ────────────────────────────────────────────────────────────
    integrity = manifest_obj.get("integrity", {})
    expected_root = integrity.get("merkle_root", "")

    try:
        computed = compute_merkle_root(shard_dir, suite=suite)
    except Exception as e:
        errors.append({"code": "E_INTEGRITY_MISMATCH", "message": ERRORS["E_INTEGRITY_MISMATCH"], "detail": str(e)})
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    if expected_root != computed:
        errors.append({
            "code": "E_INTEGRITY_MISMATCH",
            "message": ERRORS["E_INTEGRITY_MISMATCH"],
            "expected": expected_root,
            "computed": computed,
        })
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    # ── Parquet magic ─────────────────────────────────────────────────────
    rel_files = integrity.get("files", [])
    for rel in rel_files:
        if rel.endswith(".parquet"):
            p = shard_dir / rel
            b = p.read_bytes()
            if not (len(b) >= 8 and b[:4] == b"PAR1" and b[-4:] == b"PAR1"):
                errors.append({
                    "code": "E_PARQUET_MAGIC",
                    "message": ERRORS["E_PARQUET_MAGIC"],
                    "path": str(p),
                })
                return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    # ── Trust policy ──────────────────────────────────────────────────────
    trust = _load_json(gov_trust) if gov_trust.exists() else {"trusted_publishers": []}
    trusted = {x.lower() for x in trust.get("trusted_publishers", [])}
    pub_hex = pub.hex().lower()
    if pub_hex not in trusted:
        errors.append({
            "code": "E_POLICY_TRUST",
            "message": ERRORS["E_POLICY_TRUST"],
            "publisher_pub": pub_hex,
        })
        return {"status": "FAIL", "error_count": len(errors), "errors": errors}

    return {"status": "PASS", "suite": suite, "error_count": 0, "errors": []}
