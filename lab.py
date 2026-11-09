"""Momentum Lab - deterministic forward test of 3 momentum strategies vs SPY.

Rules are frozen in RULES.md. Every run refetches the full history and replays
every ledger from scratch, so runs are idempotent and self-backfilling.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# FROZEN CONFIGURATION - must not change for the duration of the test
# ---------------------------------------------------------------------------
UNIVERSE = sorted([
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC",
    "QQQ", "IWM", "IWD",
    "EFA", "VGK", "EWJ", "EEM", "EWZ", "FXI",
    "TLT", "IEF", "SHY", "LQD", "HYG", "TIP", "EMB",
    "GLD", "SLV", "DBC",
])
BENCHMARK = "SPY"
START_SIGNAL = pd.Timestamp("2026-11-06")   # last close of the first signal week
HISTORY_START = "2012-01-01"
START_CAPITAL = 10_000.0
SLIPPAGE_BPS = 5.0          # per side, on absolute traded value
COMMISSION = 0.0
CASH_YIELD = 0.0
POSITION_CAP = 0.20         # applies to A and B; inert under equal weighting
SMA_WINDOW = 200            # SPY trend filter, raw closes
DD_MULTIPLE = 1.5           # max drawdown allowance vs SPY

STRATEGIES = {
    "A": dict(name="A. Weekly trend", schedule="W", top_n=5,
              lookback="12w", cap=True, spy_filter=True),
    "B": dict(name="B. Monthly momentum", schedule="M", top_n=10,
              lookback="12m_skip1", cap=True, spy_filter=False),
    "C": dict(name="C. Aggressive momentum", schedule="M", top_n=3,
              lookback="12m_skip1", cap=False, spy_filter=False),
}

ROOT = Path(__file__).resolve().parent
DATA, LEDGERS, LOGS, REPORTS = (ROOT / d for d in ("data", "ledgers", "logs", "reports"))
for _d in (DATA, LEDGERS, LOGS, REPORTS):
    _d.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def fetch() -> dict[str, pd.DataFrame]:
    import yfinance as yf

    tickers = UNIVERSE + [BENCHMARK]
    raw = yf.Tickers(" ".join(tickers)).history(
        start=HISTORY_START, auto_adjust=False, actions=True, timeout=90, progress=False
    )
    out = {}
    for field in ("Open", "Close", "Dividends"):
        df = raw[field].copy()
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        out[field] = df.reindex(columns=tickers).sort_index()
    missing = [t for t in tickers if out["Close"][t].notna().sum() == 0]
    if missing:
        raise SystemExit(f"No data returned for: {missing}")
    return out


def total_return_indices(px: dict[str, pd.DataFrame]):
    """Per-asset total-return indices, close-marked and open-marked."""
    close, open_, div = px["Close"], px["Open"], px["Dividends"].fillna(0.0)
    cal = close[BENCHMARK].dropna().index              # SPY defines the calendar
    tr_c, tr_o = {}, {}
    for tk in close.columns:
        c = close[tk].dropna()
        if len(c) < 2:
            continue
        d = div[tk].reindex(c.index).fillna(0.0)
        o = open_[tk].reindex(c.index)
        tr = 100.0 * ((c + d) / c.shift(1)).fillna(1.0).cumprod()
        tr_c[tk] = tr.reindex(cal).ffill(limit=5)
        tr_o[tk] = (tr.shift(1) * o / c.shift(1)).reindex(cal).ffill(limit=5)
    cols = list(close.columns)
    return (pd.DataFrame(tr_c).reindex(columns=cols),
            pd.DataFrame(tr_o).reindex(columns=cols), cal)


def period_ends(cal: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    """Last trading day of every week (ISO) or calendar month present in cal."""
    if freq == "W":
        keys = [d.isocalendar()[:2] for d in cal]
    else:
        keys = [(d.year, d.month) for d in cal]
    last: dict = {}
    for k, d in zip(keys, cal):
        last[k] = d
    return pd.DatetimeIndex(sorted(last.values()))


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------
def momentum_scores(tr: pd.DataFrame, sig_date: pd.Timestamp, lookback: str,
                    ends: pd.DatetimeIndex) -> pd.Series:
    past = ends[ends <= sig_date]
    if lookback == "12w":
        if len(past) < 13:
            return pd.Series(np.nan, index=UNIVERSE)
        now, then = past[-1], past[-13]
    elif lookback == "12m_skip1":
        if len(past) < 14:
            return pd.Series(np.nan, index=UNIVERSE)
        now, then = past[-2], past[-14]            # exclude the most recent month
    else:
        raise ValueError(lookback)
    a, b = tr.loc[now, UNIVERSE], tr.loc[then, UNIVERSE]
    return (a / b - 1.0).where(a.notna() & b.notna() & (b > 0))


def spy_risk_on(close: pd.Series, sig_date: pd.Timestamp) -> tuple[bool, float, float]:
    hist = close.loc[:sig_date].dropna()
    if len(hist) < SMA_WINDOW:
        return False, float("nan"), float("nan")
    px, sma = float(hist.iloc[-1]), float(hist.iloc[-SMA_WINDOW:].mean())
    return px > sma, px, sma


def target_weights(code: str, tr: pd.DataFrame, spy_close: pd.Series,
                   sig_date: pd.Timestamp, ends: pd.DatetimeIndex):
    cfg = STRATEGIES[code]
    if cfg["spy_filter"]:
        on, px, sma = spy_risk_on(spy_close, sig_date)
        if not on:
            return {}, f"RISK-OFF: SPY {px:.2f} <= 200d SMA {sma:.2f} -> 100% cash", []
    sc = momentum_scores(tr, sig_date, cfg["lookback"], ends).dropna()
    if sc.empty:
        return {}, "no ranking available -> cash", []
    ranked = sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[: cfg["top_n"]]
    picks = [t for t, _ in ranked]
    w = {t: 1.0 / len(picks) for t in picks}
    note = ""
    if cfg["cap"] and any(v > POSITION_CAP + 1e-12 for v in w.values()):
        w = {t: min(v, POSITION_CAP) for t, v in w.items()}
        tot = sum(w.values())
        w = {t: v / tot for t, v in w.items()}
        note = "20% cap engaged; "
    detail = [dict(ticker=t, score=round(float(s), 4), weight=round(w[t], 4)) for t, s in ranked]
    note += "top %d: %s" % (len(picks), ", ".join(f"{t} {s:+.1%}" for t, s in ranked))
    return w, note, detail


# ---------------------------------------------------------------------------
# Ledger replay
# ---------------------------------------------------------------------------
def execute(cash: float, units: dict, tr_open_row: pd.Series, weights: dict):
    """Rebalance at the open; 5bp slippage on absolute traded value, paid from cash."""
    fee = SLIPPAGE_BPS / 10_000.0
    held = {t: u * float(tr_open_row[t]) for t, u in units.items() if u > 0}
    equity = cash + sum(held.values())
    names = sorted(set(held) | set(weights))

    investable, tgt, cost = equity, {}, 0.0
    for _ in range(3):                                   # converge targets net of cost
        tgt = {t: investable * weights.get(t, 0.0) for t in names}
        traded = sum(abs(tgt[t] - held.get(t, 0.0)) for t in names)
        n_tr = sum(1 for t in names if abs(tgt[t] - held.get(t, 0.0)) > 1e-9)
        cost = traded * fee + COMMISSION * n_tr
        investable = equity - cost

    trades, new_units = [], {}
    for t in names:
        delta = tgt[t] - held.get(t, 0.0)
        if abs(delta) > 1e-9:
            trades.append(dict(ticker=t, side="BUY" if delta > 0 else "SELL",
                               value=round(abs(delta), 2),
                               price=round(float(tr_open_row[t]), 4)))
        if tgt[t] > 1e-9:
            new_units[t] = tgt[t] / float(tr_open_row[t])
    new_cash = equity - sum(tgt.values()) - cost
    return new_cash, new_units, trades, cost


def replay(code, tr_c: pd.DataFrame, tr_o: pd.DataFrame,
           spy_close: pd.Series, cal: pd.DatetimeIndex) -> dict:
    """code None -> SPY buy-and-hold benchmark; otherwise 'A' / 'B' / 'C'."""
    future = cal[cal > START_SIGNAL]
    if len(future) == 0:
        return dict(error="no trading session yet after the start signal")
    first_fill = future[0]

    weekly, monthly = period_ends(cal, "W"), period_ends(cal, "M")
    if code is None:
        ends, native = weekly, pd.DatetimeIndex([])
        wfun = lambda d: ({BENCHMARK: 1.0}, "buy and hold SPY", [])
    else:
        ends = monthly if STRATEGIES[code]["schedule"] == "M" else weekly
        # drop the final period: it is still open, so it is not a signal yet
        complete = ends[:-1]
        native = complete[complete > START_SIGNAL]
        wfun = lambda d: target_weights(code, tr_c, spy_close, d, ends)
    sig_dates = set(native)

    cash, units = START_CAPITAL, {}
    w0, note0, det0 = wfun(START_SIGNAL)
    pending = (w0, START_SIGNAL)
    decisions = [dict(signal_date=str(START_SIGNAL.date()), note=note0, ranking=det0)]
    curve, trade_log, costs = [], [], 0.0

    for t in cal[cal >= first_fill]:
        if pending is not None:
            row = tr_o.loc[t]
            need = sorted(set(pending[0]) | set(units))
            if row.reindex(need).isna().any():
                row = tr_c.loc[t]                        # missing open -> mark at close
            cash, units, done, cost = execute(cash, units, row, pending[0])
            costs += cost
            for x in done:
                trade_log.append(dict(fill_date=str(t.date()),
                                      signal_date=str(pending[1].date()), **x))
            pending = None

        mark = tr_c.loc[t]
        equity = cash + sum(u * float(mark[tk]) for tk, u in units.items())
        curve.append((t, equity, cash, dict(units)))

        if t in sig_dates:
            w, note, det = wfun(t)
            pending = (w, t)
            decisions.append(dict(signal_date=str(t.date()), note=note, ranking=det))

    idx = pd.DatetimeIndex([c[0] for c in curve])
    eq = pd.Series([c[1] for c in curve], index=idx, name="equity")
    last_mark = tr_c.loc[idx[-1]]
    holdings = {tk: round(u * float(last_mark[tk]), 2) for tk, u in sorted(curve[-1][3].items())}
    return dict(equity=eq, cash=round(curve[-1][2], 2), holdings=holdings,
                trades=trade_log, decisions=decisions, costs=round(costs, 2),
                first_fill=idx[0], pending=pending[0] if pending else None)


# ---------------------------------------------------------------------------
# Metrics and verdict
# ---------------------------------------------------------------------------
def window_stats(eq: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    w = eq.loc[(eq.index >= start) & (eq.index <= end)]
    if len(w) < 2:
        return dict(ret=float("nan"), maxdd=float("nan"), days=len(w))
    ret = float(w.iloc[-1] / w.iloc[0] - 1.0)
    dd = abs(float((w / w.cummax() - 1.0).min()))
    return dict(ret=ret, maxdd=dd, days=int(len(w)))


def verdict(results: dict, spy: dict, first_fill: pd.Timestamp,
            today: pd.Timestamp) -> dict:
    six = first_fill + pd.DateOffset(months=6)
    twelve = first_fill + pd.DateOffset(months=12)
    months = (today - first_fill).days / 30.4375
    out = dict(months_elapsed=round(months, 2), first_fill=str(first_fill.date()),
               six_month_date=str(six.date()), twelve_month_date=str(twelve.date()))

    if today < six:
        out["status"] = "TOO EARLY"
        out["detail"] = (f"{months:.1f} of 6 months elapsed. First verdict "
                         f"{six.date()}, final verdict {twelve.date()}.")
        return out

    p1_spy = window_stats(spy["equity"], first_fill, six)
    quals = []
    for code, r in results.items():
        s = window_stats(r["equity"], first_fill, six)
        if s["maxdd"] <= DD_MULTIPLE * p1_spy["maxdd"] + 1e-12:
            quals.append((code, s))
    best = max(quals, key=lambda kv: kv[1]["ret"]) if quals else None

    lk = LEDGERS / "leader.json"
    if lk.exists():
        locked = json.loads(lk.read_text(encoding="utf-8"))
    else:
        locked = dict(
            leader=best[0] if best else None,
            locked_on=str(six.date()),
            period1_spy=p1_spy,
            period1_leader=best[1] if best else None,
            qualified=[c for c, _ in quals],
            phase1_verdict=("LEADER" if best and best[1]["ret"] > p1_spy["ret"] else "FAILED"),
        )
        lk.write_text(json.dumps(locked, indent=2, default=str), encoding="utf-8")
    out["leader_lock"] = locked

    if locked["phase1_verdict"] == "FAILED" or not locked["leader"]:
        out["status"] = "FAILED"
        out["detail"] = ("At 6 months no strategy met the drawdown constraint, or the "
                         "qualifying leader did not beat SPY after costs.")
        return out

    code = locked["leader"]
    if today < twelve:
        s2 = window_stats(results[code]["equity"], six, min(today, twelve))
        b2 = window_stats(spy["equity"], six, min(today, twelve))
        out["status"] = f"LEADER = {code}, months 7-12 in progress"
        out["detail"] = (f"Leader {code} {s2['ret']:+.2%} vs SPY {b2['ret']:+.2%} so far in "
                         f"the judging window; drawdown {s2['maxdd']:.2%} against an "
                         f"allowance of {DD_MULTIPLE * b2['maxdd']:.2%}.")
        return out

    s2 = window_stats(results[code]["equity"], six, twelve)
    b2 = window_stats(spy["equity"], six, twelve)
    beat = s2["ret"] > b2["ret"]
    dd_ok = s2["maxdd"] <= DD_MULTIPLE * b2["maxdd"] + 1e-12
    out["status"] = "PASSED" if (beat and dd_ok) else "FAILED"
    out["detail"] = (f"Leader {code} months 7-12: {s2['ret']:+.2%} vs SPY {b2['ret']:+.2%} "
                     f"({'beat' if beat else 'did not beat'}); drawdown {s2['maxdd']:.2%} "
                     f"vs allowance {DD_MULTIPLE * b2['maxdd']:.2%} "
                     f"({'ok' if dd_ok else 'breached'}).")
    out["caveat"] = ("A pass may still be luck. One 12-month forward window on one "
                     "universe does not prove future profits.")
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def build_report(results: dict, spy: dict, vd: dict, px: dict,
                 cal: pd.DatetimeIndex, data_hash: str) -> str:
    ff = spy["first_fill"]
    last = spy["equity"].index[-1]
    rows = []
    spy_full = window_stats(spy["equity"], ff, last)

    def line(label, r, stats):
        eq = float(r["equity"].iloc[-1])
        allow = DD_MULTIPLE * spy_full["maxdd"]
        ok = "-" if label == "SPY (benchmark)" else ("PASS" if stats["maxdd"] <= allow + 1e-12 else "BREACH")
        return (f"| {label} | ${eq:,.2f} | {stats['ret']:+.2%} | {stats['maxdd']:.2%} | "
                f"{ok} | ${r['costs']:,.2f} | {len(r['trades'])} |")

    for code in ("A", "B", "C"):
        r = results[code]
        rows.append(line(STRATEGIES[code]["name"], r, window_stats(r["equity"], ff, last)))
    rows.append(line("SPY (benchmark)", spy, spy_full))

    hold_blocks = []
    for code in ("A", "B", "C"):
        r = results[code]
        h = r["holdings"]
        tot = sum(h.values()) + r["cash"]
        if h:
            body = "\n".join(f"  - {tk}: ${v:,.2f} ({v / tot:.1%})" for tk, v in h.items())
        else:
            body = "  - (no positions)"
        hold_blocks.append(
            f"**{STRATEGIES[code]['name']}** — cash ${r['cash']:,.2f}\n{body}\n\n"
            f"  Latest signal ({r['decisions'][-1]['signal_date']}): {r['decisions'][-1]['note']}")

    weekly, monthly = period_ends(cal, "W"), period_ends(cal, "M")
    md = f"""# Momentum Lab — Report

**Run:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Data through:** {last.date()}  |  **First fill:** {ff.date()}  |  **Data fingerprint:** `{data_hash[:16]}`
**Universe:** {len(UNIVERSE)} ETFs (frozen)  |  **Costs:** {SLIPPAGE_BPS:.0f}bp/side, $0 commission, fills at next open

## VERDICT: {vd['status']}

{vd['detail']}

{vd.get('caveat', '')}

- 6-month verdict date: **{vd['six_month_date']}**
- 12-month verdict date: **{vd['twelve_month_date']}**
- Elapsed: **{vd['months_elapsed']} months**

## Side by side (since first fill, after costs)

| Strategy | Equity | Total return | Max drawdown | DD vs 1.5x SPY | Costs paid | Trades |
|---|---|---|---|---|---|---|
{chr(10).join(rows)}

Drawdown allowance this window: **{DD_MULTIPLE * spy_full['maxdd']:.2%}** (1.5 x SPY's {spy_full['maxdd']:.2%}).
No strategy is ever dropped from this table, including the losers.

## Current positions

{chr(10).join(hold_blocks)}

**SPY benchmark** — ${float(spy['equity'].iloc[-1]):,.2f}, held since {ff.date()}.

## Next scheduled signals

- Strategy A (weekly): next week-end close after {last.date()}
- Strategies B and C (monthly): next month-end close after {last.date()}
- Most recent completed week end: {weekly[-2].date() if len(weekly) > 1 else 'n/a'}
- Most recent completed month end: {monthly[-2].date() if len(monthly) > 1 else 'n/a'}

*Rules are frozen in RULES.md. Strategy D (Claude picks) is not enabled; see section 8.*
"""
    return md


SHORT = {"A": "Strategy A", "B": "Strategy B", "C": "Strategy C", "SPY": "SPY"}


def write_dashboard(payload: dict) -> None:
    """Regenerate the self-contained dashboard with this run's data embedded."""
    tpl = ROOT / "dashboard_template.html"
    if not tpl.exists():
        return
    html = tpl.read_text(encoding="utf-8").replace(
        "__MOMENTUM_DATA__", json.dumps(payload, default=str))
    (ROOT / "dashboard.html").write_text(html, encoding="utf-8")


def dashboard_payload_pending(locked: dict, cal, fingerprint: str) -> dict:
    six = START_SIGNAL + pd.DateOffset(months=6)
    twelve = START_SIGNAL + pd.DateOffset(months=12)
    series = {}
    for code in ("A", "B", "C"):
        series[code] = dict(
            name=STRATEGIES[code]["name"], short=SHORT[code], equity=START_CAPITAL,
            ret=None, maxdd=None, dd_ok=None, costs=0.0, trades=0, cash=0.0,
            holdings={k: round(v, 6) for k, v in locked[code]["weights"].items()},
            latest_note=locked[code]["note"])
    series["SPY"] = dict(name="SPY (benchmark)", short="SPY", equity=START_CAPITAL,
                         ret=None, maxdd=None, dd_ok=None, costs=0.0, trades=0,
                         cash=0.0, holdings={}, latest_note="buy and hold SPY")
    return dict(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        data_through=str(cal[-1].date()), fingerprint=fingerprint, phase="pending",
        status="TOO EARLY",
        detail=(f"Not trading yet. The initial signal is locked at the {START_SIGNAL.date()} "
                "close and fills at the next session's open, which has not printed. "
                "Each ledger holds its full $10,000 in cash."),
        caveat="", first_fill=None, months_elapsed=None,
        six_month_date=str(six.date()), twelve_month_date=str(twelve.date()),
        dd_allowance=None, spy_maxdd=None, series=series, curves=None)


def dashboard_payload_live(results: dict, spy: dict, vd: dict, cal, fingerprint: str) -> dict:
    ff, last = spy["first_fill"], spy["equity"].index[-1]
    spy_full = window_stats(spy["equity"], ff, last)
    allow = DD_MULTIPLE * spy_full["maxdd"]
    series = {}
    for code in ("A", "B", "C"):
        r = results[code]
        s = window_stats(r["equity"], ff, last)
        series[code] = dict(
            name=STRATEGIES[code]["name"], short=SHORT[code],
            equity=round(float(r["equity"].iloc[-1]), 2), ret=s["ret"], maxdd=s["maxdd"],
            dd_ok=bool(s["maxdd"] <= allow + 1e-12), costs=r["costs"],
            trades=len(r["trades"]), cash=r["cash"], holdings=r["holdings"],
            latest_note=r["decisions"][-1]["note"])
    series["SPY"] = dict(
        name="SPY (benchmark)", short="SPY", equity=round(float(spy["equity"].iloc[-1]), 2),
        ret=spy_full["ret"], maxdd=spy_full["maxdd"], dd_ok=None, costs=spy["costs"],
        trades=len(spy["trades"]), cash=spy["cash"], holdings=spy["holdings"],
        latest_note="buy and hold SPY")

    eq = pd.DataFrame({c: results[c]["equity"] for c in ("A", "B", "C")})
    eq["SPY"] = spy["equity"]
    curves = dict(dates=[str(d.date()) for d in eq.index])
    for k in ("A", "B", "C", "SPY"):
        curves[k] = [None if pd.isna(v) else round(float(v), 2) for v in eq[k]]
    return dict(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        data_through=str(last.date()), fingerprint=fingerprint, phase="running",
        status=vd["status"], detail=vd.get("detail", ""), caveat=vd.get("caveat", ""),
        first_fill=str(ff.date()), months_elapsed=vd.get("months_elapsed"),
        six_month_date=vd["six_month_date"], twelve_month_date=vd["twelve_month_date"],
        dd_allowance=allow, spy_maxdd=spy_full["maxdd"], series=series, curves=curves)


def pending_start_report(tr_c, spy_close, cal, fingerprint) -> str:
    """Before the first fill exists: lock and publish the committed initial targets."""
    weekly, monthly = period_ends(cal, "W"), period_ends(cal, "M")
    locked, blocks = {}, []
    for code in ("A", "B", "C"):
        ends = monthly if STRATEGIES[code]["schedule"] == "M" else weekly
        w, note, det = target_weights(code, tr_c, spy_close, START_SIGNAL, ends)
        locked[code] = dict(weights={k: round(v, 6) for k, v in w.items()},
                            note=note, ranking=det)
        body = ("\n".join(f"  - {d['ticker']}: {d['weight']:.1%} "
                          f"(momentum {d['score']:+.2%})" for d in det)
                or "  - 100% cash")
        blocks.append(f"**{STRATEGIES[code]['name']}**\n{body}")
    on, px_, sma = spy_risk_on(spy_close, START_SIGNAL)
    locked["SPY"] = dict(weights={BENCHMARK: 1.0}, note="buy and hold SPY", ranking=[])
    locked["_meta"] = dict(signal_date=str(START_SIGNAL.date()),
                           committed_at=datetime.now(timezone.utc).isoformat(),
                           data_through=str(cal[-1].date()), fingerprint=fingerprint,
                           spy_close=round(px_, 2), spy_sma200=round(sma, 2), risk_on=bool(on))
    (LEDGERS / "pending_start.json").write_text(
        json.dumps(locked, indent=2, default=str), encoding="utf-8")

    return f"""# Momentum Lab — Report

**Run:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Data through:** {cal[-1].date()}  |  **Data fingerprint:** `{fingerprint[:16]}`

## VERDICT: TOO EARLY

The test has not started trading yet. The initial signal is locked at the
**{START_SIGNAL.date()}** close and fills at the **next session's open**, which has
not printed yet. Each ledger holds its full $10,000 in cash until then.

The targets below are committed and timestamped *before* the fill, in
`ledgers/pending_start.json`. They cannot be revised.

- SPY trend filter at the signal: close **{px_:.2f}** vs 200-day SMA **{sma:.2f}** -> **{'RISK-ON' if on else 'RISK-OFF'}**

## Committed initial targets

{chr(10).join(blocks)}

**SPY benchmark** — $10,000 into SPY at the same open, dividends reinvested, held for the full test.

## Side by side (since first fill, after costs)

| Strategy | Equity | Total return | Max drawdown | DD vs 1.5x SPY | Costs paid | Trades |
|---|---|---|---|---|---|---|
| A. Weekly trend | $10,000.00 | — | — | — | $0.00 | 0 |
| B. Monthly momentum | $10,000.00 | — | — | — | $0.00 | 0 |
| C. Aggressive momentum | $10,000.00 | — | — | — | $0.00 | 0 |
| SPY (benchmark) | $10,000.00 | — | — | — | $0.00 | 0 |

No strategy is ever dropped from this table, including the losers.

*Rules are frozen in RULES.md. Strategy D (Claude picks) is not enabled; see section 8.*
"""


def main():
    px = fetch()
    tr_c, tr_o, cal = total_return_indices(px)
    spy_close = px["Close"][BENCHMARK]

    fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(px["Close"].round(6).ffill().fillna(-1)).values.tobytes()
    ).hexdigest()

    px["Close"].to_csv(DATA / "close.csv")
    px["Open"].to_csv(DATA / "open.csv")
    px["Dividends"].fillna(0.0).to_csv(DATA / "dividends.csv")

    if len(cal[cal > START_SIGNAL]) == 0:
        md = pending_start_report(tr_c, spy_close, cal, fingerprint)
        (REPORTS / "report.md").write_text(md, encoding="utf-8")
        locked = json.loads((LEDGERS / "pending_start.json").read_text(encoding="utf-8"))
        write_dashboard(dashboard_payload_pending(locked, cal, fingerprint))
        with (LOGS / "runs.log").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()}\tdata_through={cal[-1].date()}"
                    f"\tfingerprint={fingerprint[:16]}\tverdict=AWAITING_FIRST_FILL\n")
        print(md)
        return

    results = {c: replay(c, tr_c, tr_o, spy_close, cal) for c in ("A", "B", "C")}
    spy = replay(None, tr_c, tr_o, spy_close, cal)
    for name, r in list(results.items()) + [("SPY", spy)]:
        if "error" in r:
            raise SystemExit(f"{name}: {r['error']}")

    # Integrity: the realised initial allocation must match what was committed
    # and timestamped before the first fill ever printed.
    ps = LEDGERS / "pending_start.json"
    if ps.exists():
        committed = json.loads(ps.read_text(encoding="utf-8"))
        drift = []
        for code in ("A", "B", "C"):
            want = {k: round(v, 4) for k, v in committed.get(code, {}).get("weights", {}).items()}
            d0 = results[code]["decisions"][0]
            got = {d["ticker"]: round(d["weight"], 4) for d in d0.get("ranking", [])}
            if want != got:
                drift.append(f"{code}: committed {want} != replayed {got}")
        path = LEDGERS / "integrity.json"
        path.write_text(json.dumps(dict(
            checked_at=datetime.now(timezone.utc).isoformat(),
            committed_at=committed.get("_meta", {}).get("committed_at"),
            start_signal=committed.get("_meta", {}).get("signal_date"),
            status="OK" if not drift else "DRIFT", drift=drift), indent=2), encoding="utf-8")
        if drift:
            print("!! INITIAL ALLOCATION DRIFT vs pre-committed targets:")
            for line_ in drift:
                print("   " + line_)

    today = cal[-1]
    vd = verdict(results, spy, spy["first_fill"], today)

    # persist
    curves = pd.DataFrame({c: results[c]["equity"] for c in ("A", "B", "C")})
    curves["SPY"] = spy["equity"]
    curves.round(4).to_csv(LEDGERS / "equity_curves.csv")
    for code in ("A", "B", "C"):
        r = results[code]
        (LEDGERS / f"ledger_{code}.json").write_text(json.dumps(dict(
            strategy=STRATEGIES[code]["name"], cash=r["cash"], holdings=r["holdings"],
            costs=r["costs"], trades=r["trades"], decisions=r["decisions"],
            equity_last=round(float(r["equity"].iloc[-1]), 2),
        ), indent=2, default=str), encoding="utf-8")
    (LEDGERS / "ledger_SPY.json").write_text(json.dumps(dict(
        strategy="SPY benchmark", cash=spy["cash"], holdings=spy["holdings"],
        costs=spy["costs"], trades=spy["trades"],
        equity_last=round(float(spy["equity"].iloc[-1]), 2)), indent=2, default=str), encoding="utf-8")
    (LEDGERS / "verdict.json").write_text(json.dumps(vd, indent=2, default=str), encoding="utf-8")

    with (LOGS / "runs.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}\tdata_through={cal[-1].date()}"
                f"\tfingerprint={fingerprint[:16]}\tverdict={vd['status']}\n")

    write_dashboard(dashboard_payload_live(results, spy, vd, cal, fingerprint))
    md = build_report(results, spy, vd, px, cal, fingerprint)
    (REPORTS / "report.md").write_text(md, encoding="utf-8")
    (REPORTS / f"report_{cal[-1].date()}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
