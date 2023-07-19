class PipelineVariable:
    def __init__(
        self, type_details, initial=None, assigned=False, is_loop_variable=False
    ):
        self.type_details = type_details
        self.initial = initial  # relevent for checking null initial value, but irrelevant after assingment
        self.assigned = assigned
        self.is_loop_variable = is_loop_variable