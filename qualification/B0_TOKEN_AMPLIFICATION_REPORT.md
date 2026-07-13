# B0 token amplification

B0 used 1,472,115 tokens versus 754,751 for STANDARD (+95.1%). It also used
273 versus 229 requests (+19.2%), 83 versus 56 searches (+48.2%), and 1,320.378
versus 1,163.570 seconds (+13.5%).

The receipts support these components:

* **Initial packet exposure:** 488 selected paths, 477 unused. This is a
  measured upper-bound proxy for packet-induced opportunity cost; exact prompt
  token contribution is not isolated in the public report.
* **Post-packet search/expansion:** 29 omitted required paths were later read;
  27/35 cells required unsupplied discovery. This explains additional searches
  and turns, but not a unique token amount.
* **Failure/repair tail:** the largest B0 test-only failure consumed 435,254
  tokens and reached maximum turns. It is included in aggregate cost, not
  silently removed as a runtime outlier.
* **Unresolved:** retained conversation-history tokens, compiler overhead, and
  exact per-read token attribution are not separately identified by this
  study. No unsupported decomposition is presented.

Class totals show concentration in test-only and cross-module tasks: B0 used
546,422 and 274,405 tokens respectively, versus STANDARD 105,824 and 220,485.
