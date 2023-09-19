class ThreadGroup:
    def __init__(self, schema_id):
        self.schema_id = schema_id
        self.scope = None

        # TODO: determine whether it makes more sense for this to be plural or singular
        # {variable_name: TypeDetails}
        self.variables = {}

        self.sub_thread_group_ids = []
        self.action_refs = []

        # references to checkpoints that specifically reference this thread group as their context
        self.checkpoint_refs = []

    def has_access_to_context(self, thread_group_schema_id, thread_group_id):
        if self.scope is None or thread_group_schema_id != self.schema_id:
            return False

        return thread_group_id in self.scope.split(".")
