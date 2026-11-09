"""Export only explicitly selected model metadata, never configuration secrets."""
from .model_policy import ConfigurationError, ModelSelection


def export_catalog(profiles, read_profile):
    result = {'profiles': {}}
    for role in profiles:
        config = read_profile(role)
        model = config.get('model')
        if not isinstance(model, dict) or not model.get('provider') or not model.get('default'):
            raise ConfigurationError(f'Explicit model/provider configuration is required for {role}')
        default = {'provider': model['provider'], 'model': model['default']}
        ModelSelection(**default)
        candidates = [default, *config.get('factory_models', [])]
        models = {(item['provider'], item['model']): {'provider': item['provider'], 'model': item['model'], 'compatible': item.get('compatible', True)} for item in candidates}
        result['profiles'][role] = {'default': default, 'models': list(models.values())}
    return result
