from django.conf import settings

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import MOUSignature, MOU

from cis.middleware import current_request

@receiver(post_save, sender=MOUSignature)
def status_updated(sender, instance, **kwargs):
    from datetime import datetime

    previous_status = instance.tracker.previous('status')
    status = instance.status

    print(previous_status, status)
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
