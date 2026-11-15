"""Price/volume signal engine — "is this move unusual *for this stock, today*?"

Three lenses, each answering a different question:

1. Raw thresholds (what the brief asks for): |return| ≥ X%, volume ≥ Y × 20-day average.
   Simple and legible — these are what the user tunes.

2. Market model (event-study abnormal return): r_i = α + β·r_m + ε, fitted on the prior
   120 sessions. ε_t / σ_ε is the *stock-specific* z-score. A −4% day when the Nifty fell
   3% is not news; a −4% day on a flat tape is.

3. Trajectory (Kalman filter). Borrowed from my table-tennis ball tracker: a local-linear-
   trend Kalman filter on log price predicts where the stock "should" be tomorrow given its
   level and drift; the innovation z = (observed − predicted)/√S says how far it left its
   path. Process/measurement noise adapt to a RiskMetrics EWMA of variance (λ=0.94), the
   same trick that let the ball tracker coast through occlusions without exploding the
   covariance. The ±2√S band is drawn in the app as the stock's "corridor".

Volume uses a robust z of log-volume against the prior 20 sessions (median/MAD), so one
earlier spike doesn't mask the next.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EST_WINDOW = 120   # sessions for beta / residual sigma
VOL_WINDOW = 20    # sessions for volume baseline
LAMBDA = 0.94      # RiskMetrics EWMA decay


@dataclass
class Day:
    date: str
    close: float
    volume: float
    ret_pct: float | None = None
    mkt_ret_pct: float | None = None
    sector_ret_pct: float | None = None
    vol_mult: float | None = None
    vol_z: float | None = None
    beta: float | None = None
    abnormal_pct: float | None = None
    abnormal_z: float | None = None
    pred: float | None = None
    band_lo: float | None = None
    band_hi: float | None = None
    traj_z: float | None = None

    def as_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _align(dates: list[str], ref: dict[str, float]) -> np.ndarray:
    return np.array([ref.get(d, np.nan) for d in dates], dtype=float)


def kalman_track(logp: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (predicted log price, innovation std √S, innovation z) per step.
    Index t is the one-step-ahead prediction for t made at t-1 (nan for t=0)."""
    n = len(logp)
    pred, sd, z = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    if n < 3:
        return pred, sd, z
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    x = np.array([logp[0], 0.0])
    r0 = np.diff(logp[: min(n, 21)])
    var = float(np.var(r0)) if len(r0) > 1 else 1e-4
    var = max(var, 1e-6)
    P = np.diag([var, var * 0.01])
    for t in range(1, n):
        q, qs, R = 0.85 * var, 0.0005 * var, 0.15 * var
        Q = np.diag([q, qs])
        x_p = F @ x
        P_p = F @ P @ F.T + Q
        S = float((H @ P_p @ H.T)[0, 0]) + R
        innov = logp[t] - x_p[0]
        pred[t], sd[t], z[t] = x_p[0], math.sqrt(S), innov / math.sqrt(S)
        K = (P_p @ H.T) / S
        x = x_p + (K * innov).ravel()
        P = (np.eye(2) - K @ H) @ P_p
        # adapt noise to realised variance (EWMA of squared returns)
        ret = logp[t] - logp[t - 1]
        var = max(LAMBDA * var + (1 - LAMBDA) * ret * ret, 1e-6)
    return pred, sd, z


def analyse(rows: list, market: dict[str, float], sector: dict[str, float] | None = None,
            keep_last: int = 130) -> list[Day]:
    """rows: sequence of (date, open, high, low, close, volume)-like records, ascending."""
    dates = [r["date"] if isinstance(r, dict) or hasattr(r, "keys") else r[0] for r in rows]
    close = np.array([float(r["close"]) for r in rows])
    vol = np.array([float(r["volume"] or 0) for r in rows])
    n = len(close)
    days = [Day(dates[i], float(close[i]), float(vol[i])) for i in range(n)]
    if n < 2:
        return days

    ret = np.full(n, np.nan); ret[1:] = np.log(close[1:] / close[:-1])
    m = _align(dates, market)
    mret = np.full(n, np.nan); mret[1:] = np.log(m[1:] / m[:-1])
    sret = None
    if sector:
        s = _align(dates, sector)
        sret = np.full(n, np.nan); sret[1:] = np.log(s[1:] / s[:-1])

    pred, sd, tz = kalman_track(np.log(close))
    logv = np.log1p(vol)

    for t in range(1, n):
        d = days[t]
        d.ret_pct = 100 * (math.exp(ret[t]) - 1)
        if not math.isnan(mret[t]):
            d.mkt_ret_pct = 100 * (math.exp(mret[t]) - 1)
        if sret is not None and not math.isnan(sret[t]):
            d.sector_ret_pct = 100 * (math.exp(sret[t]) - 1)
        # volume vs prior 20 sessions
        lo = max(0, t - VOL_WINDOW)
        if t - lo >= 5:
            base = vol[lo:t]
            avg = base.mean()
            d.vol_mult = float(vol[t] / avg) if avg > 0 else None
            lb = logv[lo:t]
            med = np.median(lb)
            mad = np.median(np.abs(lb - med)) * 1.4826
            d.vol_z = float((logv[t] - med) / mad) if mad > 1e-9 else None
        # market model on prior window
        lo = max(1, t - EST_WINDOW)
        y, x = ret[lo:t], mret[lo:t]
        ok = ~(np.isnan(y) | np.isnan(x))
        if ok.sum() >= 30 and not math.isnan(mret[t]):
            X = np.vstack([np.ones(ok.sum()), x[ok]]).T
            (a, b), *_ = np.linalg.lstsq(X, y[ok], rcond=None)
            resid = y[ok] - (a + b * x[ok])
            se = resid.std(ddof=2)
            ar = ret[t] - (a + b * mret[t])
            d.beta = float(b)
            d.abnormal_pct = float(100 * ar)
            d.abnormal_z = float(ar / se) if se > 0 else None
        if not math.isnan(pred[t]):
            d.pred = float(math.exp(pred[t]))
            d.band_lo = float(math.exp(pred[t] - 2 * sd[t]))
            d.band_hi = float(math.exp(pred[t] + 2 * sd[t]))
            d.traj_z = float(tz[t])
    return days[-keep_last:]


def triggers(d: Day, th) -> list[dict]:
    """Which user thresholds does this day cross? Each trigger carries its own plain-English line."""
    out = []
    if d.ret_pct is not None and abs(d.ret_pct) >= th.price_move_pct:
        out.append({"kind": "price", "text": f"{d.ret_pct:+.1f}% on the day (your line: ±{th.price_move_pct:g}%)"})
    if d.vol_mult is not None and d.vol_mult >= th.volume_multiple:
        out.append({"kind": "volume", "text": f"volume {d.vol_mult:.1f}× its 20-day average (your line: {th.volume_multiple:g}×)"})
    if d.abnormal_z is not None and abs(d.abnormal_z) >= th.abnormal_z:
        mk = f"Nifty {d.mkt_ret_pct:+.1f}%" if d.mkt_ret_pct is not None else "market"
        out.append({"kind": "abnormal", "text": f"{d.abnormal_pct:+.1f}% stock-specific after stripping {mk} (β {d.beta:.2f}), {d.abnormal_z:+.1f}σ"})
    if d.traj_z is not None and abs(d.traj_z) >= th.trajectory_z:
        side = "above" if d.traj_z > 0 else "below"
        out.append({"kind": "trajectory", "text": f"closed {side} its predicted corridor ({d.traj_z:+.1f}σ)"})
    return out
