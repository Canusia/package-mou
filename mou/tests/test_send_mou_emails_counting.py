"""Regression test for the send_mou_emails summary-count fix.

`current_unsigned_signatures()` can return a row already at
`status='pending'` -- that's the reminder-resend case. When
`send_notification()` bails out before sending (is_active is `No`, Debug
mode with an empty `notify_address`, or no recipient), it returns *before*
touching `status`, so a post-send check of `status == STATUS_PENDING` would
still see 'pending' and wrongly count the row as sent. The fix compares
`meta['notification_count']` before/after instead, since that field is only
incremented on a real send.
"""
import json
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition
from cis.models.settings import Setting
from cis.models.term import AcademicYear


def _models():
    try:
        from mou.mou.models import MOU, MOUSignator, MOUSignature
        cron_done_path = 'mou.mou.management.commands.send_mou_emails.cron_task_done'
    except ImportError:
        from mou.models import MOU, MOUSignator, MOUSignature
        cron_done_path = 'mou.management.commands.send_mou_emails.cron_task_done'
    return MOU, MOUSignator, MOUSignature, cron_done_path


def _setting_keys():
    return ('mou.mou.settings.email_settings', 'mou.settings.email_settings')


def _write_cfg(value):
    for key in _setting_keys():
        Setting.objects.update_or_create(key=key, defaults={'value': value})


@override_settings(DEBUG=False)
class BailedSendIsNotCountedTests(TestCase):
    def setUp(self):
        MOU, MOUSignator, MOUSignature, self.cron_done_path = _models()
        self.creator = CustomUser.objects.create(username='c', email='c@example.com')
        self.signer = CustomUser.objects.create(
            username='s', email='signer@example.com', first_name='Sam', last_name='Signer',
        )
        self.hs = HighSchool.objects.create(name='Test HS', code='000002', status='active')
        pos = HSPosition.objects.create(name='Principal')
        ay = AcademicYear.objects.create(name='2026-27')
        now = timezone.now().replace(microsecond=0, second=0)
        self.mou = MOU.objects.create(
            title='Test MOU', cron='* * * * *', academic_year=ay, created_by=self.creator,
            status='ready',
            send_on_after=now - timezone.timedelta(days=1),
            send_until=now + timezone.timedelta(days=1),
        )
        tpl = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=1,
            role_type='highschool_admin', role=pos.id, meta={},
        )
        # Already 'pending' from a prior cycle -- the reminder-resend case
        # current_unsigned_signatures() still returns this row.
        self.signature = MOUSignature.objects.create(
            highschool=self.hs, signator=self.signer, signator_template=tpl,
            status='pending', meta={'role': 'Principal', 'notification_count': 1},
        )
        _write_cfg({
            # is_active='No' makes notification_recipients() return None, so
            # send_notification() bails out before touching status or meta --
            # exactly the case that used to be miscounted.
            'is_active': 'No',
            'email_subject': 'Please sign',
            'email_message': 'FIRST',
            'reminder_email_subject': 'Reminder',
            'reminder_email_message': 'REMINDER',
            'notify_address': 'ops@example.com',
        })

    def test_bailed_send_on_already_pending_row_is_not_counted(self):
        with patch(self.cron_done_path) as mock_done:
            call_command('send_mou_emails')

        self.signature.refresh_from_db()
        # send_notification bailed out: status and notification_count unchanged.
        self.assertEqual(self.signature.status, 'pending')
        self.assertEqual(self.signature.meta.get('notification_count'), 1)

        summary_detail = json.loads(mock_done.send.call_args.kwargs['detailed_log'])
        self.assertEqual(summary_detail[str(self.mou.id)], 'Sent to 0 of 1 due')
        self.assertIn('Emailed 0 MOU(s) to 0 signer(s)', mock_done.send.call_args.kwargs['summary'])
