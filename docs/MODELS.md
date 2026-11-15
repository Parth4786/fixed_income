# Models, equations and assumptions

Every formula the project uses or will use, what it assumes, and where the
assumption fails. A model enters the project only with an entry here.

Status: every section below is implemented and tested. Results are in the
validation report.

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

## 11. The curve filter

State $x_t$: par swap rates at 14 lengths. Between trades and at a trade:

$$x_t = x_{t-1} + w_t,\quad w_t \sim N(0,\, Q\,\Delta t) \qquad\qquad y = h^\top x_t + v,\quad v \sim N(0, R)$$

$h$ holds the two straight-line weights that interpolate the trade's length between neighbouring lengths. Before the trade, the prediction is $\hat y = h^\top x$ with variance $S = h^\top P h + R$. Then

$$K = \frac{P h}{S},\qquad x \leftarrow x + K\,(y - \hat y),\qquad P \leftarrow P - K h^\top P$$

$Q$ is the covariance of daily changes of an outside curve over the trailing 120 days, re-estimated monthly from the past only. If $|y-\hat y| > 3\sqrt S$ the trade's noise is inflated so that it counts as exactly three standard deviations.

**Assumes:** rate changes are roughly normal with a slowly changing covariance; a trade is the market rate plus independent noise; lengths between nodes follow a straight line. **Fails when:** errors are fat-tailed (they are: 15% exceed three standard deviations), which is why bands are calibrated (section 12); and at the short end, where central bank meeting dates make the curve step.

## 12. Calibrated bands

$$\text{band}_t = \hat q_t \cdot \sqrt{S_t},\qquad \hat q_t = \text{90th percentile of } \frac{|y_i - \hat y_i|}{\sqrt{S_i}} \text{ over the previous 5,000 trades}$$

**Assumes:** recent errors are representative of the next one. **Fails when:** the regime changes faster than 5,000 trades.

## 13. Risk by automatic differentiation

Every quantity in the curve build and the swap value is carried as a pair (value, vector of derivatives with respect to each input rate), with the product, quotient, log and exp rules applied at each step. One pass gives $\partial V / \partial s_j$ for all $j$.

**Assumes:** nothing beyond the pricing formulas. **Checked by:** agreement with bump-and-rebuild in tests.

## 14. Value-change explanation

$$V_1 - V_0 = \underbrace{V(t_1, s_0) - V(t_0, s_0)}_{\text{time}} + \underbrace{\sum_j \frac{\partial V}{\partial s_j}\,\Delta s_j}_{\text{rates}} + \text{rest}$$

**Assumes:** moves small enough for a straight-line approximation. Measured remainder: 0.09% of the move for the median trade.

## 15. Hull-White one-factor model

$$dr = (\theta(t) - a\,r)\,dt + \sigma\,dW$$

Two numbers describe every option: $a$, how fast rates are pulled back, and $\sigma$, how much the short rate moves a year. The swap rate's normal volatility for an option expiring at $T$ is

$$\sigma_N \approx \sigma\,\left|\frac{\partial S}{\partial x}\right|\sqrt{\frac{1-e^{-2aT}}{2aT}},\qquad \frac{\partial S}{\partial x} = \frac{-B_0P_0 + B_nP_n}{A} + S\,\frac{\sum_i \alpha_i B_i P_i}{A},\qquad B_i = \frac{1-e^{-a(T_i-T)}}{a}$$

with $P_i$ the forward bond prices seen from expiry. Checked against the model's exact price (integrating over its random factor): agreement within 0.1%.

**Assumes:** one source of randomness moves the whole curve; constant $a$ and $\sigma$; no dependence on strike. **Fails when:** asked to match a whole volatility surface with two numbers. Measured: 16 bp of volatility miss out of sample against 4 for the last similar trade, in-sample fit error about 32 bp, and $a$ at the edge of its range on 61% of days. It is kept as the documented first step toward models for early-exercise products, not as a pricing recommendation.

## 16. Swap futures

An Eris SOFR swap future has the cash flows of a swap. Per 100 of size, long side receiving fixed:

$$\text{price} = 100 + A + B - C$$

$$A = \sum_{i\,\text{unpaid}} \big(c\,\tfrac{d_i}{360} - f_i\big)\, DF(p_i), \qquad B = \sum_{i\,\text{paid}} \big(c\,\tfrac{d_i}{360} - f_i\big)$$

with $c$ the coupon, $d_i$ the days in period $i$, $p_i$ its payment date (two business days after the period ends) and $f_i$ the floating amount:

$$f_i = \frac{DF(s_i)}{DF(e_i)} - 1 \ \text{(period ahead)}, \qquad f_i = \frac{G(s_i, t)}{DF(e_i)} - 1 \ \text{(period under way)}, \qquad G(s,t) = \prod_{s \le k < t} \Big(1 + r_k \tfrac{n_k}{360}\Big)$$

$G$ is SOFR compounded over the fixings already published. $C$ is interest on the daily margin payments, added up one day at a time:

$$C_t = C_{t-1} + A_{t-1}\, r_{t-1}\, \tfrac{n}{360}$$

A cleared swap pays this interest explicitly; a plain future does not, which would make the two worth different amounts. Putting it in the price removes the difference.

**Assumes:** the exchange's conventions (yearly periods on anniversaries moved to a business day, Actual/360, two-day payment lag). **Checked:** against the exchange's settlement files, 16,312 contract-days. $A$ within $0.27 a contract at worst; $B$ rebuilt from New York Fed fixings within $0.01; the one-day step of $C$ exact.

## 17. Margin and its funding cost

$$\text{margin}(T) = \text{DV01}(T) \times m_{h,q}(T), \qquad m_{h,q}(T) = q\text{-quantile of } |S_{t+h}(T) - S_t(T)| \text{ over past days}$$

$S_t(T)$ is the par rate for length $T$ on day $t$. The pair $(h, q)$ is chosen to reproduce the margins the exchange publishes on its contracts: two days at 99%. A cleared swap uses $h = 5$ at the same $q$.

Margin has to be funded at a spread $s$ above the overnight rate for as long as the trade lives:

$$\text{funding cost} = s \sum_k \text{margin}(T - t_k)\, DF(t_k)\, \Delta t$$

**Assumes:** one trade on its own; the curve held still while the trade shortens; the past six years represent future moves; $s$ supplied by the user. **Fails when:** the trade sits in a portfolio that nets, or when the clearing house adds stress and concentration charges, which this rule leaves out. The swap figure is therefore likely a floor.

## 18. Trades that trigger trades

In one-second steps, for two streams (swaps up to 5.5 years, and longer), with $y_j(t) \in \{0, 1\}$ marking a second in which stream $j$ traded:

$$\lambda_i(t) = \mu_{i,w}\, g_i(t) + \sum_j K_{ij} \sum_{l \ge 1} (1-\phi)\,\phi^{\,l-1}\, y_j(t-l), \qquad P\big(y_i(t) = 1\big) = 1 - e^{-\lambda_i(t)}$$

- $g_i(t)$: the average course of the hour across days, by minute, averaging one.
- $\mu_{i,w}$: the level for morning $w$, set so the model's average rate equals that morning's: $\mu_w = (I - K)\,\bar y_w$.
- $K_{ij}$: extra active seconds in stream $i$ caused by one in stream $j$ (the kernel weights sum to one).
- Largest eigenvalue of $K$: the share of activity that is a reaction to earlier activity.
- $\ln 2 / (-\ln \phi)$: seconds for the effect of a trade to halve.

Fitted by maximum likelihood. Standard errors by leaving out one sixth of the days at a time.

**Assumes:** triggering fades exponentially; the hour's average course is news, not triggering. **Fails when:** $g$ is taken as flat while activity has a burst: the burst is then counted as triggering (release mornings: 0.56 flat, 0.23 corrected).

## 19. Signed flow

Each clean trade is given a side $q_n = \text{sign}(S^{\text{traded}}_n - S^{\text{fair}}_n)$ when the gap is at least 0.05 bp. Flow in a ten-minute interval, in ten-year equivalents: $F_t = \sum_n q_n N_n T_n / 10$.

$$\Delta S_t = a + b\,F_t + \varepsilon_t, \qquad \Delta S_{t+1} = a' + b'\,F_t + c'\,\Delta S_t + \varepsilon'_t$$

Standard errors clustered by day. $b = 1.07$ bp per \$1bn (partly built in, since the model learns from the same trades). $b' = -0.11$; fitted on the first 70% of days it explains none of the variation on the rest.

**Assumes:** a trade above fair was initiated by the payer. **Limits:** the record has no side and caps large sizes.

## 20. Scores

| Product | Score |
|---|---|
| Swap | $e = S^{\text{model}} - S^{\text{traded}}$, in bp |
| Swap option | $e_P = V^{\text{model}} - V^{\text{traded}}$, and $e_\sigma \approx e_P / \text{vega}$ |

Summaries use the median and the 95th percentile of $|e|$, never the mean alone, because a few mislabelled trades dominate a mean. Options with near-zero vega are reported separately: dividing by a tiny number is unstable.

The testing protocol itself is in [METHOD.md](METHOD.md).
