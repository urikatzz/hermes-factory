"""Live profile settings composed with the existing report and staged task policy."""
from .model_policy import ConfigurationError


class ProfileService:
    def __init__(self, report_service, profile_settings):
        self._service = report_service
        self._profiles = profile_settings

    def initialize_defaults(self):
        self._service.initialize_defaults()

    def configuration(self, report=None):
        config = self._service.configuration(report)
        profiles = self._profiles.read()
        config['profiles'] = profiles
        config['mode'] = 'Profile model + effort defaults are live for future workers · Task overrides remain preview only'
        config['defaults'] = {role: {'provider': value['provider'], 'model': value['model']} for role, value in profiles.items()}
        for task in config['tasks'].values():
            for role in task['roles']:
                if role in profiles:
                    task['effective'][role] = {'selection': config['defaults'][role], 'source': 'profile_default', 'effort': profiles[role]['effort']}
        return config

    def report(self):
        report = self._service.report()
        report['configuration'] = self.configuration(report)
        return report

    def save_profile(self, role, selection, effort, revision):
        return self._profiles.save(role, selection, effort, revision)

    def save_default(self, *args):
        raise ConfigurationError('Use profile settings to save model and effort together')

    def save_override(self, root_id, selection, revision):
        self._service.save_override(root_id, selection, revision)
        return self.configuration()
