class PipelineVariable:
    def __init__(
        self,
        type_details,
        initial=None,
        assigned=False,
        is_loop_variable=False,
    ):
        self.type_details = type_details
        self.initial = initial  # relevent for checking null initial value, but irrelevant after assingment
        self.assigned = assigned
        self.used = False
        self.is_loop_variable = is_loop_variable
        self.traversal_scopes = set() # the pipeline scopes that use this variable as a traverse ref
