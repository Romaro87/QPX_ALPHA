
import datetime


class LiveTradeJournal:

    def __init__(self):

        self.entries = []


    def record(self, event):

        self.entries.append(
            {
                "time": datetime.datetime.now().isoformat(),
                "event": event
            }
        )


    def get_entries(self):

        return self.entries
