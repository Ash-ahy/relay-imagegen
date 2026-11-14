"""Start the configuration GUI with the supported Python runtime on Windows."""

from pathlib import Path
import subprocess
import sys


runtime_exe = Path(__file__).resolve().parent / "runtime" / "python.exe"
running_on_private_runtime = Path(sys.executable).resolve() == runtime_exe.resolve()
if runtime_exe.exists() and not running_on_private_runtime and "--relay-imagegen-reexec" not in sys.argv:
    subprocess.Popen([
        str(runtime_exe),
        "-s",
        str(Path(__file__).resolve()),
        "--relay-imagegen-reexec",
    ])
    raise SystemExit(0)

if sys.version_info < (3, 10) and "--relay-imagegen-reexec" not in sys.argv:
    subprocess.Popen([
        "py",
        "-3.13",
        str(Path(__file__).resolve()),
        "--relay-imagegen-reexec",
    ])
    raise SystemExit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.setup import open_gui


if __name__ == "__main__":
    raise SystemExit(open_gui())
