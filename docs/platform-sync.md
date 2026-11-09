# Platform API synchronization

The standalone `goldarb-lab` repository is the main SDK and strategy project.
Local workspace used for this sync:
`/home/amir/arbitrage_project/workspace/goldarb-lab`.

The platform's nested `goldarb-lab/` is a smaller compatibility copy. Its version
number and simulation internals must not overwrite this repository's newer
Strategy, runtime, archive, broker and execution APIs.

## 2026-11-01 — 0.9.0

Compared standalone base `3ea8787` (0.8.0) with platform main `a1e82f8` (embedded
SDK 0.5.1). Integrated the published data API additions:

- `client.live.snapshot`, `events` and checkpointed long-poll `subscribe`.
- Provider `source_timestamp`, raw clock, verification status and receipt time
  preserved in the returned observations.
- `client.ml` research experiment helpers on the existing authenticated transport.
- `client.market.ime_daily` sorted history helper; aligned to the actual backend
  maximum of 180 days while retaining `ime_cdc_stats` response compatibility.
- Source-time inspection and HTTPS delivery-age probe examples with offline tests.

Existing `LabClient.login`, fund/market helpers and simulation interfaces remain
available. Existing Strategy runtime feeds keep their current contracts; use
`client.live` explicitly when consuming source-aware provider observations.
No scraping, Django code, database access or production credentials were added.
Local strategy examples, archives and environment files were preserved.

Verification: baseline 183 tests passed / 1 skipped; after sync 197 passed /
1 skipped (optional pyarrow). Ruff passed for all changed/new Python files.
Editable install metadata and package version both report 0.9.0. An offline wheel
build and import/API smoke from outside the checkout passed. Automated tests
used mocked HTTP and did not call the live platform.

## Future platform changes

Compare data API behavior, schemas and tests with the published backend; merge
additively into this client. Preserve the standalone version line and increment
it for new APIs. Avoid bulk replacing the standalone simulation/runtime files
with the smaller embedded copy. Run this repository's full offline test suite
and validate its distributable wheel after each synchronization.
