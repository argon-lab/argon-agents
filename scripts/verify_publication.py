#!/usr/bin/env python3
"""Verify an actual PyPI release and import its installed wheel in isolation."""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--wait-seconds", type=int, default=180)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        parser.error("--version must be a stable X.Y.Z version")
    deadline = time.monotonic() + max(0, args.wait_seconds)
    url = f"https://pypi.org/pypi/argon-agents/{args.version}/json"
    while True:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                release = json.load(response)
            wheels = [f for f in release["urls"]
                      if f["packagetype"] == "bdist_wheel" and not f["yanked"]]
            if release["info"]["version"] != args.version or not wheels:
                raise RuntimeError("Registry release has no matching non-yanked wheel")
            break
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            if time.monotonic() >= deadline:
                raise SystemExit(f"Publication not verified: {exc}") from exc
            time.sleep(min(5, max(0, deadline - time.monotonic())))

    with tempfile.TemporaryDirectory(prefix="argon-pypi-verify-") as scratch:
        root = pathlib.Path(scratch)
        venv.EnvBuilder(with_pip=True).create(root / "env")
        python = root / "env" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "--isolated", "install",
                        "--index-url", "https://pypi.org/simple/", "--only-binary=:all:",
                        "--no-cache-dir", f"argon-agents=={args.version}"], cwd=root, check=True)
        subprocess.run([str(python), "-I", "-c",
                        "import sys; from importlib.metadata import version; "
                        "from argon_agents import ArgonClient, ArgonError, Sandbox, sandboxed_mem0_config; "
                        "assert version('argon-agents') == sys.argv[1]; "
                        "print('Verified PyPI wheel:', version('argon-agents'))", args.version],
                       cwd=root, check=True)


if __name__ == "__main__":
    main()
