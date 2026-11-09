"""Game text checks over every string value in a JSON file."""
import json

from .findings import finding


def check_text(rel, data, cls):
    try:
        document = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        return [finding('BLOCKER', 'unreadable', rel, f'not UTF-8 JSON: {error}')]
    found = []
    for key, value in strings(document):
        where = f'{rel}#{key}'
        limit = cls.get('max_chars')
        if limit and len(value) > limit:
            found.append(finding('HIGH', 'max_chars', where, f'{len(value)} chars > {limit}: {value[:60]!r}'))
        found += [finding('MEDIUM', 'forbidden', where, f'contains {pattern!r}')
                  for pattern in cls.get('forbidden', []) if pattern in value]
    return found


def strings(node, prefix=''):
    if isinstance(node, str):
        yield prefix or '$', node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, f'{prefix}.{key}' if prefix else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from strings(value, f'{prefix}[{index}]')
