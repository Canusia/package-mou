from django.conf import settings

from django.db.models.signals import pre_save, post_save, post_migrate
from django.dispatch import receiver

from .models import MOUSignature, MOU

from cis.middleware import current_request


# Default cadence at which the host's cron_jobs.py invokes send_mou_emails to
# check whether any individual MOU's schedule fires inside the current cron
# window. Per-MOU cadence is still controlled by MOU.cron — this just
# determines how often the dispatcher polls.
SEND_MOU_EMAILS_DEFAULT_CRON = '*/5 * * * *'


@receiver(post_migrate)
def _register_send_mou_emails_cron(sender, **kwargs):
    """Auto-register a CronTab row so the host's cron_jobs.py picks up
    send_mou_emails without each tenant having to edit cron_jobs.py.

    Only acts for this app's post_migrate to avoid duplicate work.
    """
    if sender is None or sender.label != 'mou':
        # Both MOUConfig (name='mou') and DevMOUConfig (name='mou.mou') resolve
        # to label 'mou', so this filter works regardless of install mode.
        return

    from cis.models.crontab import CronTab
    CronTab.objects.get_or_create(
        command='send_mou_emails',
        defaults={'cron': SEND_MOU_EMAILS_DEFAULT_CRON},
    )

@receiver(post_save, sender=MOUSignature)
def status_updated(sender, instance, **kwargs):
    from datetime import datetime

    previous_status = instance.tracker.previous('status')
    status = instance.status

    if previous_status != status:
        if status == 'signed':
            instance.send_notification()
            instance.next_signator()

@receiver(post_save, sender=MOU)
def status_updated(sender, instance, **kwargs):
    from datetime import datetime

    previous_status = instance.tracker.previous('status')
    status = instance.status

    if previous_status != status:
        if status == 'ready':
            # instance.initialize_signatures()
            instance.initialize_signature_status()
