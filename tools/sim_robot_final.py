import json, random, uuid, struct, os
from datetime import datetime
from pathlib import Path
from collections import deque


from axm_core.protocol import (
    MAGIC_LATENT_FILE,
    MAGIC_LATENT_REC,
    MAGIC_RESID_REC,
    VERSION,
    REC_HEADER_FMT,
    REC_HEADER_LEN,
    DEFAULT_MAX_RESIDUAL_SIZE,
    LATENT_DIM,
    LATENT_REC_LEN,
)
# --- CONFIGURATION ---
FPS = 10
# LATENT_DIM imported from axm_core.protocol
PRE_WINDOW_FRAMES = int(FPS * 2.0)  # 2 Seconds History
POST_WINDOW_FRAMES = int(FPS * 2.0) # 2 Seconds Future + Trigger

# CONSTANTS

class ResidualRecorder:
    def __init__(self, file_handle):
        self.f = file_handle
        self.buffer = deque(maxlen=PRE_WINDOW_FRAMES)
        self.recording_frames_left = 0

    def push(self, frame_id, data):
        """
        Ingest frame.
        If RECORDING: Write direct.
        If BUFFERING: Add to ring.
        """
        # Deterministic Header
        header = struct.pack(REC_HEADER_FMT, MAGIC_RESID_REC, VERSION, frame_id, len(data))
        blob = header + data

        if self.recording_frames_left > 0:
            self.f.write(blob)
            self.recording_frames_left -= 1
            if self.recording_frames_left == 0:
                self.f.flush()  # Durability: Commit the event
                os.fdatasync(self.f.fileno()) if hasattr(os, 'fdatasync') else os.fsync(self.f.fileno())
            return "WRITTEN"
        else:
            self.buffer.append(blob)
            return "BUFFERED"

    def trigger(self):
        """
        Transitions from Buffering to Recording.
        1. Flushes the Pre-Window (History).
        2. Sets counter for Post-Window (Future).
        """
        if self.recording_frames_left > 0:
            return # Already triggered

        # Flush History
        while self.buffer:
            self.f.write(self.buffer.popleft())

        self.f.flush()  # Durability: Commit history
        os.fdatasync(self.f.fileno()) if hasattr(os, 'fdatasync') else os.fsync(self.f.fileno())

        # Set Future Window (Includes current frame if called before push)
        self.recording_frames_left = POST_WINDOW_FRAMES

def generate_session(out_dir, crash=False):
    sess_id = str(uuid.uuid4())
    path = Path(out_dir) / f"capsule-{sess_id[:8]}"
    path.mkdir(parents=True, exist_ok=True)

    f_lat = open(path / "cam_latents.bin", "wb", buffering=0)
    f_res = open(path / "cam_residuals.bin", "wb")
    f_log = open(path / "events.jsonl", "wb")

    # File-Level Magic for Latents (Safety)
    f_lat.write(MAGIC_LATENT_FILE)

    recorder = ResidualRecorder(f_res)

    print(f"Generating: {sess_id} (Crash={crash})")

    # Deterministic-ish metadata for the demo.
    # This exists to support compiler-side enrichment and tests that expect a "surface" field.
    surface_choices = ["asphalt", "concrete", "gravel", "wet_asphalt", "ice"]

    for frame_id in range(100):
        # 1. Trigger Check (Before Push ensures Trigger Frame is in Post-Window)
        evt = None
        if crash and frame_id == 50:
            evt = {
                "evt": "wheel_slip",
                "lvl": "WARN",
                # Keep this stable across runs for reproducible test vectors.
                # If you want true randomness, seed and choose per-session.
                "surface": surface_choices[0],
            }
            recorder.trigger()

        # 2. Data Gen
        latents = os.urandom(LATENT_DIM)
        residuals = os.urandom(50 * 1024)

        # 3. Write Latent (Strict Offset)
        lat_offset = f_lat.tell() # Capture BEFORE write

        # Build Record
        lat_header = struct.pack(REC_HEADER_FMT, MAGIC_LATENT_REC, VERSION, frame_id, len(latents))
        f_lat.write(lat_header + latents)

        os.fdatasync(f_lat.fileno()) if hasattr(os, 'fdatasync') else os.fsync(f_lat.fileno())
        # 4. Push Residual
        recorder.push(frame_id, residuals)

        # 5. Log (Pattern 2: No Residual Pointers)
        log_entry = {
            "frame_id": frame_id,
            "stream_refs": {
                "latents": {
                    "file": "cam_latents.bin",
                    "offset": lat_offset,
                    "length": LATENT_REC_LEN
                }
            }
        }
        if evt:
            log_entry.update(evt)
        f_log.write(json.dumps(log_entry).encode() + b"\n")

    f_lat.close(); f_res.close(); f_log.close()

    (path/"meta.json").write_text(json.dumps({
        "session_id": sess_id,
        "robot_id": "sim-final",
        "started_at": datetime.utcnow().isoformat() + "Z"
    }))

if __name__ == "__main__":
    generate_session("capsules_final", crash=False)
    generate_session("capsules_final", crash=True)
