"""Signing-key loading for embodied CLIs.

Mirrors the axm-build discipline: there is deliberately no default
signing key. A signature made with a published private key proves
integrity, never authenticity. Generate a keypair with::

    axm-build keygen <outdir> --name <publisher>

and keep the ``.key`` file offline; only the ``.pub`` file belongs
anywhere near a repository or a robot's governance directory.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from axm_build.sign import HYBRID1_SK_LEN

_ENV_VAR = "AXM_SIGNING_KEY_HEX"

NO_KEY_MSG = (
    "No signing key provided. Pass --key <path to {n}-byte secret key blob> "
    "or set {env} to {h} hex characters.\n"
    "There is no default signing key: a key with a published private half "
    "proves integrity, never authenticity. Generate your own keypair with:\n"
    "  axm-build keygen <outdir> --name <publisher>"
).format(n=HYBRID1_SK_LEN, env=_ENV_VAR, h=HYBRID1_SK_LEN * 2)


def load_secret_key(key_path: Optional[Path] = None) -> bytes:
    """Load the 3904-byte axm-hybrid1 secret key blob.

    Order: explicit ``key_path`` file, then the AXM_SIGNING_KEY_HEX
    environment variable. Anything else is an error.
    """
    if key_path is not None:
        blob = Path(key_path).read_bytes()
        if len(blob) != HYBRID1_SK_LEN:
            raise ValueError(
                f"{key_path} is not a {HYBRID1_SK_LEN}-byte axm-hybrid1 secret "
                f"key blob (got {len(blob)} bytes)"
            )
        return blob

    key_hex = os.environ.get(_ENV_VAR, "")
    if key_hex:
        try:
            blob = bytes.fromhex(key_hex)
        except ValueError as e:
            raise ValueError(f"{_ENV_VAR} is not valid hex: {e}") from None
        if len(blob) != HYBRID1_SK_LEN:
            raise ValueError(
                f"{_ENV_VAR} must decode to {HYBRID1_SK_LEN} bytes, "
                f"got {len(blob)}"
            )
        return blob

    raise ValueError(NO_KEY_MSG)
