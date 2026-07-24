

from datetime import datetime
from uuid import uuid4


REQUIRED_FIELDS = [
'schema_version',
'trade_id',
'symbol',
'timestamp',
'side',
'entry_price',
'quantity',
'exit_price',
'position_status',
'realized_pnl',
'return_pct',
'strategy'
]


def normalize_trade(raw):

    trade = {

        "schema_version":"2.0",

        "trade_id":
            str(uuid4()),

        "symbol":
            raw.get("symbol","UNKNOWN"),

        "timestamp":
            raw.get(
                "timestamp",
                datetime.utcnow().isoformat()
            ),

        "side":
            raw.get("side","UNKNOWN"),

        "entry_price":
            float(
                raw.get(
                    "entry_price",
                    0
                )
            ),

        "quantity":
            float(
                raw.get(
                    "quantity",
                    0
                )
            ),

        "exit_price":
            float(
                raw.get(
                    "exit_price",
                    raw.get(
                        "entry_price",
                        0
                    )
                )
            ),

        "position_status":
            "CLOSED",

        "realized_pnl":
            float(
                raw.get(
                    "realized_pnl",
                    0
                )
            ),

        "return_pct":
            float(
                raw.get(
                    "return_pct",
                    0
                )
            ),

        "strategy":
            raw.get(
                "strategy",
                "unknown"
            )
    }


    validate_trade(trade)

    return trade



def validate_trade(trade):

    missing = [
        x for x in REQUIRED_FIELDS
        if trade.get(x) is None
    ]

    if missing:

        raise Exception(
            f"Schema v2 failure: {missing}"
        )


    if trade["schema_version"] != "2.0":

        raise Exception(
            "Invalid schema version"
        )


    if trade["position_status"] != "CLOSED":

        raise Exception(
            "Metrics require closed trades"
        )


    return True

