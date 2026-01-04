from pathlib import Path
import hashlib

def leaf_hash(rel_path: str, content: bytes) -> bytes:
    h = hashlib.sha256()
    h.update(rel_path.encode("utf-8"))
    h.update(b"\x00")
    h.update(content)
    return h.digest()

def compute_integrity_root(root_dir: Path, rel_files: list[str]) -> str:
    acc = hashlib.sha256()
    for rel in sorted(rel_files):
        p = root_dir / rel
        acc.update(leaf_hash(rel, p.read_bytes()))
    return acc.hexdigest()

def looks_like_parquet(p: Path) -> bool:
    b = p.read_bytes()
    return len(b) >= 8 and b[:4] == b"PAR1" and b[-4:] == b"PAR1"
