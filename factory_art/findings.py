"""Finding records shared by every art check."""

SEVERITIES = ('BLOCKER', 'HIGH', 'MEDIUM', 'LOW', 'NIT')
BLOCKING = ('BLOCKER', 'HIGH')


def finding(severity, check, file, problem):
    if severity not in SEVERITIES:
        raise ValueError(f'Unknown severity {severity!r}')
    return {'severity': severity, 'check': check, 'file': file, 'problem': problem}


def override(found, levels):
    return [dict(item, severity=levels.get(item['check'], item['severity'])) for item in found]


def ordered(found):
    return sorted(found, key=lambda item: (SEVERITIES.index(item['severity']), item['file'], item['check']))


def lines(found):
    return [f"F{number}|{item['severity']}|{item['check']}|{item['file']}|{item['problem'].replace('|', '/')}"
            for number, item in enumerate(found, 1)]
