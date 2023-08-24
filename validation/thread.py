class ThreadGroup:
    def __init__(self):
        self.scope = None

        # TODO: determine whether it makes more sense for this to be plural or singular
        # {variable_name: FieldTypeDetails}
        self.variables = {}

        self.sub_thread_ids = []
        self.action_ids = []

        # checkpoints that specifically reference this thread as their context
        self.checkpoints = []

    def has_access_to_context(self, thread_id):
        if self.scope is None:
            return False

        return thread_id in self.scope.split(".")
