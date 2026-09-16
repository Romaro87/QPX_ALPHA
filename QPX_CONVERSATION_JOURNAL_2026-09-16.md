# QPX conversation journal — 2026-09-16

## 13:34 CDT — proven tax-reserve defect exclusion and correction start

- **USER REQUIREMENT:** Implement the proven high-risk net-realized tax-reserve
  correction, focused tests, accepted `main` push, and a distinct corrected V3
  replay while preserving the exact approved universe and strategy parameters.
- **VERIFIED REPO:** Before work, branch `main`, local `HEAD`, and `origin/main`
  were all `6dcfb702c28ecaea35965ee3da85e16e03e0f0f6`. Existing untracked `runtime/`
  and `ystemctl --user show qpx-clean-v2-dummy-intervention-20260903.timer \\`
  remain user-owned and unstaged.
- **VERIFIED RUNTIME:** Only
  `qpx-v3-reservoir-replay-corrected-20260915.service` was stopped. It had PID
  181490, start time 2026-09-15 17:58:06 CDT, and zero restarts; it stopped at
  2026-09-16 13:34:19 CDT with `Result=success` and exit status 0.
- **VERIFIED ARTIFACT:** Defective run
  `1fbbd3cb80755e4ed8cbe37e05adee1c50b43ab90ff77ff25668197ecbbf8f83`
  is acceptance-excluded. Preserved checksum-valid digests are manifest
  `95b656c657833c669b3316e98fc0d1719f2c7c4ee5e690d7ed6bfba2d96ec80d`,
  preparation checkpoint
  `638f313ed7e388d822a61b3677f165aba9ecb426e73f4017efd694375be740ad`,
  and final replay checkpoint
  `3b552a95e4f793d99ff6d5588658db385f6958fc73cb4deea790ade693b198ce`.
  The 126,857,822,208-byte SQLite cache and its sidecars remain in place.
- **PROVEN CAUSE:** Historical OPEN and CLOSE directly closed positions without
  invoking the governed net-realized tax-reserve reconciliation, trapping
  reserve after cumulative losses and suppressing later deployable-cash sizing.
- **SCOPE:** Correct only matching historical/live accounting omissions and
  exact sizing-rejection persistence, run focused directly affected tests,
  preserve live account continuity, push accepted work, and start a fresh V3
  replay. RVLT/AMMA lifecycle treatment remains unchanged.

## 13:45 CDT — implementation and focused verification complete

- **RISK / DESIGN:** HIGH-risk reviewed design retained existing account owners
  and causal boundaries. The existing configured-rate reserve calculation was
  extracted as one shared balance primitive; the existing historical wrapper
  remains authoritative. Reconciliation is immediate and idempotent, and the
  transfer preserves cash plus reserve.
- **IMPLEMENTED:** Historical OPEN/CLOSE now reconcile directly after a close;
  pending sizing therefore sees released cash. Historical sizing rejection
  persistence uses `_position_size_rejection_diagnostic`. Active IEX
  authentic-OPEN and completed-CLOSE paths share the same live-state close
  accounting and emit `tax_reserve_released` and `required_tax_reserve`.
- **VERIFIED TEST:** `python3 -m unittest -v` over the four directly affected
  modules passed 73/73. `tests/test_qpx_bot_net_realized_tax_reserve_control.py`
  and `tests/test_qpx_bot_portfolio_risk.py` both passed with `PYTHONPATH=.`.
  Changed Python compiled and `git diff --check` passed. No broad suite ran.
- **VERIFIED COVERAGE:** Configured profitable reserve, later-loss release,
  negative cumulative P&L, equity preservation, OPEN/CLOSE timing,
  same-boundary sizing, restart/fingerprint identity, no double release,
  rejection subtypes/reconciliation, duplicate-symbol isolation, exact
  provider-ID marks/exits, and live paper close accounting all passed.
- **LIVE BASELINE:** Active supervised IEX paper state checksum validated at
  revision 134: 50 QDTE shares, QDTE cost `$1,421.065`, cash `$22.275`, zero
  reserve/P&L, no swing positions, no pending entries, simulated only, 90% cap.
- **NEXT EXACT ACTION:** Inspect/stage only intended files, commit and push to
  `main`, verify remote equality, deploy the active paper target without account
  reset, and launch a distinct replay from the beginning.
