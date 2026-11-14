"""Start the configuration GUI with the supported Python runtime on Windows."""

from pathlib import Path
import subprocess
import sys


if sys.version_info < (3, 10) and "--relay-imagegen-reexec" not in sys.argv:
    subprocess.Popen([
        "py",
        "-3.13",
        str(Path(__file__).resolve()),
        "--relay-imagegen-reexec",
    ])
    raise SystemExit(0)

from scripts.setup import open_gui


if __name__ == "__main__":
    raise SystemExit(open_gui())
