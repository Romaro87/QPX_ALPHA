#!/usr/bin/env python3
"""Migrate the live paper account to the updated capital model."""

from qpx_bot.capital_migration import (
    migrate_paper_capital_and_allocation,
)


if __name__ == "__main__":
    print(
        migrate_paper_capital_and_allocation()
    )
