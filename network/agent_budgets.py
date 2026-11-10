"""Agent container budgets and session lifetime: validation and normalization.

The wrapper validates the same values in Bash because unrestricted installations
may lack host Python; tests feed identical cases to both implementations.
"""
import re

DEFAULTS = {'MEMORY_LIMIT': '4g', 'CPU_LIMIT': '2', 'PIDS_LIMIT': '512', 'RUN_TIMEOUT': '0'}
SUFFIXES = tuple(DEFAULTS)
MAX_PIDS = 4194304
MAX_TIMEOUT = 2147483647
MAX_MEMORY = 1 << 50
MAX_CPUS = 1024
UNITS = {'k': 1 << 10, 'm': 1 << 20, 'g': 1 << 30}
MEMORY = re.compile(r'([1-9][0-9]{0,15})([kmgKMG])')
CPU = re.compile(r'([0-9]{1,4})(?:\.([0-9]{1,3}))?')
INTEGER = re.compile(r'(0|[1-9][0-9]{0,9})')
FORMATS = {
    'MEMORY_LIMIT': 'a positive integer with unit k, m or g, for example 4g',
    'CPU_LIMIT': 'a positive number of CPUs with at most 3 decimals, for example 2 or 1.5',
    'PIDS_LIMIT': 'a positive integer process count up to ' + str(MAX_PIDS),
    'RUN_TIMEOUT': 'whole seconds; 0 disables the lifetime limit',
}


class BudgetError(ValueError):
    pass


def memory(text):
    match = MEMORY.fullmatch(text)
    value = int(match[1]) * UNITS[match[2].lower()] if match else 0
    if not 0 < value <= MAX_MEMORY:
        raise BudgetError('MEMORY_LIMIT')
    return value


def cpus(text):
    match = CPU.fullmatch(text)
    value = int(match[1]) * 10**9 + int((match[2] or '').ljust(3, '0')) * 10**6 if match else 0
    if not 0 < value <= MAX_CPUS * 10**9:
        raise BudgetError('CPU_LIMIT')
    return value


def pids(text):
    match = INTEGER.fullmatch(text)
    if not match or not 0 < int(text) <= MAX_PIDS:
        raise BudgetError('PIDS_LIMIT')
    return int(text)


def timeout(text):
    # Empty means disabled, like unset; only digits are accepted otherwise.
    if text == '':
        return 0
    if not INTEGER.fullmatch(text) or int(text) > MAX_TIMEOUT:
        raise BudgetError('RUN_TIMEOUT')
    return int(text)


PARSERS = {'MEMORY_LIMIT': memory, 'CPU_LIMIT': cpus, 'PIDS_LIMIT': pids, 'RUN_TIMEOUT': timeout}


def normalize(values):
    """Map suffix -> raw text (None = unset) to the normalized hardening record."""
    result = {}
    for suffix, key in (('MEMORY_LIMIT', 'memory'), ('CPU_LIMIT', 'nano_cpus'),
                        ('PIDS_LIMIT', 'pids'), ('RUN_TIMEOUT', 'timeout')):
        raw = values.get(suffix)
        result[key] = PARSERS[suffix](DEFAULTS[suffix] if raw is None else raw)
    return result


def from_environment(environ, profile):
    return normalize({suffix: environ.get(profile.env(suffix)) for suffix in SUFFIXES})


def canonical(suffix, text):
    """Validate one setup answer and return the string saved in preferences."""
    PARSERS[suffix](text)
    return text.lower() if suffix == 'MEMORY_LIMIT' else ('0' if suffix == 'RUN_TIMEOUT' and text == '' else text)


def agent_hardening(environ, profile):
    return dict(capabilities=[], no_new_privs=True, **from_environment(environ, profile))
