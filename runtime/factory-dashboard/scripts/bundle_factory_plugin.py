#!/usr/bin/env python3
"""Build a self-contained stdlib plugin directory from the dashboard source."""
from pathlib import Path
import argparse
import shutil

ROOT=Path(__file__).resolve().parents[1]


def bundle_plugin(destination: Path):
    destination.mkdir(parents=True,exist_ok=False)
    for name in ('plugin.yaml','__init__.py'):
        shutil.copy2(ROOT/'integrations/hermes_factory_models'/name,destination/name)
    runtime=destination/'factory_dashboard';runtime.mkdir()
    for name in ('__init__.py','model_policy.py','policy_store.py','model_catalog.py','factory_model_resolver.py','task_settings.py','task_settings_store.py','board_registry.py','run_boards.py','task_identity.py','factory_creation.py','frozen_resolver.py','workflow_types.py','workflow_templates.py','workflow_capture.py','workflow_state.py','workflow_guards.py','workflow_controller.py','workflow_cards.py','workflow_handoffs.py','workflow_gate.py','tool_incidents.py','hermes_compat.py'):
        shutil.copy2(ROOT/'factory_dashboard'/name,runtime/name)
    for path in (ROOT/'factory_dashboard').glob('project_*.py'):
        shutil.copy2(path,runtime/path.name)
    return destination

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    args=parser.parse_args();print(bundle_plugin(args.output))
