"""Windows-safe runner invocation; no shell interpolation of command text."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["sync", "ssh", "collect"])
    parser.add_argument("command", nargs="?", default="true")
    args = parser.parse_args()
    ip = (ROOT / "tools/runner_ip").read_text().strip()
    key = str(Path.home() / ".ssh/village_vultr")
    if args.mode == "sync":
        # tools/remote_run.sh does the required sync, venv setup, and execution.
        bash = "C:/Program Files/Git/bin/bash.exe" if Path("C:/Program Files/Git/bin/bash.exe").exists() else "bash"
        result = subprocess.run([bash, "tools/remote_run.sh", args.command], cwd=ROOT)
    elif args.mode == "ssh":
        result = subprocess.run(["ssh", "-i", key, f"root@{ip}", "bash", "-s"],
                                input=(args.command + "\n").encode())
    else:
        dest = ROOT / "demo_video/v3/out"
        dest.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["scp", "-i", key, "-r",
            f"root@{ip}:/srv/lim/{ROOT.name}/demo_video/v3/out/.", str(dest)])
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
