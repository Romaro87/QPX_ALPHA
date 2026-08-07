#!/usr/bin/env python3
from __future__ import annotations

import csv, json, re, shutil, subprocess, sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = ROOT/'qpx_bot/config.py'
RISK = ROOT/'qpx_bot/risk.py'
HIST = ROOT/'qpx_bot/actual_two_year_15m_six.py'
INIT = ROOT/'qpx_bot/__init__.py'
README = ROOT/'qpx_bot/ACTUAL_TWO_YEAR_15M_SIX_README.txt'
BACKUP = ROOT/'backups'/('qpx_v19_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
ORIGINALS: dict[Path, bytes|None] = {}


def sh(*args: str, check: bool=True):
    print('$', ' '.join(args))
    return subprocess.run(args, cwd=ROOT, check=check)


def keep(path: Path):
    if path in ORIGINALS:
        return
    ORIGINALS[path] = path.read_bytes() if path.exists() else None
    if path.exists():
        dst = BACKUP/path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)


def restore():
    print('Restoring V19 target files...')
    for path, data in ORIGINALS.items():
        if data is None:
            if path.exists(): path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n == 0 and new in text:
        return text
    if n != 1:
        raise RuntimeError(f'{label}: expected one old match, found {n}')
    return text.replace(old, new, 1)


def patch_code():
    for p in (CFG, RISK, HIST, INIT, README): keep(p)

    s = CFG.read_text(encoding='utf-8')
    s = once(s,
        '    risk_per_trade: float = 0.01\n    maximum_active_portfolio_risk: float = 0.06\n',
        '    risk_per_trade: float = 0.03\n    maximum_active_portfolio_risk: float = 0.10\n',
        'BotConfig risk defaults')
    CFG.write_text(s, encoding='utf-8')

    s = RISK.read_text(encoding='utf-8')
    s = once(s,
        '            blocked_reason="The 6% active-risk cap is full.",\n',
        '            blocked_reason=(\n                f"The {config.maximum_active_portfolio_risk:.0%} "\n                "active-risk cap is full."\n            ),\n',
        'dynamic risk-cap message')
    RISK.write_text(s, encoding='utf-8')

    s = HIST.read_text(encoding='utf-8')
    old = ('    else:\n        entry_gap_atr_limit = (\n            policy.maximum_gap_atr_multiple\n        )\n\n'
           '    config.validate()\n    kelly_enabled = (\n')
    new = ('    else:\n        entry_gap_atr_limit = (\n            policy.maximum_gap_atr_multiple\n        )\n\n'
           '    if (\n        risk_profile\n        == FIXED_ONE_PERCENT_RISK_PROFILE\n    ):\n'
           '        config = replace(\n            config,\n            risk_per_trade=0.01,\n'
           '            maximum_active_portfolio_risk=0.06,\n        )\n\n'
           '    config.validate()\n    kelly_enabled = (\n')
    s = once(s, old, new, 'historical fixed 1%/6% override')
    HIST.write_text(s, encoding='utf-8')

    s = INIT.read_text(encoding='utf-8')
    s = once(s, '__version__ = "1.32.0"', '__version__ = "1.33.0"', 'version')
    INIT.write_text(s, encoding='utf-8')

    marker = 'V19 entry-edge stability + 3% / 10% default-risk update'
    s = README.read_text(encoding='utf-8')
    if marker not in s:
        s += f'''\n\n{marker}\n{'-'*len(marker)}\nDefault BotConfig risk is now 3% per trade and 10% aggregate active risk.\nThe named FIXED_1PCT_NO_KELLY_RESEARCH historical profile remains explicitly\n1% / 6% so V14-V18 fixed-window results remain reproducible. Kelly behavior\nis unchanged. V19 also reports six-month chronological stability of the\nexisting V16/V17 baseline trades by symbol, trigger combination, individual\ntrigger, and VIX regime. This is in-sample diagnostic research, not a claim\nthat higher risk improves returns.\n'''
        README.write_text(s, encoding='utf-8')


def patch_stale_default_tests() -> list[Path]:
    changed=[]
    for p in sorted((ROOT/'tests').glob('test_*.py')):
        s=p.read_text(encoding='utf-8')
        if 'FIXED_ONE_PERCENT_RISK_PROFILE' in s:
            continue
        t=s
        for old,new in (
            ('risk_per_trade == 0.01','risk_per_trade == 0.03'),
            ('maximum_active_portfolio_risk == 0.06','maximum_active_portfolio_risk == 0.10'),
            ('config.risk_per_trade - 0.01','config.risk_per_trade - 0.03'),
            ('config.maximum_active_portfolio_risk - 0.06','config.maximum_active_portfolio_risk - 0.10'),
            ('risk_fraction == 0.01','risk_fraction == 0.03'),
            ('The 6% active-risk cap is full.','The 10% active-risk cap is full.'),
        ):
            t=t.replace(old,new)
        if p.name == 'test_qpx_bot_portfolio_risk.py':
            exact = (
                ('assert sizing.shares == 20','assert sizing.shares == 60'),
                ('assert abs(sizing.planned_risk - 100.0) < 1e-9','assert abs(sizing.planned_risk - 300.0) < 1e-9'),
                ('    active_risk=600.0,','    active_risk=1_000.0,'),
                ('assert "6%" in (capped.blocked_reason or "")','assert "10%" in (capped.blocked_reason or "")'),
                ('assert position.shares == 20','assert position.shares == 60'),
                ('assert abs(portfolio.active_risk() - 100.0) < 1e-9','assert abs(portfolio.active_risk() - 300.0) < 1e-9'),
            )
            for old,new in exact:
                if old not in t:
                    raise RuntimeError('Unexpected portfolio-risk test contract: '+old)
                t=t.replace(old,new,1)
        if t!=s:
            keep(p); p.write_text(t, encoding='utf-8'); changed.append(p)
            print('Updated stale default-risk test:', p.relative_to(ROOT))
    return changed


def focused_checks():
    sys.path.insert(0, str(ROOT))
    from qpx_bot.config import BotConfig
    from qpx_bot.risk import calculate_position_size
    c=BotConfig()
    assert abs(c.risk_per_trade-0.03)<1e-12
    assert abs(c.maximum_active_portfolio_risk-0.10)<1e-12
    z=calculate_position_size(account_equity=10000, available_cash=10000,
        entry_price=100, atr=2, active_risk=0, config=c, trade_results_r=())
    assert z.is_tradeable and abs(z.risk_fraction-0.03)<1e-12 and z.shares==60
    b=calculate_position_size(account_equity=10000, available_cash=10000,
        entry_price=100, atr=2, active_risk=1000, config=c, trade_results_r=())
    assert b.blocked_reason=='The 10% active-risk cap is full.'
    hs=HIST.read_text(encoding='utf-8')
    assert 'risk_per_trade=0.01' in hs and 'maximum_active_portfolio_risk=0.06' in hs
    print('Focused V19 risk checks: PASS')


def pf(vals):
    gp=sum(x for x in vals if x>0); gl=-sum(x for x in vals if x<0)
    return None if gl==0 and gp>0 else (0.0 if gl==0 else gp/gl)


def sm(rows):
    n=len(rows); pnl=[r['pnl'] for r in rows]; rr=[r['r'] for r in rows]
    return {'n':n,'win':sum(x>0 for x in pnl)/n if n else 0.0,
            'pf':pf(pnl),'r':sum(rr)/n if n else 0.0,'pnl':sum(pnl)}


def stability():
    root=ROOT/'reports/qpx_16pct_notional_cap_2024_08_06_to_2026_07_28'
    candidates=[]
    for d in root.iterdir():
        f=d/'v17_exit_diagnostics_trades.csv'
        if d.is_dir() and f.exists(): candidates.append((d.name,f))
    if not candidates: raise RuntimeError('No V17 diagnostic trade CSV found.')
    src=max(candidates)[1]
    rows=[]
    with src.open(newline='',encoding='utf-8') as f:
        for x in csv.DictReader(f):
            rows.append({'symbol':x['Symbol'],'dt':datetime.fromisoformat(x['EntryTimestampMarket']).date(),
                'pnl':float(x['PnL']),'r':float(x['ResultR']),'vix':x['VIXRegime'],
                'combo':x['TriggerCombo'],'triggers':tuple(t for t in x['Triggers'].split('|') if t)})
    periods=[('P1',date(2024,8,6),date(2025,2,5)),('P2',date(2025,2,6),date(2025,8,5)),
             ('P3',date(2025,8,6),date(2026,2,5)),('P4',date(2026,2,6),date(2026,7,28))]
    def groups(kind):
        g=defaultdict(list)
        if kind=='trigger':
            for r in rows:
                for k in r['triggers']: g[k].append(r)
        else:
            for r in rows: g[r[kind]].append(r)
        return g
    lines=['='*110,'QPX V19 — ENTRY-EDGE CHRONOLOGICAL STABILITY DIAGNOSTIC','='*110,
           f'Source: {src}','Strategy rerun: NO | Market-data download: NONE','']
    payload={'source':str(src),'periods':[(a,str(b),str(c)) for a,b,c in periods]}
    for title,kind in [('BY SYMBOL','symbol'),('BY TRIGGER COMBINATION','combo'),('BY ENTRY VIX REGIME','vix'),('BY INDIVIDUAL TRIGGER (COUNTS OVERLAP)','trigger')]:
        lines += [title,'  Category                         n    PF    AvgR      Net P&L   +Net periods']
        out={}
        for k,rs in sorted(groups(kind).items()):
            o=sm(rs); pp=[]; pos=0; active=0
            for lab,a,b in periods:
                q=sm([r for r in rs if a<=r['dt']<=b]); pp.append((lab,q))
                if q['n']:
                    active+=1; pos+=q['pnl']>0
            pft='∞' if o['pf'] is None else f"{o['pf']:.3f}"
            lines.append(f"  {k:<32}{o['n']:>4}  {pft:>6}  {o['r']:>6.3f}  ${o['pnl']:>10,.2f}   {pos}/{active}")
            lines.append('    '+' | '.join(f"{lab}:n={q['n']},PF={'∞' if q['pf'] is None else f'{q['pf']:.3f}'},R={q['r']:+.3f},net=${q['pnl']:+,.0f}" for lab,q in pp))
            out[k]={'overall':o,'periods':{lab:q for lab,q in pp},'positive_net_periods':pos,'active_periods':active}
        payload[kind]=out; lines.append('')
    lines += ['IN-SAMPLE GUARDRAIL: descriptive stability only; do not auto-promote filters from this window.','='*110]
    outdir=ROOT/'reports/qpx_entry_edge_stability_v19'/datetime.now().strftime('%Y%m%d_%H%M%S')
    outdir.mkdir(parents=True,exist_ok=True)
    report=outdir/'v19_entry_edge_stability_report.txt'; js=outdir/'v19_entry_edge_stability.json'
    report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    js.write_text(json.dumps(payload,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8')
    print('\n'.join(lines)); print('Artifacts:', report, js, sep='\n  ')


def main():
    print('='*78); print('QPX V19 — ENTRY STABILITY + 3% / 10% RISK DEFAULTS'); print('='*78)
    try:
        patch_code(); changed_tests=patch_stale_default_tests(); focused_checks()
        sh(sys.executable,'tests/run_all_tests.py')
    except Exception:
        restore(); raise
    paths=[CFG,RISK,HIST,INIT,README,*changed_tests]
    try:
        installer=Path(__file__).resolve()
        if installer.is_relative_to(ROOT):
            paths.append(installer)
    except (ValueError, AttributeError):
        pass
    sh('git','add','--',*(str(p.relative_to(ROOT)) for p in paths))
    if subprocess.run(['git','diff','--cached','--quiet'],cwd=ROOT).returncode:
        sh('git','commit','-m','Add entry stability diagnostics and 3 percent 10 percent risk defaults')
        sh('git','push','origin',subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip())
    stability()
    print('='*78); print('QPX ENTRY STABILITY + 3% / 10% RISK WORKFLOW V19: COMPLETE'); print('='*78)

if __name__=='__main__': main()
