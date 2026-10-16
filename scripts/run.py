"""Absolute entry point for identifiable Windows background processes."""
import os
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
mode = sys.argv[1] if len(sys.argv) > 1 else "control"
if mode not in ("control", "voice"):
    raise SystemExit("Expected control or voice")
runpy.run_module("server" if mode == "control" else "server.voice_runner", run_name="__main__")
