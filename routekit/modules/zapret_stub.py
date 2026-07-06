from .base import Module


class ZapretStubModule(Module):
    name = 'zapret_stub'
    priority = 60
    defaults = {
        'enabled': False,
        'note': 'placeholder only; real zapret module must be separate',
    }

    def preflight(self):
        return ['zapret_stub is only a placeholder; install a real zapret module'] if self.enabled() else []

    def status(self):
        return {'note': self.cfg().get('note')}
