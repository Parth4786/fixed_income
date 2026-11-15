// Full revaluation of a fixed cash-flow portfolio under many curve scenarios.
//
// value[s] = sum_k amount[k] * exp(-z_s(t[k]) * t[k] / 100)
// z_s(t)   = linear interpolation in t of (base[g] + shift[s][g]) on grid[g], held flat outside the grid.
//
// This is the inner loop of historical VaR by full repricing: thousands of cash flows times thousands of days.
// Python calls it through ctypes (tapemark.fast); a NumPy version of the same sum is the reference it is tested against.

#include <cmath>
#include <cstddef>

extern "C" {

#ifdef _WIN32
__declspec(dllexport)
#endif
void revalue(const double* t, const double* amount, std::size_t n_cf,
             const double* grid, const double* base, std::size_t n_grid,
             const double* shift, std::size_t n_scen, double* value) {
    // Each cash flow's place on the grid does not change between scenarios: find it once.
    std::size_t* lo = new std::size_t[n_cf];
    double* w = new double[n_cf];
    for (std::size_t k = 0; k < n_cf; ++k) {
        double x = t[k];
        if (x <= grid[0]) { lo[k] = 0; w[k] = 0.0; continue; }
        if (x >= grid[n_grid - 1]) { lo[k] = n_grid - 2; w[k] = 1.0; continue; }
        std::size_t j = 0;
        while (grid[j + 1] < x) ++j;
        lo[k] = j;
        w[k] = (x - grid[j]) / (grid[j + 1] - grid[j]);
    }
    for (std::size_t s = 0; s < n_scen; ++s) {
        const double* sh = shift + s * n_grid;
        double total = 0.0;
        for (std::size_t k = 0; k < n_cf; ++k) {
            std::size_t j = lo[k];
            double z0 = base[j] + sh[j], z1 = base[j + 1] + sh[j + 1];
            double z = z0 + w[k] * (z1 - z0);
            total += amount[k] * std::exp(-z * t[k] / 100.0);
        }
        value[s] = total;
    }
    delete[] lo;
    delete[] w;
}

}
