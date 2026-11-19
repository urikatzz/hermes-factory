#!/usr/bin/env python3
"""Check and provision the scoped secrets Factory workers need, without ever printing a secret value.

Hermes strips secrets from the commands a worker runs, and refuses to forward provider credential names (OPENROUTER_API_KEY, ...)
on purpose. A worker that needs a key therefore declares a dedicated, non-provider name in its profile's
``terminal.env_passthrough``; Hermes then supplies that one value from the profile's own ``.env`` to that profile's commands only.
Workers never load a ``.env`` themselves and the value never enters a card, handoff or artifact.

  factory_secrets.py doctor [--profile P]      report problems per profile (names only, never values)
  factory_secrets.py set PROFILE NAME          read the value from a hidden prompt and store it in the profile's .env (mode 600)
"""
import argparse
import getpass
import os
from pathlib import Path
import re
import sys

REQUIRED = {'art-reviewer': ['FACTORY_SIMILARITY_API_KEY']}
NAME = re.compile(r'[A-Z][A-Z0-9_]{2,63}')


def hermes_home():
    return Path(os.environ.get('HERMES_HOME', Path.home() / '.hermes'))


def env_values(path):
    """{name: value} from a .env file; callers must not print the values."""
    values = {}
    try:
        for line in Path(path).read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                name, value = line.split('=', 1)
                values[name.strip()] = value.strip().strip('"\'')
    except OSError:
        pass
    return values


def passthrough_names(config_path):
    """terminal.env_passthrough from a profile config, read without a YAML dependency (a short, flat list)."""
    try:
        lines = Path(config_path).read_text().splitlines()
    except OSError:
        return []
    names, state = [], 0
    for line in lines:
        if state == 0 and re.fullmatch(r'terminal:\s*', line):
            state = 1
        elif state == 1 and re.fullmatch(r'  env_passthrough:\s*', line):
            state = 2
        elif state == 2:
            match = re.fullmatch(r'  - (\S+)\s*', line)
            if not match:
                break
            names.append(match.group(1))
        elif state == 1 and line and not line.startswith(' '):
            break
    return names


def provider_blocked(name):
    """Hermes' own provider-credential guard, when its source is importable; otherwise unknown (None)."""
    source = hermes_home() / 'hermes-agent'
    if not (source / 'tools/env_passthrough.py').exists():
        return None
    sys.path.insert(0, str(source))
    try:
        from tools.env_passthrough import _is_hermes_provider_credential
        return bool(_is_hermes_provider_credential(name))
    except Exception:
        return None
    finally:
        sys.path.remove(str(source))


def check_profile(home, profile, required, blocked=provider_blocked):
    """Problems preventing `profile` from receiving each required secret; empty when every one will arrive. Names only."""
    problems = []
    base = Path(home) / 'profiles' / profile
    declared = passthrough_names(base / 'config.yaml')
    values = env_values(base / '.env')
    for name in required:
        if blocked(name):
            problems.append(f'{name}: Hermes refuses to forward this provider credential name; use a dedicated non-provider name')
            continue
        if name not in declared:
            problems.append(f'{name}: not listed under terminal.env_passthrough in profiles/{profile}/config.yaml')
        if not values.get(name):
            problems.append(f'{name}: no value in profiles/{profile}/.env (run: factory_secrets.py set {profile} {name})')
    for name in declared:
        if blocked(name):
            problems.append(f'{name}: listed in env_passthrough but Hermes will never forward it (provider credential); remove it')
    return problems


def set_secret(home, profile, name, value):
    """Store `value` as NAME in the profile's .env. Only declared required names; never a provider credential name."""
    if name not in REQUIRED.get(profile, []):
        raise SystemExit(f'{name} is not a declared secret of profile {profile}')
    if not NAME.fullmatch(name) or provider_blocked(name):
        raise SystemExit(f'{name} cannot be used: provider credential names are never forwarded to workers')
    if not value or '\n' in value or len(value) < 8:
        raise SystemExit('The value looks empty or malformed; nothing was written')
    path = Path(home) / 'profiles' / profile / '.env'
    lines = [l for l in (path.read_text().splitlines() if path.exists() else []) if not l.startswith(name + '=')]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join([*lines, f'{name}={value}']) + '\n')
    path.chmod(0o600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    doctor = sub.add_parser('doctor')
    doctor.add_argument('--profile')
    setter = sub.add_parser('set')
    setter.add_argument('profile')
    setter.add_argument('name')
    args = parser.parse_args(argv)
    if args.command == 'set':
        if not sys.stdin.isatty():
            raise SystemExit('Run this in a terminal: the value is read from a hidden prompt, never from arguments or pipes')
        set_secret(hermes_home(), args.profile, args.name, getpass.getpass(f'Value for {args.name} (hidden): '))
        print(f'stored {args.name} for {args.profile} (value not shown)')
        return 0
    failed = False
    for profile, names in REQUIRED.items():
        if args.profile in (None, profile):
            problems = check_profile(hermes_home(), profile, names)
            print(f'{profile}: ' + ('ok' if not problems else f'{len(problems)} problem(s)'))
            for problem in problems:
                print('  - ' + problem)
            failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
