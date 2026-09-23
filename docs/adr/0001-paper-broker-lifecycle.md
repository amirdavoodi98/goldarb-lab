# ADR 0001 — Local paper broker lifecycle and execution pipeline

## Status

Accepted (2026-09-23)

## Context

The local paper broker must support Write-Strategy-Once across backtest and live
simulation, while keeping matching, portfolio, and persistence separable.

## Decision 1 — Order lifecycle

- `CREATED` is a first-class, persistable state.
- Primary transitions from creation:
  - `CREATED → REJECTED` (validation / early reject)
  - `CREATED → ACCEPTED` (accepted after submit path)
- `SubmitLatency` is applied between the submit request and order activation
  (`active_at`). Until activation, the order remains `CREATED`.
- Only `OrderManager` may mutate order status / apply fills to order state.
- `MatchingEngine` proposes fills (`MatchResult` / `raw_match_price`) and never
  mutates orders, accounts, or portfolios.

Canonical statuses:

`CREATED`, `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`,
`CANCELLED`, `REJECTED`, `EXPIRED`.

Legacy alias: `OrderStatus.OPEN` equals `ACCEPTED` for Strategy / older tests.

Working orders: `ACCEPTED`, `PARTIALLY_FILLED`, `CANCEL_PENDING`
(late fills may still apply in `CANCEL_PENDING`).

## Decision 2 — Execution pipeline (order path)

```text
Order (CREATED → ACCEPTED after SubmitLatency)
  → MatchingEngine        # raw_match_price + quantity
  → SlippageModel         # final execution price
  → FeeModel
  → PortfolioService      # ledger deltas (cash / position)
  → OrderManager.commit   # fills + order status + events
```

Matching produces `raw_match_price`. Slippage alone decides the execution
`price` written on the Fill.

Fee amount on the fill uses **account.fee_rate** (ledger truth) so it stays
consistent with `create_account(..., fee_rate=...)`. The broker's `FeeModel`
is the default when creating accounts without an explicit rate.

## Conflict with SimulationLoop snapshot transforms

**Resolved:** `SimulationLoop.process` passes market snapshots through unchanged.
Execution slippage/latency are configured on `LocalPaperBroker` via
`configure_execution` / constructor (order-path pipeline only).

`NoOpMarketIngress` is an alias of `ServerSideExecution` for remote modes.

## Out of scope (later)

- Full RemoteSimulator redesign
- LiveBroker
- OrderBookMatching
- LastPriceMatching (protocol slot only / thin stub optional)
