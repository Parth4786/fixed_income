# Models, equations and assumptions

Every formula the project uses or will use, what it assumes, and where the
assumption fails. A model enters the project only with an entry here.

Status: sections 1 to 3 describe rules already in the code. Sections 4 to 10
are the pricing models for stages 1 to 7 and are not implemented yet.

## Notation

| Symbol | Meaning |
|---|---|
| $DF(t)$ | Discount factor: value today of 1 dollar paid at time $t$ |
| $\alpha_i$ | Length of payment period $i$ in years, by the day-count rule |
| $S$ | Par swap rate: the fixed rate that makes a swap worth zero |
| $A$ | Annuity: $\sum_i \alpha_i DF(T_i)$, the value of receiving 1 per year on the fixed dates |
| $F$ | Forward swap rate for a swap starting in the future |
| $K$ | Strike: the fixed rate written into an option |
| $\sigma$ | Volatility of the swap rate, in rate units per year |
| bp | Basis point: one hundredth of a percent |

## 1. Trade lifecycle (implemented)

A raw file is a log of messages. The set of real trades is

$$\text{trades} = \{\, \text{last correction of } r \;:\; r \text{ is NEWT/TRAD and no report in its chain is cancelled} \,\}$$

**Assumes:** every correction and cancellation points at the report it replaces. **Fails when:** a firm re-reports a trade as new instead of correcting it, which would count it twice. Not yet measured.

## 2. Standard start (implemented)

A swap is "spot" when $0 \le \text{business days from trade to start} \le 3$.

**Assumes:** the standard two-business-day start, plus one day for a holiday. **Fails when:** same-day or next-day starts are economically different. Exact dates are used at pricing time.

## 3. Outside-curve agreement (implemented)

For day $d$ and swap length $n$:

$$\text{gap}_{d,n} = \operatorname{median}(\text{traded rates on } d \text{ for length } n) - S^{\text{Eris}}_{d,n}$$

**Assumes:** nothing; it is a description. **Read with care:** one side is the whole day's middle, the other a closing level, so part of the gap is intraday movement, not error.

## 4. Present value

$$PV = \sum_i CF_i \cdot DF(t_i)$$

**Assumes:** payments are certain, and one curve discounts everything. **Fails when:** there is credit risk, or collateral is posted in another currency.

## 5. Compounded overnight rate

The floating side of a SOFR swap pays, for a period of $D$ days with daily fixings $r_i$ each applying for $d_i$ days:

$$\text{floating rate} = \frac{360}{D}\left[\prod_i \left(1 + \frac{r_i\, d_i}{360}\right) - 1\right]$$

**Assumes:** Actual/360 day count, each fixing applied for the calendar days until the next business day. **Fails when:** the trade uses a lookback or lockout variant; these exist and must be read from the trade terms.

## 6. Par swap rate

For a swap from $T_0$ to $T_n$ with fixed payments at $T_1..T_n$:

$$S = \frac{DF(T_0) - DF(T_n)}{\sum_{i=1}^{n} \alpha_i\, DF(T_i)}$$

**Assumes:** the same curve both projects the overnight rate and discounts. True for cleared dollar SOFR swaps. **Fails when:** the trade is uncleared with different collateral.

## 7. Curve construction

Find discount factors such that every input swap reprices at its traded rate:

$$S_k^{\text{model}}(DF) = S_k^{\text{traded}} \quad \text{for each input } k$$

Between input dates, $\ln DF(t)$ is interpolated linearly, which means the overnight forward rate is constant between dates.

**Assumes:** inputs are consistent prices at one moment; the interpolation rule is a choice, not a fact. **Fails when:** inputs are from different times of day, or a central bank meeting falls between dates and the true forward rate steps. Alternatives are compared by out-of-sample error.

## 8. Sensitivity to rates

$$DV01 = \frac{PV(\text{rates} - 1\text{bp}) - PV(\text{rates} + 1\text{bp})}{2}$$

computed for a parallel shift and separately for each input swap. The same numbers are also obtained by automatic differentiation and must agree.

**Assumes:** small moves. **Fails when:** moves are large (convexity) or the curve changes shape in a way no single input captures.

## 9. Swap option price (normal model)

Value of the right to pay fixed rate $K$ on a swap with annuity $A$, forward rate $F$, expiry $T$:

$$V_{\text{payer}} = A\left[(F-K)\,\Phi(d) + \sigma\sqrt{T}\,\varphi(d)\right], \qquad d = \frac{F-K}{\sigma\sqrt{T}}$$

and to receive fixed: $V_{\text{receiver}} = A\left[(K-F)\,\Phi(-d) + \sigma\sqrt{T}\,\varphi(d)\right]$.

$\Phi$ and $\varphi$ are the standard normal distribution and density. Implied volatility is the $\sigma$ that makes $V$ equal the traded premium, found numerically.

$$\text{vega} = A\sqrt{T}\,\varphi(d)$$

**Assumes:** the forward swap rate moves in absolute steps with constant volatility until expiry (it can go negative); no early exercise. **Fails when:** volatility differs by strike, which it does. That is what section 10 addresses.

## 10. Volatility by strike (SABR)

$$dF = \alpha F^{\beta}\, dW_1, \qquad d\alpha = \nu\, \alpha\, dW_2, \qquad dW_1\, dW_2 = \rho\, dt$$

Four numbers per expiry and swap length: level $\alpha$, shape $\beta$ (fixed in advance), correlation $\rho$, volatility of volatility $\nu$. A closed-form approximation gives implied volatility at any strike.

**Assumes:** this particular random process; $\beta$ is chosen, not fitted. **Fails when:** there are too few traded strikes to pin down $\rho$ and $\nu$, which is common in this data. It must beat flat volatility and straight-line interpolation out of sample to be kept.

## 11. Scores

| Product | Score |
|---|---|
| Swap | $e = S^{\text{model}} - S^{\text{traded}}$, in bp |
| Swap option | $e_P = V^{\text{model}} - V^{\text{traded}}$, and $e_\sigma \approx e_P / \text{vega}$ |

Summaries use the median and the 95th percentile of $|e|$, never the mean alone, because a few mislabelled trades dominate a mean. Options with near-zero vega are reported separately: dividing by a tiny number is unstable.

The testing protocol itself is in [METHOD.md](METHOD.md).
