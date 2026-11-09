"""Strict JSON, contained paths and private atomic file output."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f'Nonfinite JSON number: {value}')
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=invalid)


def contained(root, relative):
    root = Path(root).resolve(strict=True)
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Expected a relative evidence/source path')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Path escapes its root')
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlinked evidence/source path')
    if not current.resolve().is_relative_to(root):
        raise ValueError('Path escapes its root')
    return current


def private_write(path, text, *, exclusive=False):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing symlinked output')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value, *, exclusive=False):
    private_write(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', exclusive=exclusive)
