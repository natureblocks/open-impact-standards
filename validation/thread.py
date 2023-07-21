class Thread:
    def __init__(self):
        self.scope = None
        self.variables = {}
        self.sub_thread_ids = []
        self.action_ids = []
