#!/usr/bin/env python3
import pathlib, sys, time, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from hivemind.platform.input import VirtualInput
PROOF = pathlib.Path("/tmp/hivemind-diag/keyproof")
sock = os.environ["TARGET_SOCK"]
PROOF.unlink(missing_ok=True)
vin = VirtualInput(sock)
print("  sending F9 via our virtual keyboard...")
for _ in range(3):
    vin.tap("f9"); time.sleep(0.4)
time.sleep(1.0)
print(f"  compositor received the key: {PROOF.exists()}")
vin.close()
