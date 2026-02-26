from django.apps import AppConfig

class ObservacionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Apps.observaciones'   # <-- IMPORTANTE
    verbose_name = 'Observaciones'