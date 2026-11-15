"""Compile the C++ revaluation kernel into a shared library that tapemark.fast loads.

    python tools/build_cpp.py

Needs g++ (MinGW-w64 on Windows, gcc on Linux, clang on macOS). Without it the
project still runs: tapemark.fast falls back to NumPy.
"""

import pathlib
import platform
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "cpp" / "revalue.cpp"
OUT = ROOT / "cpp" / "build" / {"Windows": "revalue.dll", "Darwin": "librevalue.dylib"}.get(platform.system(), "librevalue.so")


def main() -> int:
    cxx = shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        print("no C++ compiler found; the NumPy version will be used")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    flags = ["-O3", "-march=x86-64-v2", "-shared", "-std=c++17"] + ([] if platform.system() == "Windows" else ["-fPIC"])
    if platform.system() == "Windows":
        flags += ["-static"]                                         # the DLL then needs no MinGW runtime (libstdc++, libwinpthread) on the path
    cmd = [cxx, *flags, str(SRC), "-o", str(OUT)]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"built {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
