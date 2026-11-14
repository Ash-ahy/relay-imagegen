"""Start the configuration GUI with the supported Python runtime on Windows."""

from pathlib import Path
import os
import subprocess
import sys


current_dir = Path(__file__).resolve().parent
codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
installed_dir = codex_home / "skills" / "relay-imagegen"
installed_configure = installed_dir / "configure.pyw"
if installed_configure.exists() and installed_dir.resolve() != current_dir.resolve() and "--relay-imagegen-installed" not in sys.argv:
    installed_runtime = installed_dir / "runtime" / "python.exe"
    installed_python = str(installed_runtime) if installed_runtime.exists() else sys.executable
    subprocess.Popen([
        installed_python,
        "-s",
        str(installed_configure),
        "--relay-imagegen-installed",
    ])
    raise SystemExit(0)

runtime_exe = current_dir / "runtime" / "python.exe"
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
