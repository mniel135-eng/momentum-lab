# Momentum Lab — Frozen Rules

**Frozen on:** 2026-11-09. Nothing below may change for the duration of the test.
Signal date for the first entry: **2026-11-06** (last close of that week).
First fill: the next trading session's **open** after 2026-11-06.

---

## 1. Universe (frozen, 30 tickers)

Liquid multi-asset ETFs. Chosen because strategy A's SPY-200-day switch is an
asset-rotation design, data is clean, there is no survivorship bias, and top-10
of 30 is a real selection rather than "hold almost everything".

SPY is deliberately **not** in the universe — it is the benchmark, kept distinct.
Broad equity exposure is still reachable via QQQ / IWM / EFA / EEM / VGK.

| Group | Tickers |
|---|---|
| US sectors (11) | XLK XLF XLV XLE XLI XLP XLY XLU XLB XLRE XLC |
| US broad / style (3) | QQQ IWM IWD |
| International (6) | EFA VGK EWJ EEM EWZ FXI |
| Bonds (7) | TLT IEF SHY LQD HYG TIP EMB |
| Real assets (3) | GLD SLV DBC |

Every ticker has price history well before 2024, so the 13-month lookback is
fully available on day one. A ticker missing any part of its required lookback on
a given signal date is excluded from that date's ranking.

## 2. Data

- Source: Yahoo Finance via the `yfinance` client. Raw OHLC + cash dividends on ex-date.
- Every run refetches the full history and **replays all ledgers from scratch**.
  All strategies are deterministic functions of (data, rules), so replay is
  idempotent, self-backfilling, and immune to later provider re-adjustments.
- A raw snapshot of each run's data is written to `data/` for audit.

## 3. Total return and dividends

For each asset a total-return index is built from raw closes and ex-date dividends:

    TR[0] = 100
    TR[t] = TR[t-1] * (Close[t] + Dividend[t]) / Close[t-1]
    TRopen[t] = TR[t-1] * Open[t] / Close[t-1]

This reinvests each dividend into the paying asset at the ex-date close, with no
transaction cost on the reinvestment itself. Splits cancel out of the ratios.
**The same rule applies to every strategy and to the SPY benchmark.**

All momentum ranking uses TR, so high-yield assets such as TLT are not penalised.

## 4. Fill timing and costs (identical for all ledgers)

- Signal computed from the period's **last close**.
- Filled at the **next trading session's open**.
- **5 basis points** slippage on the absolute dollar value of every trade, both directions.
- **$0** commission.
- Uninvested cash earns **0%**. This is a conservative, deliberate choice: it
  handicaps strategy A during its risk-off stretches in a positive-rate world.

## 5. Strategies — $10,000 fake USD each, separate ledger

**A. Weekly trend.** On the last close of each week, rank the universe by 12-week
TR return (weekly closes, t vs t-12). If SPY's close is above its 200-day simple
moving average of raw closes, hold the top 5 at equal weight; otherwise hold 100% cash.

**B. Monthly momentum.** On the last close of each month, rank by 12-month TR
return excluding the most recent month: TR[m-1] / TR[m-13] - 1, on month-end
closes. Hold the top 10 at equal weight.

**C. Aggressive momentum.** Identical ranking and schedule to B. Hold the top 3
at equal weight. The 20% position cap does not apply.

**D. Claude picks — NOT ENABLED.** See section 8.

**Initial entry.** Every strategy enters at the first fill date using its own
ranking rule evaluated at the 2026-11-06 signal, then follows its native schedule
from there (A weekly, B and C at the next month-end close). Without this, B and C
would sit in cash until 2026-12-01 while A traded, which would not be a fair
side-by-side test.

Ties in any ranking break alphabetically by ticker, so every result is reproducible.

### The 20% position cap

Applied to A and B, not to C. Note that under equal weighting it never binds:
A holds 5 names at exactly 20% each, B holds 10 at 10% each. It is implemented as
a clip-and-renormalise guard and recorded in the logs, but it is inert by construction.

## 6. Benchmark

On the first fill date, $10,000 into SPY at the open under the same 5bp slippage
rule, dividends reinvested per section 3, held untouched for the whole test.

## 7. Scoring

- Primary metric: **total return after costs**.
- Risk constraint: **max drawdown no more than 1.5x SPY's** over the same window.
- Max drawdown = largest peak-to-trough decline of the daily close-marked equity curve.
- Every strategy is shown side by side every run, winners and losers. No strategy
  is ever dropped, disabled, or re-specified mid-test.

### Verdict schedule

- **Before 6 months:** `TOO EARLY`.
- **At 6 months:** among strategies meeting the drawdown constraint, the highest
  total return is locked as `LEADER` (written once to `ledgers/leader.json`, never
  rewritten). If nothing qualifies, or the leader did not beat SPY after costs,
  the verdict is `FAILED`.
- **Months 7-12:** all ledgers keep running; the leader is judged only on this
  later window.
- **At 12 months:** `PASSED` only if the leader beat SPY after costs in months
  7-12 **and** its drawdown in that window was no more than 1.5x SPY's.
  Otherwise `FAILED`.

A pass may still be luck. One 12-month forward window on one universe is not
evidence of future profit.

## 8. Strategy D — why it is off

The spec made D optional and required asking first. The decision was handed back
to me, and a deferral is not authorisation to spend real money on someone's API
account, so D is **excluded for the whole test**. Two further reasons:

1. A/B/C are reproducible forever from frozen rules plus public data. D is not —
   nobody, including the model, can re-derive its picks later.
2. It would break the replay-from-scratch architecture that makes everything else
   auditable, forcing stateful, non-idempotent ledgers.

Because section 5 freezes the strategy set before the start, D cannot be bolted on
later. If it is wanted, it has to be added before the first fill is final.

**Confirmed 2026-11-09, before the first fill:** the decision to leave D off was put
back to the user and affirmed ("Keep D off"). The strategy set for this test is
final at A, B, C and the SPY benchmark. No D ledger exists and none may be added.
