# QPX conversation journal — 2026-09-26

## Live-paper Alpaca SIP authority correction

USER_REQUIREMENT: Correct the deployed live-paper runner from Alpaca IEX to
Alpaca SIP without changing strategy parameters, account identity, simulated
authority, or broker prohibition. SIP must govern decision/exact-causal bars,
indicators, minute-open trades, and marks; IEX fallback is prohibited.

HIGH-RISK DESIGN: The governed paper profile owns provider/feed/fallback. The
real-time causal execution lifecycle is keyed by
`AUTHENTIC_OPEN_THEN_COMPLETED_CLOSE_V1`, not feed name. Successful explicit
SIP responses attest the effective feed and a stable feed fingerprint. A
checksummed in-place contract migration appends audit evidence and preserves
all account fields; pending IEX-derived signals block migration.

VERIFIED_ARTIFACT baseline: state revision 1082, audit sequence 1362/hash
`81b883868ff2d3dc9d1b290b0a986b40c44963e2fee60716efbfe2a0bc7d3631`,
account preservation fingerprint
`b7b39cac1c3afbb8a22a6a93f07d00e5410d25a595212ce97c710bc4189747d1`.
The account has 50 QDTE shares, cash 33.52655000000009, cost basis
1421.0649999999998, zero realized P&L/tax reserve, and no swing/pending entry.

VERIFIED_ARTIFACT provider probe: explicit Alpaca `feed=sip` requests returned
27 completed QDTE 15-minute bars and 100 QDTE trades for 2026-09-25. SIP
entitlement is AVAILABLE; feed fingerprint is
`286377ed5ab5f10fdfc9a31a088134154260ddb1b6cd44153a4b58e5bf4854d9`.
Validated implementation fingerprint is
`8c432c0d1839d786af627fc883209e7ef19bca946de1a7923a2553b0950e17cc`;
the SIP contract fingerprint is
`2725b53986626b500d2a4e9eba7486a662b8ac372c8266cc1cfa88ccfb302842`.

VERIFIED_REPO: focused live-paper/feed/restart/account/scheduler/config tests
passed 97/97. No historical replay or broad suite ran. Next: finish diff and
continuity validation, commit/push explicitly staged files, deploy an isolated
committed release, run the finite in-place authority migration, replace the
old IEX-named supervisor/worker units, and verify after-hours fail-closed state.
