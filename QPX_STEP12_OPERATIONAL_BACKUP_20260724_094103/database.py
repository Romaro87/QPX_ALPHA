
"""
QPX Alpha Step 10 Database Compatibility Layer

Compatibility only.
Does not modify database lifecycle.
"""


class Database:

    def __init__(self):
        self.connected = True


    def save_trade(self, trade):
        return True


    def query(self, request=None):
        return []


def get_database():

    return Database()
