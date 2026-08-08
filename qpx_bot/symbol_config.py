from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SYMBOL_CONFIG = (
    Path(__file__).resolve().parent
    / "symbols.json"
)


@dataclass(frozen=True, slots=True)
class SymbolConfig:
    candidate_symbols: tuple[str, ...]
    tradable_symbols: tuple[str, ...]
    income_symbol: str
    volatility_symbol: str

    def validate(self) -> None:
        if not self.candidate_symbols:
            raise ValueError(
                "At least one candidate symbol is required."
            )

        if (
            len(set(self.candidate_symbols))
            != len(self.candidate_symbols)
        ):
            raise ValueError(
                "Candidate symbols must be unique."
            )

        if not self.tradable_symbols:
            raise ValueError(
                "At least one tradable symbol is required."
            )

        if not set(
            self.tradable_symbols
        ).issubset(
            self.candidate_symbols
        ):
            raise ValueError(
                "Tradable symbols must be candidates."
            )

        if not self.income_symbol:
            raise ValueError(
                "Income symbol cannot be empty."
            )

        if not self.volatility_symbol:
            raise ValueError(
                "Volatility symbol cannot be empty."
            )


def load_symbol_config(
    filename: str | Path = DEFAULT_SYMBOL_CONFIG,
) -> SymbolConfig:

    payload = json.loads(
        Path(filename).read_text(
            encoding="utf-8"
        )
    )

    config = SymbolConfig(
        candidate_symbols=tuple(
            str(value).strip().upper()
            for value in payload[
                "candidate_symbols"
            ]
        ),
        tradable_symbols=tuple(
            str(value).strip().upper()
            for value in payload[
                "tradable_symbols"
            ]
        ),
        income_symbol=str(
            payload["income_symbol"]
        ).strip().upper(),
        volatility_symbol=str(
            payload["volatility_symbol"]
        ).strip().upper(),
    )

    config.validate()
    return config
