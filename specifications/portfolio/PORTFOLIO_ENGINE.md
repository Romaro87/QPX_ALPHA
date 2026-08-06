# Portfolio Engine Specification

Version: 1.0

Status:
Draft

------------------------------------------------------------

## Purpose

The Portfolio Engine is the financial source of truth for
QPX_ALPHA.

It maintains portfolio state independently of trading
strategies and broker implementations.

------------------------------------------------------------

## Responsibilities

• Track cash balances

• Track holdings

• Track realized gains/losses

• Track unrealized gains/losses

• Track dividends

• Track tax reserves

• Track monthly contributions

• Maintain historical portfolio snapshots

------------------------------------------------------------

## Core Components

Cash Account

Investment Accounts

Dividend Ledger

Tax Reserve Ledger

Contribution Ledger

Position Registry

Allocation Manager

Performance Calculator

------------------------------------------------------------

## Position Data

Each position should maintain:

• Symbol

• Quantity

• Average Cost Basis

• Current Market Value

• Unrealized Gain/Loss

• Realized Gain/Loss

• Dividend Income

• Allocation Percentage

------------------------------------------------------------

## Cash Management

The engine should support:

Operating Cash

Dividend Cash

Contribution Cash

Tax Reserve Cash

Available Buying Power

------------------------------------------------------------

## Allocation Engine

The allocation manager should support:

Target allocations

Current allocations

Rebalancing recommendations

Strategy allocations

Portfolio drift analysis

------------------------------------------------------------

## Dividend Management

Record:

Dividend declarations

Payment dates

Dividend cash

Dividend reinvestment

Income reporting

------------------------------------------------------------

## Tax Management

Maintain configurable tax reserve.

Record:

Realized gains

Realized losses

Estimated tax liability

Tax reserve balance

------------------------------------------------------------

## Performance Metrics

Portfolio Value

Net Asset Value

Total Return

Income Return

Annualized Return

Maximum Drawdown

Sharpe Ratio

Allocation History

------------------------------------------------------------

## Interfaces

Consumes:

Market Data Engine

Execution Engine

Broker Interface

Provides:

Portfolio State

Account Balances

Performance Metrics

Allocation Data

------------------------------------------------------------

## Future Features

Multi-account support

Retirement accounts

Margin accounts

Options positions

Cryptocurrency

Multi-currency

Family portfolios

------------------------------------------------------------

End of Specification
