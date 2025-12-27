class PriceBuffer:
    '''Basic circular buffer implementation for maintaining price history
       O(1) append, O(1) access by index, O(n) last_n_obj access
    '''
    def __init__(self, max_size=500):
        self.buffer = [None] * max_size
        self.capacity = max_size

        self.head = 0
        self.size = 0

    def add(self, elem):

        idx = (self.head + self.size) % self.capacity

        self.buffer[idx] = elem

        if self.size < self.capacity:
            self.size += 1
        else:
            self.head = (self.head + 1) % self.capacity

    def __getitem__(self, idx):
        if idx >= self.size or idx < 0:
            raise IndexError("Invalid index")
        
        index = (self.head + idx) % self.capacity
        return self.buffer[index]

    def get_last_n(self, n):
        n = min(n, self.size)
        start_idx = self.size - n
        return [self[i] for i in range(start_idx, self.size)]

    def __len__(self):
        return self.size
