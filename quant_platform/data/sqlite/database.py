
import sqlite3
from pathlib import Path


class SQLiteDatabase:

    def __init__(self, db_path="qpx_mobile.db"):
        self.db_path = Path(db_path)
        self.connection = None


    def connect(self):
        self.connection = sqlite3.connect(
            self.db_path
        )
        return self.connection


    def execute(self, query, params=None):

        cursor = self.connection.cursor()

        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        self.connection.commit()

        return cursor


    def fetch_all(self, query):

        cursor = self.connection.cursor()
        cursor.execute(query)

        return cursor.fetchall()


    def close(self):

        if self.connection:
            self.connection.close()
