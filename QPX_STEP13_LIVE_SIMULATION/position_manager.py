
class PositionManager:

    def __init__(self):

        self.positions = []


    def open_position(self, trade):

        self.positions.append(trade)

        return trade


    def get_positions(self):

        return self.positions
