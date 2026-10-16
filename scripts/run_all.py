"""Foreground supervisor for Linux/container deployment; exits if either service fails."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
wrapper = str(root / "scripts/run.py")
processes = []

def stop(signum=None, frame=None):
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda signum, frame: (stop(), sys.exit(0)))
try:
    processes.append(subprocess.Popen([sys.executable, "-u", wrapper, "control"], cwd=root))
    for _ in range(60):
        if processes[0].poll() is not None:
            raise RuntimeError("Control service exited during startup")
        try:
            with urlopen(f"http://127.0.0.1:{os.environ.get('ESP_PORT', '8002')}/api/health", timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(.5)
    else:
        raise RuntimeError("Control service did not become ready")
    processes.append(subprocess.Popen([sys.executable, "-u", wrapper, "voice"], cwd=root))
    while all(process.poll() is None for process in processes):
        time.sleep(1)
    raise RuntimeError("A service exited; stopping the companion process")
finally:
    stop()
