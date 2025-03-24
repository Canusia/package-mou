import logging, datetime, json
from django.core.management.base import BaseCommand

from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

from mou.models import MOU, MOUSignature

class Command(BaseCommand):
    '''
    Daily jobs
    '''
    help = ''

    def handle(self, *args, **kwargs):
        # get all 'ready to send' messages
        ready_mous = MOU.objects.filter(
            status='ready',
            send_on_after__lte=datetime.datetime.now(),
            send_until__gte=timezone.now()
        )

        summary = {}
        for mou in ready_mous:
            if mou.should_message_be_sent():
                pending_signatures = MOUSignature.objects.filter(
                    status='pending',
                    signator_template__mou=mou
                )

                summary[str(mou.id)] = 'Sending to ' + str(pending_signatures.count())
                for pending_signature in pending_signatures:
                    pending_signature.send_notification()
            else:
                summary[str(mou.id)] = 'Not scheduled to be sent'
        