import logging, datetime, json
from django.core.management.base import BaseCommand

from django.utils import timezone
from django.conf import settings

from cis.signals.crontab import cron_task_done, cron_task_started

logger = logging.getLogger(__name__)

from ...models import MOU, MOUSignature

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class Command(BaseCommand):
    '''
    Daily jobs
    '''
    help = ''

    def add_arguments(self, parser):
        parser.add_argument(
            '-t', '--time',
            type=str,
            default=None,
            help='Scheduled run time as "%Y-%m-%d %H:%M:%S". Defaults to the current time.',
        )

    def handle(self, *args, **kwargs):
        time_arg = kwargs.get('time')
        if time_arg:
            now = datetime.datetime.strptime(time_arg, TIME_FORMAT)
            if timezone.is_naive(now):
                now = timezone.make_aware(now, timezone.get_current_timezone())
            scheduled_time = time_arg
        else:
            now = timezone.now()
            scheduled_time = timezone.localtime(now).strftime(TIME_FORMAT)

        cron_task_started.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=scheduled_time,
        )

        # get all 'ready to send' messages
        ready_mous = MOU.objects.filter(
            status='ready',
            send_on_after__lte=now,
            send_until__gte=now,
        )

        summary_detail = {}
        mous_emailed = 0
        signatures_emailed = 0
        for mou in ready_mous:
            if mou.should_message_be_sent(now=now):
                due = mou.current_unsigned_signatures()
                count = due.count()

                summary_detail[str(mou.id)] = f'Sending to {count}'
                for signature in due:
                    signature.send_notification()

                if count:
                    mous_emailed += 1
                    signatures_emailed += count
            else:
                summary_detail[str(mou.id)] = 'Not scheduled to be sent'

        summary = (
            f'Emailed {mous_emailed} MOU(s) to {signatures_emailed} signer(s); '
            f'evaluated {ready_mous.count()} ready MOU(s).'
        )

        cron_task_done.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=scheduled_time,
            summary=summary,
            detailed_log=json.dumps(summary_detail),
        )
