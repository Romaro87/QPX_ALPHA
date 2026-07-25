from core.portfolio_manager import PortfolioManager


def test_create():

    obj = PortfolioManager()

    assert obj is not None


def test_execute():

    obj = PortfolioManager()

    obj.execute()