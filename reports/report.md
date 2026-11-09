# Momentum Lab — Report

**Run:** 2026-11-09 09:31 UTC
**Data through:** 2026-11-06  |  **Data fingerprint:** `e86c9a094db7043e`

## VERDICT: TOO EARLY

The test has not started trading yet. The initial signal is locked at the
**2026-11-06** close and fills at the **next session's open**, which has
not printed yet. Each ledger holds its full $10,000 in cash until then.

The targets below are committed and timestamped *before* the fill, in
`ledgers/pending_start.json`. They cannot be revised.

- SPY trend filter at the signal: close **735.29** vs 200-day SMA **730.38** -> **RISK-ON**

## Committed initial targets

**A. Weekly trend**
  - XLV: 20.0% (momentum +10.83%)
  - XLP: 20.0% (momentum +5.33%)
  - DBC: 20.0% (momentum +5.13%)
  - TLT: 20.0% (momentum +0.64%)
  - FXI: 20.0% (momentum +0.17%)
**B. Monthly momentum**
  - XLE: 10.0% (momentum +63.41%)
  - DBC: 10.0% (momentum +51.78%)
  - XLV: 10.0% (momentum +30.29%)
  - IWD: 10.0% (momentum +28.40%)
  - XLB: 10.0% (momentum +25.33%)
  - XLP: 10.0% (momentum +20.45%)
  - XLK: 10.0% (momentum +20.01%)
  - EWJ: 10.0% (momentum +16.17%)
  - IWM: 10.0% (momentum +14.60%)
  - EFA: 10.0% (momentum +13.14%)
**C. Aggressive momentum**
  - XLE: 33.3% (momentum +63.41%)
  - DBC: 33.3% (momentum +51.78%)
  - XLV: 33.3% (momentum +30.29%)

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
