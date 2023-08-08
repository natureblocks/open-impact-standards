class Pipeline:
    def __init__(self, thread_scope):
        self.thread_scope = thread_scope

        # {pipeline_scope: {var_name: PipelineVariable}}
        self.variables = {}

    def set_variable(self, pipeline_scope, var_name, pipeline_variable):
        if pipeline_scope not in self.variables:
            self.variables[pipeline_scope] = {}

        self.variables[pipeline_scope][var_name] = pipeline_variable

    def get_variable(self, var_name, within_scope, return_scope=False):
        scope_path = within_scope.split(".")
        while len(scope_path):
            scope = ".".join(scope_path)
            scope_path.pop()

            if scope not in self.variables:
                continue

            if var_name in self.variables[scope]:
                if return_scope:
                    return scope
                return self.variables[scope][var_name]

        return None

    def get_thread_id(self):
        return self.thread_scope.split(".")[-1] if self.thread_scope else None
