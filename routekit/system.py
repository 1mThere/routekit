import os
import subprocess
from pathlib import Path


class CommandError(RuntimeError):
    pass


def run(argv, check=True, capture=False, quiet=False):
    if capture or quiet:
        p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        p = subprocess.run(argv)
    if check and p.returncode != 0:
        detail = ''
        if capture or quiet:
            detail = f'\nstdout: {p.stdout}\nstderr: {p.stderr}'
        raise CommandError(f'command failed: {argv}{detail}')
    return p


def out(argv):
    return run(argv, capture=True).stdout


def atomic_write(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(data, encoding='utf-8')
    os.chmod(tmp, mode)
    tmp.replace(path)


def service_restart(name):
    script = Path('/etc/init.d') / name
    if script.exists():
        run([str(script), 'restart'], check=False, quiet=True)


def service_reload(name):
    script = Path('/etc/init.d') / name
    if script.exists():
        run([str(script), 'reload'], check=False, quiet=True)
