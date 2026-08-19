from unittest.mock import patch

from django.test import TestCase, override_settings

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition
from cis.models.settings import Setting
from cis.models.term import AcademicYear


def _models():
    try:
        from mou.mou.models import MOU, MOUSignator, MOUSignature
        from mou.mou.settings.helpers import notification_recipients
        mail_path = 'mou.mou.models.send_html_mail'
    except ImportError:
        from mou.models import MOU, MOUSignator, MOUSignature
        from mou.settings.helpers import notification_recipients
        mail_path = 'mou.models.send_html_mail'
    return MOU, MOUSignator, MOUSignature, notification_recipients, mail_path


def _setting_keys():
    return ('mou.mou.settings.email_settings', 'mou.settings.email_settings')


def _write_cfg(value):
    for key in _setting_keys():
        Setting.objects.update_or_create(key=key, defaults={'value': value})


MAIL_PATH = _models()[-1]


@override_settings(DEBUG=False)
class NotificationRoutingTests(TestCase):
    def test_is_active_no_returns_none(self):
        _, _, _, notification_recipients, _ = _models()
        cfg = {'is_active': 'No', 'notify_address': 'ops@example.com'}
        self.assertIsNone(notification_recipients(['a@b.com'], cfg))

    def test_is_active_debug_uses_notify_address(self):
        _, _, _, notification_recipients, _ = _models()
        cfg = {'is_active': 'Debug', 'notify_address': 'ops@example.com,b@c.com'}
        self.assertEqual(
            notification_recipients(['signer@example.com'], cfg),
            ['ops@example.com', 'b@c.com'],
        )

    def test_is_active_yes_uses_intended(self):
        _, _, _, notification_recipients, _ = _models()
        cfg = {'is_active': 'Yes', 'notify_address': 'ops@example.com'}
        self.assertEqual(
            notification_recipients(['signer@example.com'], cfg),
            ['signer@example.com'],
        )


@override_settings(DEBUG=False)
class ReminderEmailTests(TestCase):
    def setUp(self):
        MOU, MOUSignator, MOUSignature, _ = _models()[:4]
        self.creator = CustomUser.objects.create(username='c', email='c@example.com')
        self.signer = CustomUser.objects.create(
            username='s', email='signer@example.com', first_name='Sam', last_name='Signer',
        )
        self.hs = HighSchool.objects.create(name='Test HS', code='000001', status='active')
        pos = HSPosition.objects.create(name='Principal')
        ay = AcademicYear.objects.create(name='2026-27')
        self.mou = MOU.objects.create(
            title='Test MOU', cron='0 7 * * *', academic_year=ay, created_by=self.creator,
        )
        tpl = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=1,
            role_type='highschool_admin', role=pos.id, meta={},
        )
        self.signature = MOUSignature.objects.create(
            highschool=self.hs, signator=self.signer, signator_template=tpl,
            status='', meta={'role': 'Principal'},
        )

    @patch(MAIL_PATH)
    def test_first_pending_send_uses_request_copy(self, mock_send):
        _write_cfg({
            'is_active': 'Yes',
            'email_subject': 'Please sign',
            'email_message': 'FIRST {{signator_firstname}}',
            'reminder_email_subject': 'Reminder',
            'reminder_email_message': 'REMINDER {{signator_firstname}}',
            'notify_address': 'ops@example.com',
        })
        self.signature.send_notification()
        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(mock_send.call_args[0][0], 'Please sign')
        self.assertIn('FIRST Sam', mock_send.call_args[0][1])
        self.signature.refresh_from_db()
        self.assertEqual(self.signature.meta.get('notification_count'), 1)
        self.assertEqual(self.signature.status, 'pending')
        self.assertTrue(self.signature.meta.get('notified_on'))

    @patch(MAIL_PATH)
    def test_later_pending_send_uses_reminder_copy(self, mock_send):
        _write_cfg({
            'is_active': 'Yes',
            'email_subject': 'Please sign',
            'email_message': 'FIRST {{signator_firstname}}',
            'reminder_email_subject': 'Reminder',
            'reminder_email_message': 'REMINDER {{signator_firstname}}',
            'notify_address': 'ops@example.com',
        })
        self.signature.meta['notification_count'] = 1
        self.signature.save()
        self.signature.send_notification()
        self.assertEqual(mock_send.call_args[0][0], 'Reminder')
        self.assertIn('REMINDER Sam', mock_send.call_args[0][1])

    @patch(MAIL_PATH)
    def test_inactive_send_does_not_mark_pending(self, mock_send):
        _write_cfg({
            'is_active': 'No',
            'email_subject': 'Please sign',
            'email_message': 'FIRST',
            'notify_address': 'ops@example.com',
        })
        self.signature.send_notification()
        mock_send.assert_not_called()
        self.signature.refresh_from_db()
        self.assertEqual(self.signature.status, '')
        self.assertFalse(self.signature.meta.get('notified_on'))

    @patch(MAIL_PATH)
    def test_signing_marks_next_person_next_up(self, mock_send):
        MOU, MOUSignator, MOUSignature = _models()[:3]
        later = CustomUser.objects.create(
            username='t', email='two@example.com', first_name='Two', last_name='Signer',
        )
        tpl2 = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=2,
            role_type='highschool_admin', role=self.signature.signator_template.role,
            meta={},
        )
        sig2 = MOUSignature.objects.create(
            highschool=self.hs, signator=later, signator_template=tpl2,
            status='', meta={'role': 'Counselor'},
        )
        nxt = self.signature.next_signator()
        self.assertEqual(nxt.id, sig2.id)
        sig2.refresh_from_db()
        self.assertEqual(sig2.status, 'next')
        self.assertFalse(sig2.meta.get('notified_on'))

    def test_get_link_marks_next_up_pending(self):
        self.signature.status = 'next'
        self.signature.save()
        self.assertTrue(self.signature.mark_pending_from_signature_link())
        self.signature.refresh_from_db()
        self.assertEqual(self.signature.status, 'pending')
        # Copying a link is not a send, so it must not claim one happened.
        self.assertFalse(self.signature.meta.get('notified_on'))
        self.assertFalse(self.signature.meta.get('notification_count'))

    def test_get_link_does_not_skip_ahead_in_chain(self):
        MOU, MOUSignator, MOUSignature = _models()[:3]
        later = CustomUser.objects.create(
            username='skip', email='skip@example.com',
        )
        tpl2 = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=2,
            role_type='highschool_admin', role=self.signature.signator_template.role,
            meta={},
        )
        sig2 = MOUSignature.objects.create(
            highschool=self.hs, signator=later, signator_template=tpl2,
            status='', meta={'role': 'Counselor'},
        )
        self.assertFalse(sig2.mark_pending_from_signature_link())
        sig2.refresh_from_db()
        self.assertEqual(sig2.status, '')
