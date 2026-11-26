"""Does this Hermes carry the local patches the Factory needs?

A Hermes update resets its source tree to an upstream commit, which removes the Factory's patches (see runtime/hermes-patches). Without them
the plugin's hooks are rejected (an unknown hook name only logs a warning) and stage creation fails on a missing module, so the plugin
checks for them when it loads, says so loudly, and does not claim run-board support.
"""
import importlib.util

REQUIRED_MODULES = ('hermes_cli.kanban_db_mutation_guard', 'hermes_cli.kanban_db_task_creation', 'hermes_cli.kanban_db_worker_model')
REQUIRED_HOOKS = ('resolve_kanban_worker_model', 'before_kanban_task_create', 'before_kanban_task_mutation',
                  'on_kanban_dispatch_tick', 'kanban_task_completed')
REMEDY = 'run `python3 runtime/hermes-patches/hermes_patches.py apply` (or the installed copy in ~/.hermes/hermes-patches), then restart the Hermes gateway'


class HermesUnpatched(RuntimeError):
    """Hermes lacks the Factory patches. Never turned into a project stop: the whole controller transaction rolls back."""


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def compat_report():
    missing_modules = [name for name in REQUIRED_MODULES if not _has_module(name)]
    try:
        from hermes_cli import plugins
        valid = set(plugins.VALID_HOOKS)
    except Exception:
        valid = set()
    missing_hooks = [name for name in REQUIRED_HOOKS if name not in valid]
    ok = not missing_modules and not missing_hooks
    message = '' if ok else ('missing modules: ' + (', '.join(missing_modules) or 'none') + '; hook names Hermes does not know: ' + (', '.join(missing_hooks) or 'none'))
    return dict(ok=ok, missing_modules=missing_modules, missing_hooks=missing_hooks, message=message, remedy=REMEDY)


def require_patched(action):
    """Refuse `action` on a Hermes without the Factory patches: a run continues only where the Factory stopped, never with untracked cards."""
    report = compat_report()
    if not report['ok']:
        raise HermesUnpatched('Cannot ' + action + ': Hermes lacks patches the Factory needs (' + report['message'] + '). ' + REMEDY[0].upper() + REMEDY[1:] + ', then try again.')
