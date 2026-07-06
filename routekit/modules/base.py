class Module:
    name = 'base'
    priority = 100
    defaults = {}

    def __init__(self, core):
        self.core = core

    def cfg(self):
        return self.core.module_config(self.name, self.defaults)

    def enabled(self):
        return bool(self.cfg().get('enabled', False))

    def preflight(self):
        return []

    def render(self):
        return []

    def apply(self):
        return []

    def status(self):
        return {}
