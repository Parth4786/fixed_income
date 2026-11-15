"""Full revaluation of cash flows under many curve scenarios: a C++ kernel with a NumPy reference.

`revalue` uses the compiled library `cpp/revalue.cpp` when it has been built
(`python tools/build_cpp.py`) and falls back to the NumPy version otherwise;
the two are tested against each other to a fraction of a cent.

Why C++ here: historical VaR by full repricing of a large book is a sum over
(days x cash flows) exponentials. NumPy has to hold the whole days x cash
flows matrix in memory; the C++ loop streams it, and runs several times
faster. Both numbers are reported by `benchmark`.
"""

from __future__ import annotations

import ctypes
import time

import numpy as np

from tapemark.paths import ROOT

LIB_PATHS = [ROOT / "cpp" / "build" / "revalue.dll", ROOT / "cpp" / "build" / "librevalue.so", ROOT / "cpp" / "build" / "librevalue.dylib"]
_lib = None


def _load():
    global _lib
    if _lib is None:
        _lib = False
        for p in LIB_PATHS:
            if p.exists():
                lib = ctypes.CDLL(str(p))
                d = ctypes.POINTER(ctypes.c_double)
                lib.revalue.argtypes = [d, d, ctypes.c_size_t, d, d, ctypes.c_size_t, d, ctypes.c_size_t, d]
                lib.revalue.restype = None
                _lib = lib
                break
    return _lib or None


def available() -> bool:
    return _load() is not None


def revalue_numpy(t, amount, grid, base, shift) -> np.ndarray:
    """value[s] = sum_k amount[k] * exp(-z_s(t_k) t_k / 100), z_s interpolated linearly on grid from base + shift[s]."""
    t, amount, grid, base = (np.asarray(a, dtype=float) for a in (t, amount, grid, base))
    shift = np.atleast_2d(np.asarray(shift, dtype=float))
    x = np.clip(t, grid[0], grid[-1])
    j = np.clip(np.searchsorted(grid, x, side="right") - 1, 0, len(grid) - 2)
    w = (x - grid[j]) / (grid[j + 1] - grid[j])
    curves = base[None, :] + shift                                    # scenarios x grid
    z = curves[:, j] + w[None, :] * (curves[:, j + 1] - curves[:, j])  # scenarios x cash flows
    return (amount[None, :] * np.exp(-z * t[None, :] / 100.0)).sum(axis=1)


def revalue_cpp(t, amount, grid, base, shift) -> np.ndarray:
    lib = _load()
    if lib is None:
        raise RuntimeError("C++ kernel not built: run python tools/build_cpp.py")
    arr = lambda a: np.ascontiguousarray(a, dtype=np.float64)  # noqa: E731
    t, amount, grid, base = arr(t), arr(amount), arr(grid), arr(base)
    shift = arr(np.atleast_2d(shift))
    out = np.empty(shift.shape[0])
    p = lambda a: a.ctypes.data_as(ctypes.POINTER(ctypes.c_double))  # noqa: E731
    lib.revalue(p(t), p(amount), len(t), p(grid), p(base), len(grid), p(shift), shift.shape[0], p(out))
    return out


def revalue(t, amount, grid, base, shift) -> np.ndarray:
    return revalue_cpp(t, amount, grid, base, shift) if available() else revalue_numpy(t, amount, grid, base, shift)


def benchmark(t, amount, grid, base, shift, repeat: int = 3) -> dict:
    def best(f):
        times = []
        for _ in range(repeat):
            s = time.perf_counter()
            f(t, amount, grid, base, shift)
            times.append(time.perf_counter() - s)
        return min(times) * 1000
    out = {"cash_flows": int(len(t)), "scenarios": int(np.atleast_2d(shift).shape[0]), "numpy_ms": round(best(revalue_numpy), 1)}
    if available():
        out["cpp_ms"] = round(best(revalue_cpp), 1)
        out["speedup"] = round(out["numpy_ms"] / max(out["cpp_ms"], 1e-6), 1)
        out["max_difference"] = float(np.max(np.abs(revalue_cpp(t, amount, grid, base, shift) - revalue_numpy(t, amount, grid, base, shift))))
    return out
