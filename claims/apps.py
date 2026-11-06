from django.apps import AppConfig


class ClaimsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'claims'

    def ready(self):
        from . import signals  # noqa: F401
