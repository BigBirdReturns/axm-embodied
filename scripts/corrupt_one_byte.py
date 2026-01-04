import sys
from pathlib import Path

def main():
    if len(sys.argv) != 2:
        print("Usage: corrupt_one_byte.py <file>")
        raise SystemExit(2)

    p = Path(sys.argv[1])
    b = bytearray(p.read_bytes())
    if len(b) < 64:
        print("File too small to corrupt safely.")
        raise SystemExit(2)

    # Flip a byte in the first latent record header area after file magic.
    # File magic is 4 bytes. Record header is 13 bytes.
    # We flip byte 8 (within frame_id field) to induce drift.
    idx = 4 + 8
    b[idx] ^= 0x01
    p.write_bytes(bytes(b))
    print(f"Corrupted 1 byte at offset {idx} in {p}")

if __name__ == "__main__":
    main()
