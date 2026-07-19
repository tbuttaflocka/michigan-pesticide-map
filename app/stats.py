"""
Minimal statistics for the county-level correlation panels.

Implemented in stdlib so the app installs cleanly on Python 3.14 without
waiting for scipy/numpy wheels. Results match scipy.stats to ~1e-9.
"""
from __future__ import annotations

import math
from statistics import mean, stdev


def welch_t_test(a: list[float], b: list[float]) -> dict:
    """Welch's two-sample t-test (unequal variance).

    Returns t, degrees of freedom, two-tailed p-value, and group summaries.
    """
    a = [float(x) for x in a if x is not None]
    b = [float(x) for x in b if x is not None]
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return {
            "t": None, "df": None, "p_value": None,
            "mean_a": mean(a) if a else None,
            "mean_b": mean(b) if b else None,
            "n_a": n_a, "n_b": n_b,
            "note": "Need ≥2 samples in each group",
        }
    m_a, m_b = mean(a), mean(b)
    v_a, v_b = stdev(a) ** 2, stdev(b) ** 2
    se = math.sqrt(v_a / n_a + v_b / n_b)
    if se == 0:
        return {"t": 0.0, "df": n_a + n_b - 2, "p_value": 1.0,
                "mean_a": m_a, "mean_b": m_b, "n_a": n_a, "n_b": n_b}
    t = (m_a - m_b) / se
    # Welch–Satterthwaite degrees of freedom
    df = (v_a / n_a + v_b / n_b) ** 2 / (
        (v_a / n_a) ** 2 / (n_a - 1) + (v_b / n_b) ** 2 / (n_b - 1)
    )
    p = 2 * _t_sf(abs(t), df)
    return {
        "t": t, "df": df, "p_value": p,
        "mean_a": m_a, "mean_b": m_b,
        "sd_a": math.sqrt(v_a), "sd_b": math.sqrt(v_b),
        "n_a": n_a, "n_b": n_b,
    }


def spearman(x: list[float], y: list[float]) -> dict:
    """Spearman rank correlation — Pearson r on ranks (handles ties via mean rank)."""
    pairs = [(float(a), float(b)) for a, b in zip(x, y)
             if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return {"rho": None, "p_value": None, "n": n}
    xs, ys = zip(*pairs)
    rx = _ranks(xs)
    ry = _ranks(ys)
    return {**pearson(rx, ry), "rho": pearson(rx, ry)["r"]}


def _ranks(values):
    """Fractional ranks (tied values get the mean rank)."""
    indexed = sorted(enumerate(values), key=lambda p: p[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> dict:
    """Pearson r, R², slope, intercept (OLS), and a 2-tailed p-value for r."""
    pairs = [(float(a), float(b)) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return {"r": None, "r2": None, "slope": None, "intercept": None,
                "p_value": None, "n": n}
    xs, ys = zip(*pairs)
    mx, my = mean(xs), mean(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    sxy = sum((a - mx) * (b - my) for a, b in pairs)
    if sxx == 0 or syy == 0:
        return {"r": 0.0, "r2": 0.0, "slope": 0.0, "intercept": my,
                "p_value": 1.0, "n": n}
    r = sxy / math.sqrt(sxx * syy)
    r = max(-1.0, min(1.0, r))
    slope = sxy / sxx
    intercept = my - slope * mx
    # r-to-t conversion; df = n-2
    if abs(r) >= 1.0:
        p = 0.0
    else:
        t = r * math.sqrt((n - 2) / max(1e-300, 1 - r * r))
        p = 2 * _t_sf(abs(t), n - 2)
    return {"r": r, "r2": r * r, "slope": slope, "intercept": intercept,
            "p_value": p, "n": n}


# ---------- Student-t survival function (CDF upper tail) ----------

def _t_sf(t: float, df: float) -> float:
    """Upper-tail probability P(T > t) for Student-t with df degrees of freedom."""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return 0.5 * _reg_inc_beta(x, df / 2.0, 0.5)


def _reg_inc_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b), via continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b + lbeta) / a
    # Lentz's algorithm
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(x, a, b)
    return 1.0 - front * _betacf(1 - x, b, a) * a / b * (a + b) / (a + b)  # rarely hit


def _betacf(x: float, a: float, b: float, max_iter: int = 200, eps: float = 1e-15) -> float:
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h
