import json
from pathlib import Path
from .const import ERRORS
from .crypto import verify_ed25519
from .merkle import compute_integrity_root, looks_like_parquet

CANONICAL_JSON_KW = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False}

def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def _canonical_json_bytes(obj) -> bytes:
    return json.dumps(obj, **CANONICAL_JSON_KW).encode("utf-8")

def verify_shard(shard_dir: Path, repo_root: Path | None = None) -> dict:
    errors = []
    # Resolve repo root robustly.
    # Shards may live anywhere on disk, so do not assume a fixed parent depth.
    if repo_root is None:
        cur = shard_dir.resolve()
        found: Path | None = None
        # Walk upward looking for a repo marker.
        for p in (cur,) + tuple(cur.parents):
            if (p / "governance" / "trust_store.json").exists() or (p / "pyproject.toml").exists():
                found = p
                break
        # Fallback: treat the shard directory itself as the root.
        repo_root = found or cur

    manifest_path = shard_dir / "manifest.json"
    sig_path = shard_dir / "sig" / "manifest.sig"
    pub_path = shard_dir / "sig" / "publisher.pub"
    gov_trust = repo_root / "governance" / "trust_store.json"

    for p in [manifest_path, sig_path, pub_path]:
        if not p.exists():
            errors.append({"code":"E_LAYOUT_MISSING","message":ERRORS["E_LAYOUT_MISSING"],"path":str(p)})
            return {"status":"FAIL","error_count":len(errors),"errors":errors}

    try:
        manifest_obj = _load_json(manifest_path)
    except Exception as e:
        errors.append({"code":"E_MANIFEST_JSON","message":ERRORS["E_MANIFEST_JSON"],"detail":str(e)})
        return {"status":"FAIL","error_count":len(errors),"errors":errors}

    canonical_bytes = _canonical_json_bytes(manifest_obj)
    pub = pub_path.read_bytes()
    sig = sig_path.read_bytes()
    if not verify_ed25519(pub, canonical_bytes, sig):
        errors.append({"code":"E_SIG_INVALID","message":ERRORS["E_SIG_INVALID"]})
        return {"status":"FAIL","error_count":len(errors),"errors":errors}

    integrity = manifest_obj.get("integrity", {})
    expected_root = integrity.get("merkle_root", "")
    rel_files = integrity.get("files", [])

    try:
        computed = compute_integrity_root(shard_dir, rel_files)
    except Exception as e:
        errors.append({"code":"E_INTEGRITY_MISMATCH","message":ERRORS["E_INTEGRITY_MISMATCH"],"detail":str(e)})
        return {"status":"FAIL","error_count":len(errors),"errors":errors}
    if expected_root != computed:
        errors.append({"code":"E_INTEGRITY_MISMATCH","message":ERRORS["E_INTEGRITY_MISMATCH"],"expected":expected_root,"computed":computed})
        return {"status":"FAIL","error_count":len(errors),"errors":errors}

    for rel in rel_files:
        if rel.endswith(".parquet"):
            p = shard_dir / rel
            if not looks_like_parquet(p):
                errors.append({"code":"E_PARQUET_MAGIC","message":ERRORS["E_PARQUET_MAGIC"],"path":str(p)})
                return {"status":"FAIL","error_count":len(errors),"errors":errors}

    trust = _load_json(gov_trust) if gov_trust.exists() else {"trusted_publishers":[]}
    trusted = set([x.lower() for x in trust.get("trusted_publishers", [])])
    pub_hex = pub.hex().lower()
    if pub_hex not in trusted:
        errors.append({"code":"E_POLICY_TRUST","message":ERRORS["E_POLICY_TRUST"],"publisher_pub":pub_hex})
        return {"status":"FAIL","error_count":len(errors),"errors":errors}

    return {"status":"PASS","error_count":0,"errors":[]}
