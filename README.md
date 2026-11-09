# Momentum Lab

A 12-month paper-trading forward test: three momentum strategies, each with its own
$10,000 fake-USD ledger, against a $10,000 buy-and-hold SPY benchmark.

### → Live dashboard: https://mniel135-eng.github.io/momentum-lab/

Updates itself every weekday at 23:00 UTC. Nothing needs to be running on your machine.

**The rules are frozen in [RULES.md](RULES.md) and must not be edited while the test runs.**

- Start signal: **2026-11-06** close
- First fill: the next session's **open** after that
- 6-month verdict: ~2027-05
- 12-month verdict: ~2027-11

## Run it

PowerShell (note the leading `&` — PowerShell will not run a quoted path without it):

```powershell
& "C:\Users\danit\.claude\sessions\momentum-lab\.venv\Scripts\python.exe" "C:\Users\danit\.claude\sessions\momentum-lab\lab.py"
```

Git Bash:

```bash
"/c/Users/danit/.claude/sessions/momentum-lab/.venv/Scripts/python.exe" "/c/Users/danit/.claude/sessions/momentum-lab/lab.py"
```

Or just `run.cmd`. The authoritative schedule is the GitHub Actions workflow, which
runs weekdays at 23:00 UTC in the cloud. No local scheduled task is used.

Every run refetches the full price history and **replays all ledgers from scratch**.
Nothing is mutated incrementally. That means:

- Running it twice changes nothing (idempotent).
- Missing a week, or a month, changes nothing — the next run backfills it.
- **Run frequency has zero effect on results**, only on how fresh the report is.
- A later data re-adjustment by the provider cannot corrupt a saved position.

## Read the results

| File | What it holds |
|---|---|
| `reports/report.md` | Current side-by-side table, verdict, positions. **Start here.** |
| `reports/report_<date>.md` | Dated snapshot of each run |
| `ledgers/equity_curves.csv` | Daily equity for A, B, C and SPY |
| `ledgers/ledger_<X>.json` | Full trade log, every rebalance decision with its ranking |
| `ledgers/pending_start.json` | Initial targets, committed and timestamped **before** the first fill |
| `ledgers/integrity.json` | Confirms the realised first fill matched those committed targets |
| `ledgers/leader.json` | The 6-month leader, written once and never rewritten |
| `ledgers/verdict.json` | Machine-readable current verdict |
| `data/*.csv` | Raw closes, opens and dividends used by the latest run |
| `logs/runs.log` | One line per run: data date, data fingerprint, verdict |
| `logs/last_run.log` | Console output of the most recent scheduled run |

## Scoring, in short

Primary metric is total return after costs, but a strategy only qualifies if its max
drawdown stays within **1.5x SPY's** over the same window. At 6 months the best
qualifying strategy is locked as LEADER; it is then judged **only** on months 7-12.
All four ledgers run to the end regardless. Nothing is ever dropped.

## Known honest limitations

- Fills use the next session's open with 5bp slippage. Real fills vary.
- Cash earns 0%, which handicaps strategy A during risk-off stretches.
- Dividends are reinvested at the ex-date close, not the later pay date.
- Yahoo Finance is the single data source; the per-run fingerprint in `logs/runs.log`
  lets you detect if history was silently restated.
- One 12-month forward window on one 30-ETF universe is a smoke test, not evidence.
  A PASS may still be luck.

## Strategy D (Claude picks)

Not enabled. See RULES.md section 8 for why, and note that section 5 freezes the
strategy set before the start, so it cannot be added once the first fill is final.
