#!/usr/bin/env python3
"""Run with a Hermes interpreter to export local, profile-scoped model choices."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from factory_dashboard.catalog_export import export_catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-source',type=Path,required=True)
    parser.add_argument('--profile',action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.hermes_source.resolve()))
    from hermes_cli.config import load_config_readonly
    from hermes_cli.profiles import resolve_profile_env
    from hermes_cli.kanban_db_dispatch import _worker_profile_scope
    from hermes_cli.models import list_available_providers, normalize_provider, _PROVIDER_MODELS

    def read_profile(role):
        with _worker_profile_scope(resolve_profile_env(role)):
            config=load_config_readonly()
            model=config.get('model',{})
            if isinstance(model,dict) and model.get('provider'):
                model={**model,'provider':normalize_provider(model['provider'])}
            choices=[]
            for provider in list_available_providers():
                if provider['authenticated']:
                    for entry in _PROVIDER_MODELS.get(provider['id'],[]):
                        name=entry[0] if isinstance(entry,(tuple,list)) else entry
                        if isinstance(name,str): choices.append({'provider':provider['id'],'model':name})
            return {'model':model,'factory_models':choices}

    catalog=export_catalog(args.profile,read_profile)
    from factory_dashboard.renderer import write_report
    write_report(args.output,json.dumps(catalog,indent=2))
    print(f'Exported local model metadata for {len(catalog["profiles"])} profiles to {args.output}')

if __name__=='__main__': main()
