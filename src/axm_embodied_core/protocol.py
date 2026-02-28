"""AXM Embodied protocol constants.

Single source of truth for on-disk magic values and record layouts.
Keep this file stable. Recorder and Judge must remain synchronized.
"""

# File and record magics
MAGIC_LATENT_FILE = b"AXLF"  # Latent file header
MAGIC_LATENT_REC  = b"AXLR"  # Latent record header
MAGIC_RESID_REC   = b"AXRR"  # Residual record header

VERSION = 1

# Header: [Magic(4) | Ver(1) | FrameID(4) | Length(4)] = 13 bytes
REC_HEADER_FMT = "<4sBII"
REC_HEADER_LEN = 13

# Default safety bounds
DEFAULT_MAX_RESIDUAL_SIZE = 10 * 1024 * 1024  # 10 MiB

# Resynchronization bounds
DEFAULT_MAX_RESYNC_BYTES = 64 * 1024 * 1024  # 64 MiB scan window per corruption event
DEFAULT_MAX_GARBAGE_BYTES = 256 * 1024  # 256 KiB maximum tolerated garbage between records

# Latent record sizing
LATENT_DIM = 256
FILE_HEADER_LEN = 4
LATENT_REC_LEN = REC_HEADER_LEN + LATENT_DIM
