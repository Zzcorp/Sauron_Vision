"""Platform-level periodic tasks."""
from celery import shared_task


@shared_task
def send_component_digest_task():
    """Daily: tell the operator what is quietly broken.

    Deliberately NOT wrapped in `guarded_task`. Every other periodic task on
    this platform is gated by its own PlatformComponent row, which is right
    — an operator who switches a scraper off means it. But this task's whole
    job is to report the state of those rows, and a health check that can be
    silenced by the same switch it is watching is a health check that goes
    quiet exactly when the platform does.

    It is still bounded: `render_digest` returns nothing when there is
    nothing wrong, so a healthy platform sends no message at all.
    """
    from core.component_digest import send_component_digest
    return send_component_digest()
