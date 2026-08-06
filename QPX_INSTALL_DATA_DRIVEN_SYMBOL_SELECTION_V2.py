#!/usr/bin/env python3
"""Install, test, push, and run data-driven QPX symbol selection."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (start, *start.parents):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = (
    ROOT
    / "backups"
    / "qpx_data_driven_selection"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.10.0"\n',
    "qpx_bot/swing_universe.json": '{\n  "schema_version": 1,\n  "decision_frequency": "monthly",\n  "history_range": "3y",\n  "candidates": [\n    "DIA",\n    "IWM",\n    "QQQ",\n    "SPY",\n    "XLE",\n    "XLF",\n    "XLK",\n    "XLV"\n  ],\n  "minimum_history_bars": 252,\n  "minimum_eligible_candidates": 3,\n  "minimum_median_dollar_volume": 50000000,\n  "maximum_stale_days": 4,\n  "short_return_lookback": 63,\n  "long_return_lookback": 126,\n  "trend_lookback": 200,\n  "volatility_lookback": 63,\n  "drawdown_lookback": 126,\n  "liquidity_lookback": 20,\n  "weights": {\n    "short_return": 0.25,\n    "long_return": 0.30,\n    "trend": 0.15,\n    "liquidity": 0.10,\n    "volatility_penalty": 0.10,\n    "drawdown_penalty": 0.10\n  },\n  "symbol_bonus_policy": "none"\n}\n',
    "qpx_bot/symbol_selector.py": '"""Data-driven, symbol-neutral swing-universe ranking."""\n\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nfrom dataclasses import asdict, dataclass, replace\nfrom datetime import date, datetime, timezone\nfrom pathlib import Path\nfrom statistics import fmean, median, pstdev\nfrom typing import Any, Callable, Mapping, Sequence\n\nfrom qpx_bot.yahoo_data import (\n    MarketRow,\n    extract_market_rows,\n    fetch_chart,\n)\n\n\n@dataclass(frozen=True, slots=True)\nclass SelectionConfig:\n    schema_version: int\n    decision_frequency: str\n    history_range: str\n    candidates: tuple[str, ...]\n    minimum_history_bars: int\n    minimum_eligible_candidates: int\n    minimum_median_dollar_volume: float\n    maximum_stale_days: int\n    short_return_lookback: int\n    long_return_lookback: int\n    trend_lookback: int\n    volatility_lookback: int\n    drawdown_lookback: int\n    liquidity_lookback: int\n    weights: Mapping[str, float]\n    symbol_bonus_policy: str\n\n    def validate(self) -> None:\n        if self.schema_version != 1:\n            raise ValueError(\n                "Unsupported swing-universe schema version."\n            )\n\n        if self.decision_frequency != "monthly":\n            raise ValueError(\n                "Only monthly selection is currently supported."\n            )\n\n        normalized = tuple(\n            symbol.strip().upper()\n            for symbol in self.candidates\n            if symbol.strip()\n        )\n\n        if len(normalized) < 2:\n            raise ValueError(\n                "The swing universe needs at least two candidates."\n            )\n\n        if len(normalized) != len(set(normalized)):\n            raise ValueError(\n                "The swing universe contains duplicate symbols."\n            )\n\n        if self.minimum_eligible_candidates < 2:\n            raise ValueError(\n                "At least two eligible candidates are required."\n            )\n\n        if (\n            self.minimum_eligible_candidates\n            > len(normalized)\n        ):\n            raise ValueError(\n                "Minimum eligible candidates exceeds universe size."\n            )\n\n        periods = (\n            self.minimum_history_bars,\n            self.short_return_lookback,\n            self.long_return_lookback,\n            self.trend_lookback,\n            self.volatility_lookback,\n            self.drawdown_lookback,\n            self.liquidity_lookback,\n        )\n\n        if any(period < 2 for period in periods):\n            raise ValueError(\n                "Selection lookbacks must be at least two bars."\n            )\n\n        if self.minimum_median_dollar_volume <= 0:\n            raise ValueError(\n                "Minimum median dollar volume must be positive."\n            )\n\n        if self.maximum_stale_days < 0:\n            raise ValueError(\n                "Maximum stale days cannot be negative."\n            )\n\n        required_weights = {\n            "short_return",\n            "long_return",\n            "trend",\n            "liquidity",\n            "volatility_penalty",\n            "drawdown_penalty",\n        }\n\n        if set(self.weights) != required_weights:\n            raise ValueError(\n                "Selection weights do not match the required fields."\n            )\n\n        if any(float(value) < 0 for value in self.weights.values()):\n            raise ValueError(\n                "Selection weights cannot be negative."\n            )\n\n        total_weight = sum(\n            float(value)\n            for value in self.weights.values()\n        )\n\n        if abs(total_weight - 1.0) > 1e-9:\n            raise ValueError(\n                "Selection weights must total 1.0."\n            )\n\n        if self.symbol_bonus_policy != "none":\n            raise ValueError(\n                "Symbol-specific bonuses are prohibited."\n            )\n\n\n@dataclass(frozen=True, slots=True)\nclass CandidateMetrics:\n    symbol: str\n    first_date: date | None\n    last_date: date | None\n    bars: int\n    median_dollar_volume: float\n    short_return: float\n    long_return: float\n    trend_distance: float\n    annualized_volatility: float\n    maximum_drawdown: float\n    eligible: bool\n    rejection_reason: str | None\n    score: float = 0.0\n    rank: int | None = None\n\n\n@dataclass(frozen=True, slots=True)\nclass SelectionResult:\n    generated_at_utc: str\n    latest_market_date: date\n    selected_symbol: str\n    rankings: tuple[CandidateMetrics, ...]\n    failed_downloads: Mapping[str, str]\n    methodology: str\n    symbol_bonus_policy: str\n\n\ndef load_selection_config(\n    filename: str | Path,\n) -> SelectionConfig:\n    path = Path(filename).expanduser().resolve()\n    payload = json.loads(path.read_text(encoding="utf-8"))\n\n    if not isinstance(payload, Mapping):\n        raise ValueError(\n            "Swing-universe configuration must be an object."\n        )\n\n    config = SelectionConfig(\n        schema_version=int(payload["schema_version"]),\n        decision_frequency=str(\n            payload["decision_frequency"]\n        ).strip().lower(),\n        history_range=str(payload["history_range"]),\n        candidates=tuple(\n            str(symbol).strip().upper()\n            for symbol in payload["candidates"]\n        ),\n        minimum_history_bars=int(\n            payload["minimum_history_bars"]\n        ),\n        minimum_eligible_candidates=int(\n            payload["minimum_eligible_candidates"]\n        ),\n        minimum_median_dollar_volume=float(\n            payload["minimum_median_dollar_volume"]\n        ),\n        maximum_stale_days=int(\n            payload["maximum_stale_days"]\n        ),\n        short_return_lookback=int(\n            payload["short_return_lookback"]\n        ),\n        long_return_lookback=int(\n            payload["long_return_lookback"]\n        ),\n        trend_lookback=int(payload["trend_lookback"]),\n        volatility_lookback=int(\n            payload["volatility_lookback"]\n        ),\n        drawdown_lookback=int(\n            payload["drawdown_lookback"]\n        ),\n        liquidity_lookback=int(\n            payload["liquidity_lookback"]\n        ),\n        weights={\n            str(name): float(value)\n            for name, value in payload["weights"].items()\n        },\n        symbol_bonus_policy=str(\n            payload.get("symbol_bonus_policy", "")\n        ).strip().lower(),\n    )\n    config.validate()\n    return config\n\n\ndef _required_bars(config: SelectionConfig) -> int:\n    return max(\n        config.minimum_history_bars,\n        config.short_return_lookback + 1,\n        config.long_return_lookback + 1,\n        config.trend_lookback,\n        config.volatility_lookback + 1,\n        config.drawdown_lookback,\n        config.liquidity_lookback,\n    )\n\n\ndef _maximum_drawdown(prices: Sequence[float]) -> float:\n    peak = float(prices[0])\n    maximum = 0.0\n\n    for price in prices:\n        peak = max(peak, float(price))\n\n        if peak > 0:\n            maximum = max(\n                maximum,\n                (peak - float(price)) / peak,\n            )\n\n    return maximum\n\n\ndef _candidate_metrics(\n    symbol: str,\n    rows: Sequence[MarketRow],\n    config: SelectionConfig,\n) -> CandidateMetrics:\n    normalized = symbol.strip().upper()\n    ordered = sorted(rows, key=lambda row: row.date)\n    required = _required_bars(config)\n\n    if len(ordered) < required:\n        return CandidateMetrics(\n            symbol=normalized,\n            first_date=(\n                ordered[0].date\n                if ordered\n                else None\n            ),\n            last_date=(\n                ordered[-1].date\n                if ordered\n                else None\n            ),\n            bars=len(ordered),\n            median_dollar_volume=0.0,\n            short_return=0.0,\n            long_return=0.0,\n            trend_distance=0.0,\n            annualized_volatility=0.0,\n            maximum_drawdown=0.0,\n            eligible=False,\n            rejection_reason=(\n                f"{len(ordered)} bars; {required} required"\n            ),\n        )\n\n    prices = [\n        float(row.adjusted_close)\n        for row in ordered\n    ]\n\n    if any(price <= 0 for price in prices):\n        return CandidateMetrics(\n            symbol=normalized,\n            first_date=ordered[0].date,\n            last_date=ordered[-1].date,\n            bars=len(ordered),\n            median_dollar_volume=0.0,\n            short_return=0.0,\n            long_return=0.0,\n            trend_distance=0.0,\n            annualized_volatility=0.0,\n            maximum_drawdown=0.0,\n            eligible=False,\n            rejection_reason="non-positive adjusted price",\n        )\n\n    short_return = (\n        prices[-1]\n        / prices[-config.short_return_lookback - 1]\n        - 1.0\n    )\n    long_return = (\n        prices[-1]\n        / prices[-config.long_return_lookback - 1]\n        - 1.0\n    )\n    trend_average = fmean(\n        prices[-config.trend_lookback:]\n    )\n    trend_distance = prices[-1] / trend_average - 1.0\n\n    volatility_prices = prices[\n        -config.volatility_lookback - 1:\n    ]\n    daily_returns = [\n        current / previous - 1.0\n        for previous, current in zip(\n            volatility_prices,\n            volatility_prices[1:],\n        )\n    ]\n    annualized_volatility = (\n        pstdev(daily_returns) * math.sqrt(252.0)\n        if len(daily_returns) > 1\n        else 0.0\n    )\n\n    drawdown_prices = prices[\n        -config.drawdown_lookback:\n    ]\n    maximum_drawdown = _maximum_drawdown(\n        drawdown_prices\n    )\n\n    liquidity_rows = ordered[\n        -config.liquidity_lookback:\n    ]\n    median_dollar_volume = median(\n        float(row.close) * float(row.volume)\n        for row in liquidity_rows\n    )\n    eligible = (\n        median_dollar_volume\n        >= config.minimum_median_dollar_volume\n    )\n\n    return CandidateMetrics(\n        symbol=normalized,\n        first_date=ordered[0].date,\n        last_date=ordered[-1].date,\n        bars=len(ordered),\n        median_dollar_volume=median_dollar_volume,\n        short_return=short_return,\n        long_return=long_return,\n        trend_distance=trend_distance,\n        annualized_volatility=annualized_volatility,\n        maximum_drawdown=maximum_drawdown,\n        eligible=eligible,\n        rejection_reason=(\n            None\n            if eligible\n            else "median dollar volume below minimum"\n        ),\n    )\n\n\ndef _z_scores(\n    candidates: Sequence[CandidateMetrics],\n    attribute: str,\n) -> dict[str, float]:\n    values = [\n        float(getattr(candidate, attribute))\n        for candidate in candidates\n    ]\n    average = fmean(values)\n    deviation = (\n        pstdev(values)\n        if len(values) > 1\n        else 0.0\n    )\n\n    if deviation <= 1e-15:\n        return {\n            candidate.symbol: 0.0\n            for candidate in candidates\n        }\n\n    return {\n        candidate.symbol: (\n            float(getattr(candidate, attribute))\n            - average\n        ) / deviation\n        for candidate in candidates\n    }\n\n\ndef rank_candidates(\n    histories: Mapping[str, Sequence[MarketRow]],\n    config: SelectionConfig,\n    *,\n    failed_downloads: Mapping[str, str] | None = None,\n) -> SelectionResult:\n    """\n    Rank all eligible symbols using identical formulas.\n\n    There is no symbol-specific preference, bonus, fallback, or\n    tie-break. Equal scores are resolved alphabetically.\n    """\n    config.validate()\n    metrics = [\n        _candidate_metrics(symbol, histories.get(symbol, ()), config)\n        for symbol in config.candidates\n    ]\n    dated = [\n        candidate.last_date\n        for candidate in metrics\n        if candidate.last_date is not None\n    ]\n\n    if not dated:\n        raise RuntimeError(\n            "No candidate returned usable daily history."\n        )\n\n    latest_market_date = max(dated)\n    stale_checked: list[CandidateMetrics] = []\n\n    for candidate in metrics:\n        if (\n            candidate.eligible\n            and candidate.last_date is not None\n            and (\n                latest_market_date - candidate.last_date\n            ).days > config.maximum_stale_days\n        ):\n            stale_checked.append(\n                replace(\n                    candidate,\n                    eligible=False,\n                    rejection_reason=(\n                        "history is stale relative to universe"\n                    ),\n                )\n            )\n        else:\n            stale_checked.append(candidate)\n\n    eligible = [\n        candidate\n        for candidate in stale_checked\n        if candidate.eligible\n    ]\n\n    if len(eligible) < config.minimum_eligible_candidates:\n        reasons = "; ".join(\n            f"{candidate.symbol}: "\n            f"{candidate.rejection_reason or \'ineligible\'}"\n            for candidate in stale_checked\n            if not candidate.eligible\n        )\n        raise RuntimeError(\n            "Too few eligible swing candidates: "\n            f"{len(eligible)}; "\n            f"{config.minimum_eligible_candidates} required. "\n            + reasons\n        )\n\n    short_z = _z_scores(eligible, "short_return")\n    long_z = _z_scores(eligible, "long_return")\n    trend_z = _z_scores(eligible, "trend_distance")\n    liquidity_values = {\n        candidate.symbol: math.log10(\n            max(1.0, candidate.median_dollar_volume)\n        )\n        for candidate in eligible\n    }\n    liquidity_average = fmean(\n        liquidity_values.values()\n    )\n    liquidity_deviation = (\n        pstdev(liquidity_values.values())\n        if len(liquidity_values) > 1\n        else 0.0\n    )\n    liquidity_z = {\n        symbol: (\n            (value - liquidity_average)\n            / liquidity_deviation\n            if liquidity_deviation > 1e-15\n            else 0.0\n        )\n        for symbol, value in liquidity_values.items()\n    }\n    volatility_z = _z_scores(\n        eligible,\n        "annualized_volatility",\n    )\n    drawdown_z = _z_scores(\n        eligible,\n        "maximum_drawdown",\n    )\n\n    scored: list[CandidateMetrics] = []\n\n    for candidate in eligible:\n        score = (\n            config.weights["short_return"]\n            * short_z[candidate.symbol]\n            + config.weights["long_return"]\n            * long_z[candidate.symbol]\n            + config.weights["trend"]\n            * trend_z[candidate.symbol]\n            + config.weights["liquidity"]\n            * liquidity_z[candidate.symbol]\n            - config.weights["volatility_penalty"]\n            * volatility_z[candidate.symbol]\n            - config.weights["drawdown_penalty"]\n            * drawdown_z[candidate.symbol]\n        )\n        scored.append(replace(candidate, score=score))\n\n    scored.sort(key=lambda item: (-item.score, item.symbol))\n    ranked = [\n        replace(candidate, rank=index)\n        for index, candidate in enumerate(\n            scored,\n            start=1,\n        )\n    ]\n    rejected = sorted(\n        (\n            candidate\n            for candidate in stale_checked\n            if not candidate.eligible\n        ),\n        key=lambda item: item.symbol,\n    )\n    complete = tuple([*ranked, *rejected])\n\n    return SelectionResult(\n        generated_at_utc=datetime.now(\n            timezone.utc\n        ).isoformat(),\n        latest_market_date=latest_market_date,\n        selected_symbol=ranked[0].symbol,\n        rankings=complete,\n        failed_downloads=dict(\n            failed_downloads or {}\n        ),\n        methodology=(\n            "Cross-sectional z-score ranking of trailing "\n            "adjusted returns, trend distance, and dollar "\n            "liquidity, minus volatility and drawdown penalties."\n        ),\n        symbol_bonus_policy=config.symbol_bonus_policy,\n    )\n\n\ndef select_from_provider(\n    config: SelectionConfig,\n    *,\n    fetcher: Callable[[str], Mapping[str, Any]] | None = None,\n) -> SelectionResult:\n    histories: dict[str, Sequence[MarketRow]] = {}\n    failures: dict[str, str] = {}\n\n    for symbol in config.candidates:\n        print(f"Ranking data: {symbol}...")\n\n        try:\n            if fetcher is None:\n                result = fetch_chart(\n                    symbol,\n                    range_name=config.history_range,\n                    timeout_seconds=20.0,\n                    maximum_attempts=3,\n                )\n            else:\n                result = fetcher(symbol)\n\n            histories[symbol] = extract_market_rows(result)\n        except Exception as exc:\n            failures[symbol] = (\n                f"{type(exc).__name__}: {exc}"\n            )\n\n    return rank_candidates(\n        histories,\n        config,\n        failed_downloads=failures,\n    )\n\n\ndef _candidate_payload(\n    candidate: CandidateMetrics,\n) -> dict[str, Any]:\n    payload = asdict(candidate)\n    payload["first_date"] = (\n        candidate.first_date.isoformat()\n        if candidate.first_date\n        else None\n    )\n    payload["last_date"] = (\n        candidate.last_date.isoformat()\n        if candidate.last_date\n        else None\n    )\n    return payload\n\n\ndef write_selection_artifacts(\n    result: SelectionResult,\n    output_directory: str | Path,\n) -> dict[str, Path]:\n    output = Path(\n        output_directory\n    ).expanduser().resolve()\n    output.mkdir(parents=True, exist_ok=True)\n\n    text_path = output / "symbol_selection_report.txt"\n    csv_path = output / "symbol_selection_rankings.csv"\n    json_path = output / "symbol_selection_result.json"\n\n    lines = [\n        "=" * 78,\n        "QPX BOT v1.10 — DATA-DRIVEN SWING SYMBOL SELECTION",\n        "=" * 78,\n        f"Selected symbol          : {result.selected_symbol}",\n        f"Latest market date       : {result.latest_market_date}",\n        f"Symbol bonus policy      : {result.symbol_bonus_policy}",\n        f"Methodology              : {result.methodology}",\n        "-" * 78,\n    ]\n\n    for candidate in result.rankings:\n        if candidate.eligible:\n            lines.append(\n                (\n                    f"{candidate.rank:02d} {candidate.symbol:<6} "\n                    f"score {candidate.score:>8.4f} | "\n                    f"63d {candidate.short_return:>8.2%} | "\n                    f"126d {candidate.long_return:>8.2%} | "\n                    f"trend {candidate.trend_distance:>8.2%} | "\n                    f"vol {candidate.annualized_volatility:>8.2%} | "\n                    f"DD {candidate.maximum_drawdown:>8.2%}"\n                )\n            )\n        else:\n            lines.append(\n                f"-- {candidate.symbol:<6} REJECTED: "\n                f"{candidate.rejection_reason}"\n            )\n\n    if result.failed_downloads:\n        lines.append("-" * 78)\n        lines.append("DOWNLOAD FAILURES")\n\n        for symbol, reason in sorted(\n            result.failed_downloads.items()\n        ):\n            lines.append(f"{symbol}: {reason}")\n\n    lines.extend(\n        [\n            "=" * 78,\n            (\n                "Every candidate uses the same score. "\n                "No ticker receives a hardcoded preference."\n            ),\n            (\n                "Research selection only. This is not a "\n                "recommendation or guarantee."\n            ),\n        ]\n    )\n    text_path.write_text(\n        "\\n".join(lines) + "\\n",\n        encoding="utf-8",\n    )\n\n    with csv_path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            [\n                "Rank",\n                "Symbol",\n                "Eligible",\n                "Score",\n                "FirstDate",\n                "LastDate",\n                "Bars",\n                "MedianDollarVolume",\n                "ShortReturn",\n                "LongReturn",\n                "TrendDistance",\n                "AnnualizedVolatility",\n                "MaximumDrawdown",\n                "RejectionReason",\n            ]\n        )\n\n        for candidate in result.rankings:\n            writer.writerow(\n                [\n                    candidate.rank or "",\n                    candidate.symbol,\n                    candidate.eligible,\n                    f"{candidate.score:.10f}",\n                    (\n                        candidate.first_date.isoformat()\n                        if candidate.first_date\n                        else ""\n                    ),\n                    (\n                        candidate.last_date.isoformat()\n                        if candidate.last_date\n                        else ""\n                    ),\n                    candidate.bars,\n                    f"{candidate.median_dollar_volume:.6f}",\n                    f"{candidate.short_return:.10f}",\n                    f"{candidate.long_return:.10f}",\n                    f"{candidate.trend_distance:.10f}",\n                    f"{candidate.annualized_volatility:.10f}",\n                    f"{candidate.maximum_drawdown:.10f}",\n                    candidate.rejection_reason or "",\n                ]\n            )\n\n    payload = {\n        "generated_at_utc": result.generated_at_utc,\n        "latest_market_date": (\n            result.latest_market_date.isoformat()\n        ),\n        "selected_symbol": result.selected_symbol,\n        "methodology": result.methodology,\n        "symbol_bonus_policy": result.symbol_bonus_policy,\n        "rankings": [\n            _candidate_payload(candidate)\n            for candidate in result.rankings\n        ],\n        "failed_downloads": dict(\n            result.failed_downloads\n        ),\n    }\n    json_path.write_text(\n        json.dumps(payload, indent=2) + "\\n",\n        encoding="utf-8",\n    )\n\n    return {\n        "report": text_path,\n        "rankings": csv_path,\n        "result": json_path,\n    }\n',
    "qpx_bot/auto_paper.py": '"""Monthly data-driven selection plus daily persistent paper operation."""\n\nfrom __future__ import annotations\n\nimport argparse\nimport hashlib\nimport json\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom typing import Sequence\n\nfrom qpx_bot.paper_runner import main as paper_main\nfrom qpx_bot.paper_state import AuditEvent, StateStore\nfrom qpx_bot.symbol_selector import (\n    load_selection_config,\n    select_from_provider,\n    write_selection_artifacts,\n)\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nDEFAULT_UNIVERSE = PACKAGE_DIR / "swing_universe.json"\nDEFAULT_SELECTION_RUNTIME = (\n    PACKAGE_DIR / "selection_runtime"\n)\nDEFAULT_SELECTION_REPORTS = (\n    PROJECT_ROOT / "reports" / "qpx_symbol_selection"\n)\nDEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"\nDEFAULT_INPUT_DIR = PACKAGE_DIR / "data_inputs"\nDEFAULT_PAPER_REPORTS = (\n    PROJECT_ROOT / "reports" / "qpx_paper"\n)\n\n\ndef _atomic_json(path: Path, payload: dict) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(path.suffix + ".tmp")\n    temporary.write_text(\n        json.dumps(payload, indent=2) + "\\n",\n        encoding="utf-8",\n    )\n    temporary.replace(path)\n\n\ndef _decision_month() -> str:\n    return datetime.now(\n        timezone.utc\n    ).strftime("%Y-%m")\n\n\ndef _load_cached_decision(\n    path: Path,\n    *,\n    month: str,\n    candidates: tuple[str, ...],\n) -> dict | None:\n    if not path.exists():\n        return None\n\n    try:\n        payload = json.loads(\n            path.read_text(encoding="utf-8")\n        )\n    except (OSError, json.JSONDecodeError):\n        return None\n\n    selected = str(\n        payload.get("selected_symbol", "")\n    ).strip().upper()\n\n    if (\n        payload.get("decision_month") != month\n        or selected not in candidates\n    ):\n        return None\n\n    return payload\n\n\ndef _selection_event(\n    *,\n    state_id: str,\n    previous_symbol: str,\n    selected_symbol: str,\n    month: str,\n) -> AuditEvent:\n    raw = (\n        f"{state_id}|{previous_symbol}|"\n        f"{selected_symbol}|{month}"\n    )\n    event_id = (\n        "symbol-rotation-"\n        + hashlib.sha256(\n            raw.encode("utf-8")\n        ).hexdigest()[:24]\n    )\n\n    return AuditEvent(\n        event_id=event_id,\n        event_type="SYMBOL_ROTATION",\n        event_date=datetime.now().date(),\n        details={\n            "previous_symbol": previous_symbol,\n            "selected_symbol": selected_symbol,\n            "decision_month": month,\n            "selection_policy": (\n                "data-driven; no symbol bonus"\n            ),\n        },\n    )\n\n\ndef _execution_symbol(\n    *,\n    store: StateStore,\n    selected_symbol: str,\n    decision_month: str,\n) -> tuple[str, str]:\n    if not store.exists():\n        return (\n            selected_symbol,\n            "new paper account uses ranked winner",\n        )\n\n    with store.locked():\n        state = store.load()\n\n        if (\n            state.position is not None\n            or state.pending_entry is not None\n        ):\n            return (\n                state.swing_symbol,\n                (\n                    "existing position or pending order locks "\n                    "the current symbol until flat"\n                ),\n            )\n\n        if state.swing_symbol == selected_symbol:\n            return (\n                selected_symbol,\n                "saved paper symbol already matches ranked winner",\n            )\n\n        previous_symbol = state.swing_symbol\n        state.swing_symbol = selected_symbol\n        state.revision += 1\n        event = _selection_event(\n            state_id=state.state_id,\n            previous_symbol=previous_symbol,\n            selected_symbol=selected_symbol,\n            month=decision_month,\n        )\n        store.append_events([event])\n        store.save(state)\n\n        return (\n            selected_symbol,\n            (\n                f"flat paper account rotated from "\n                f"{previous_symbol} to ranked winner"\n            ),\n        )\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Select a swing ticker without hardcoded preference, "\n            "then advance the persistent simulated paper account."\n        )\n    )\n    parser.add_argument(\n        "--universe",\n        default=str(DEFAULT_UNIVERSE),\n    )\n    parser.add_argument(\n        "--selection-runtime-dir",\n        default=str(DEFAULT_SELECTION_RUNTIME),\n    )\n    parser.add_argument(\n        "--selection-report-dir",\n        default=str(DEFAULT_SELECTION_REPORTS),\n    )\n    parser.add_argument(\n        "--paper-runtime-dir",\n        default=str(DEFAULT_PAPER_RUNTIME),\n    )\n    parser.add_argument(\n        "--input-dir",\n        default=str(DEFAULT_INPUT_DIR),\n    )\n    parser.add_argument(\n        "--paper-report-dir",\n        default=str(DEFAULT_PAPER_REPORTS),\n    )\n    parser.add_argument(\n        "--force-reselect",\n        action="store_true",\n    )\n    return parser\n\n\ndef main(argv: Sequence[str] | None = None) -> int:\n    args = _parser().parse_args(argv)\n    config = load_selection_config(args.universe)\n    month = _decision_month()\n    selection_runtime = Path(\n        args.selection_runtime_dir\n    ).expanduser().resolve()\n    decision_path = (\n        selection_runtime / "selection_decision.json"\n    )\n    cached = (\n        None\n        if args.force_reselect\n        else _load_cached_decision(\n            decision_path,\n            month=month,\n            candidates=config.candidates,\n        )\n    )\n\n    print("=" * 78)\n    print("QPX BOT v1.10 — SYMBOL-NEUTRAL AUTO PAPER RUNNER")\n    print("=" * 78)\n    print(\n        "SPY is a candidate only; it has no bonus, "\n        "fallback, or default."\n    )\n\n    if cached is None:\n        result = select_from_provider(config)\n        artifacts = write_selection_artifacts(\n            result,\n            args.selection_report_dir,\n        )\n        selected_symbol = result.selected_symbol\n        decision = {\n            "decision_month": month,\n            "selected_symbol": selected_symbol,\n            "created_at_utc": result.generated_at_utc,\n            "latest_market_date": (\n                result.latest_market_date.isoformat()\n            ),\n            "symbol_bonus_policy": (\n                result.symbol_bonus_policy\n            ),\n            "report": str(artifacts["report"]),\n            "result": str(artifacts["result"]),\n        }\n        _atomic_json(decision_path, decision)\n        print()\n        print(\n            f"Monthly ranked winner: {selected_symbol}"\n        )\n        print(f"Selection report: {artifacts[\'report\']}")\n    else:\n        selected_symbol = str(\n            cached["selected_symbol"]\n        ).strip().upper()\n        print(\n            f"Using cached monthly winner: {selected_symbol}"\n        )\n\n    paper_store = StateStore(args.paper_runtime_dir)\n    execution_symbol, reason = _execution_symbol(\n        store=paper_store,\n        selected_symbol=selected_symbol,\n        decision_month=month,\n    )\n    print(f"Execution symbol     : {execution_symbol}")\n    print(f"Execution policy     : {reason}")\n    print()\n\n    return paper_main(\n        [\n            "--symbol",\n            execution_symbol,\n            "--runtime-dir",\n            str(\n                Path(args.paper_runtime_dir)\n                .expanduser()\n                .resolve()\n            ),\n            "--input-dir",\n            str(\n                Path(args.input_dir)\n                .expanduser()\n                .resolve()\n            ),\n            "--report-dir",\n            str(\n                Path(args.paper_report_dir)\n                .expanduser()\n                .resolve()\n            ),\n        ]\n    )\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_RUN_AUTO_PAPER.py": '#!/usr/bin/env python3\n"""Run data-driven monthly selection and daily QPX paper operations."""\n\nfrom qpx_bot.auto_paper import main\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_symbol_selection.py": 'import json\nfrom datetime import date, timedelta\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.symbol_selector import (\n    SelectionConfig,\n    load_selection_config,\n    rank_candidates,\n    write_selection_artifacts,\n)\nfrom qpx_bot.yahoo_data import MarketRow\n\n\ndef make_rows(\n    *,\n    slope: float,\n    volume: int,\n    wave: float,\n):\n    start = date(2024, 1, 2)\n    rows = []\n\n    for index in range(300):\n        base = 100.0 + (slope * index)\n        wobble = wave * ((index % 10) - 5) / 10.0\n        price = base + wobble\n        rows.append(\n            MarketRow(\n                date=start + timedelta(days=index),\n                open=price,\n                high=price + 1.0,\n                low=price - 1.0,\n                close=price + 0.20,\n                adjusted_close=price + 0.20,\n                volume=volume,\n            )\n        )\n\n    return rows\n\n\nconfig = SelectionConfig(\n    schema_version=1,\n    decision_frequency="monthly",\n    history_range="3y",\n    candidates=("IWM", "QQQ", "SPY"),\n    minimum_history_bars=252,\n    minimum_eligible_candidates=3,\n    minimum_median_dollar_volume=50_000_000.0,\n    maximum_stale_days=4,\n    short_return_lookback=63,\n    long_return_lookback=126,\n    trend_lookback=200,\n    volatility_lookback=63,\n    drawdown_lookback=126,\n    liquidity_lookback=20,\n    weights={\n        "short_return": 0.25,\n        "long_return": 0.30,\n        "trend": 0.15,\n        "liquidity": 0.10,\n        "volatility_penalty": 0.10,\n        "drawdown_penalty": 0.10,\n    },\n    symbol_bonus_policy="none",\n)\nconfig.validate()\n\nhistories = {\n    "SPY": make_rows(\n        slope=0.03,\n        volume=5_000_000,\n        wave=0.20,\n    ),\n    "QQQ": make_rows(\n        slope=0.11,\n        volume=5_000_000,\n        wave=0.10,\n    ),\n    "IWM": make_rows(\n        slope=0.01,\n        volume=5_000_000,\n        wave=0.40,\n    ),\n}\n\nresult = rank_candidates(histories, config)\n\nassert result.selected_symbol == "QQQ"\nassert result.symbol_bonus_policy == "none"\nassert result.rankings[0].symbol == "QQQ"\nassert next(\n    candidate.rank\n    for candidate in result.rankings\n    if candidate.symbol == "SPY"\n) != 1\n\nwith TemporaryDirectory() as temporary_directory:\n    directory = Path(temporary_directory)\n    config_path = directory / "universe.json"\n    config_path.write_text(\n        json.dumps(\n            {\n                "schema_version": 1,\n                "decision_frequency": "monthly",\n                "history_range": "3y",\n                "candidates": ["IWM", "QQQ", "SPY"],\n                "minimum_history_bars": 252,\n                "minimum_eligible_candidates": 3,\n                "minimum_median_dollar_volume": 50000000,\n                "maximum_stale_days": 4,\n                "short_return_lookback": 63,\n                "long_return_lookback": 126,\n                "trend_lookback": 200,\n                "volatility_lookback": 63,\n                "drawdown_lookback": 126,\n                "liquidity_lookback": 20,\n                "weights": dict(config.weights),\n                "symbol_bonus_policy": "none",\n            }\n        ),\n        encoding="utf-8",\n    )\n    loaded = load_selection_config(config_path)\n    assert "SPY" in loaded.candidates\n\n    artifacts = write_selection_artifacts(\n        result,\n        directory / "reports",\n    )\n    assert artifacts["report"].exists()\n    assert artifacts["rankings"].exists()\n    assert artifacts["result"].exists()\n    assert (\n        \'"selected_symbol": "QQQ"\'\n        in artifacts["result"].read_text(\n            encoding="utf-8"\n        )\n    )\n\nroot = Path(__file__).resolve().parents[1]\npaper_source = (\n    root / "qpx_bot" / "paper_runner.py"\n).read_text(encoding="utf-8")\nfetch_source = (\n    root / "QPX_FETCH_AND_RUN_REAL_DATA.py"\n).read_text(encoding="utf-8")\nwalk_source = (\n    root / "QPX_RUN_WALK_FORWARD.py"\n).read_text(encoding="utf-8")\n\nassert \'default="SPY"\' not in paper_source\nassert \'default="SPY"\' not in fetch_source\nassert \'default="SPY"\' not in walk_source\nassert "SPY" in (\n    root / "qpx_bot" / "swing_universe.json"\n).read_text(encoding="utf-8")\n\nprint("QPX Bot Data-Driven Symbol Selection PASS")\n',
    "qpx_bot/SYMBOL_SELECTION_README.txt": 'QPX DATA-DRIVEN SWING SYMBOL SELECTION\n======================================\n\nRecommended daily paper command:\n\npython QPX_RUN_AUTO_PAPER.py\n\nSelection policy:\n\n- The candidate universe is stored in qpx_bot/swing_universe.json.\n- SPY remains one candidate but receives no preference or bonus.\n- No swing ticker is the default for manual runners.\n- Each eligible ticker receives the same formula.\n- The formula ranks adjusted 63-day and 126-day returns, distance\n  above the 200-day trend, and median dollar liquidity.\n- Annualized volatility and maximum drawdown reduce the score.\n- Candidates with inadequate history, liquidity, or stale data are\n  rejected.\n- Equal scores are resolved alphabetically, not by preferred ticker.\n- The winning symbol is held as the monthly selection decision.\n- A live paper position or pending order locks the current symbol\n  until that simulated account is flat.\n- A flat paper account may rotate to the new monthly winner while\n  preserving its cash, QDTE income holding, contributions, taxes,\n  and audit history.\n\nManual explicit-symbol commands remain available:\n\npython QPX_RUN_PAPER.py --symbol TICKER\npython QPX_FETCH_AND_RUN_REAL_DATA.py --symbol TICKER\npython QPX_RUN_WALK_FORWARD.py --symbol TICKER\n\nEdit swing_universe.json to change candidates or transparent scoring\nweights. All weights must remain nonnegative and total exactly 1.0.\nSymbol-specific bonuses are rejected by validation.\n\nThis is a research ranking process, not a recommendation or guarantee.\n',
}

PATCHES = {
    "qpx_bot/paper_runner.py": [
        (
            '    parser.add_argument("--symbol", default="SPY")',
            (
                '    parser.add_argument(\n'
                '        "--symbol",\n'
                '        default=None,\n'
                '        help=(\n'
                '            "Explicit swing ticker. The recommended "\n'
                '            "auto runner selects one without a default."\n'
                '        ),\n'
                '    )'
            ),
        ),
        (
            (
                "        input_directory = Path(\n"
                "            args.input_dir\n"
                "        ).expanduser().resolve()\n"
            ),
            (
                "        if not args.symbol:\n"
                "            print(\n"
                '                "No swing symbol was supplied. Use "\n'
                '                "QPX_RUN_AUTO_PAPER.py or --symbol TICKER."\n'
                "            )\n"
                "            return 2\n"
                "\n"
                "        symbol = args.symbol.strip().upper()\n"
                "\n"
                "        input_directory = Path(\n"
                "            args.input_dir\n"
                "        ).expanduser().resolve()\n"
            ),
        ),
        (
            "                swing_symbol=args.symbol,",
            "                swing_symbol=symbol,",
        ),
        (
            (
                "            if state.swing_symbol "
                "!= args.symbol.strip().upper():"
            ),
            "            if state.swing_symbol != symbol:",
        ),
        (
            "                swing_symbol=args.symbol,",
            "                swing_symbol=symbol,",
        ),
        (
            "QPX BOT v1.9 — PERSISTENT PAPER ACCOUNT",
            "QPX BOT v1.10 — PERSISTENT PAPER ACCOUNT",
        ),
    ],
    "QPX_FETCH_AND_RUN_REAL_DATA.py": [
        (
            (
                '    parser.add_argument(\n'
                '        "--symbol",\n'
                '        default="SPY",\n'
                '        help="Swing ticker to download. Default: SPY.",\n'
                '    )'
            ),
            (
                '    parser.add_argument(\n'
                '        "--symbol",\n'
                '        required=True,\n'
                '        help="Explicit swing ticker to download.",\n'
                '    )'
            ),
        ),
    ],
    "QPX_RUN_WALK_FORWARD.py": [
        (
            (
                '"Run rolling QPX training/testing windows and compare "\n'
                '            "unseen results with adjusted-close SPY buy-and-hold."'
            ),
            (
                '"Run rolling QPX training/testing windows and compare "\n'
                '            "unseen results with matched adjusted-close buy-and-hold."'
            ),
        ),
        (
            '    parser.add_argument("--symbol", default="SPY")',
            (
                '    parser.add_argument(\n'
                '        "--symbol",\n'
                '        required=True,\n'
                '        help="Explicit swing and matched benchmark ticker.",\n'
                '    )'
            ),
        ),
        (
            "QPX BOT v1.8 — WALK-FORWARD + SPY BENCHMARK RUNNER",
            (
                "QPX BOT v1.10 — WALK-FORWARD + "
                "MATCHED BENCHMARK RUNNER"
            ),
        ),
    ],
    "qpx_bot/walk_forward.py": [
        (
            (
                '            "SPY contribution-adjusted return : "\n'
                '            f"{percent(benchmark.total_return)}"'
            ),
            (
                '            f"{result.symbol} contribution-adjusted "\n'
                '            f"return : {percent(benchmark.total_return)}"'
            ),
        ),
        (
            (
                '        f"SPY CAGR                         : '
                '{percent(benchmark.cagr)}",'
            ),
            (
                '        f"{result.symbol} CAGR                         : '
                '{percent(benchmark.cagr)}",'
            ),
        ),
        (
            (
                '        f"SPY Sharpe                       : '
                '{ratio(benchmark.sharpe_ratio)}",'
            ),
            (
                '        f"{result.symbol} Sharpe                       : '
                '{ratio(benchmark.sharpe_ratio)}",'
            ),
        ),
        (
            (
                '        f"SPY Sortino                      : '
                '{ratio(benchmark.sortino_ratio)}",'
            ),
            (
                '        f"{result.symbol} Sortino                      : '
                '{ratio(benchmark.sortino_ratio)}",'
            ),
        ),
        (
            (
                '        f"SPY maximum drawdown             : '
                '{percent(benchmark.maximum_drawdown)}",'
            ),
            (
                '        f"{result.symbol} maximum drawdown             : '
                '{percent(benchmark.maximum_drawdown)}",'
            ),
        ),
        (
            (
                '                f"SPY CAGR '
                '{percent(window.benchmark_metrics.cagr)} | "'
            ),
            (
                '                f"{result.symbol} CAGR '
                '{percent(window.benchmark_metrics.cagr)} | "'
            ),
        ),
        (
            "QPX BOT v1.8 — WALK-FORWARD OUT-OF-SAMPLE VALIDATION",
            "QPX BOT v1.10 — WALK-FORWARD OUT-OF-SAMPLE VALIDATION",
        ),
    ],
    ".gitignore": [
        (
            (
                "# QPX persistent paper runtime\n"
                "qpx_bot/paper_runtime/\n"
            ),
            (
                "# QPX persistent paper runtime\n"
                "qpx_bot/paper_runtime/\n"
                "\n"
                "# QPX data-driven selection runtime and reports\n"
                "qpx_bot/selection_runtime/\n"
                "reports/qpx_symbol_selection/\n"
            ),
        ),
    ],
    "qpx_bot/PAPER_TRADING_README.txt": [
        (
            "python QPX_RUN_PAPER.py --symbol SPY",
            "python QPX_RUN_AUTO_PAPER.py",
        ),
    ],
}

TARGET_PATHS = [*FILES, *PATCHES]
originals: dict[str, bytes | None] = {}


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def is_tracked(relative: str) -> bool:
    return subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGET_PATHS:
        path = ROOT / relative
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if worktree.returncode != 0 or staged.returncode != 0:
            changed.append(relative)
            continue

        if (
            relative in FILES
            and path.exists()
            and not is_tracked(relative)
        ):
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain local changes and were "
            "not overwritten:\n" + "\n".join(changed)
        )



def validate_patch_markers() -> None:
    """
    Simulate every source replacement before writing any file.

    This catches formatting drift while the repository is still
    untouched and also verifies sequential duplicate replacements.
    """
    problems: list[str] = []

    for relative, replacements in PATCHES.items():
        path = ROOT / relative

        if not path.exists():
            problems.append(f"{relative}: file not found")
            continue

        content = path.read_text(encoding="utf-8")

        for old, new in replacements:
            if old in content:
                content = content.replace(old, new, 1)
            elif new in content:
                continue
            else:
                problems.append(
                    f"{relative}: missing marker\n{old}"
                )
                break

    if problems:
        raise RuntimeError(
            "Patch preflight failed before any file was changed:\n"
            + "\n\n".join(problems)
        )

def preserve(relative: str) -> None:
    if relative in originals:
        return

    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup_path = BACKUP / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )
        print(f"Installed: {relative}")


def patch_files() -> None:
    for relative, replacements in PATCHES.items():
        path = ROOT / relative

        if not path.exists():
            raise FileNotFoundError(
                f"Required target was not found: {path}"
            )

        preserve(relative)
        content = path.read_text(encoding="utf-8")

        for old, new in replacements:
            if old in content:
                content = content.replace(old, new, 1)
            elif new in content:
                continue
            else:
                raise RuntimeError(
                    f"Expected marker was not found in "
                    f"{relative}:\n{old}"
                )

        path.write_text(content, encoding="utf-8")
        print(f"Updated: {relative}")


def restore() -> None:
    print("Restoring previous target files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGET_PATHS)

    try:
        paths.append(
            str(Path(__file__).resolve().relative_to(ROOT))
        )
    except ValueError:
        pass

    run(["git", "add", "--", *paths])

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print("Data-driven selection is already committed.")
        return

    run([
        "git",
        "commit",
        "-m",
        "Implement QPX Bot data-driven swing symbol selection",
    ])

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError("Cannot push from detached Git state.")

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 78)
    print("QPX BOT — DATA-DRIVEN SYMBOL SELECTION INSTALLER V2")
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    validate_patch_markers()
    install_files()

    try:
        patch_files()
        run([sys.executable, "tests/run_all_tests.py"])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print("Running the first symbol-neutral ranking and paper cycle...")
    print()

    try:
        run([
            sys.executable,
            "QPX_RUN_AUTO_PAPER.py",
            "--force-reselect",
        ])
    except Exception:
        print()
        print("=" * 78)
        print("QPX DATA-DRIVEN SELECTION CODE: INSTALLED AND PUSHED")
        print("LIVE RANKING/PAPER RUN: NEEDS RETRY")
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_RUN_AUTO_PAPER.py --force-reselect"
        )
        return 2

    print()
    print("=" * 78)
    print("QPX DATA-DRIVEN SYMBOL SELECTION: COMPLETE")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
