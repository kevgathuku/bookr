from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    name = "scheduling"

    def ready(self):
        # Relocated models: Django auto-imports only <app>.models, so the
        # appointments module registers here (after all models load: no cycle).
        from scheduling import appointments  # noqa: F401
