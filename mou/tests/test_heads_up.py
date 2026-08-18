import uuid
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
        mail_path = 'mou.mou.models.send_html_mail'
    except ImportError:
        from mou.models import MOU, MOUSignator, MOUSignature
        mail_path = 'mou.models.send_html_mail'
    return MOU, MOUSignator, MOUSignature, mail_path


def _write_cfg(value):
    for key in ('mou.mou.settings.email_settings', 'mou.settings.email_settings'):
        Setting.objects.update_or_create(key=key, defaults={'value': value})


MAIL_PATH = _models()[-1]


HEADS_UP_ON = {
    'is_active': 'Yes',
    'notify_address': 'ops@example.com',
    'email_subject': 'Please sign',
    'email_message': 'SIGN {{signator_firstname}} {{signature_url}}',
    'reminder_email_subject': 'Reminder',
    'reminder_email_message': 'REMIND {{signator_firstname}}',
    'heads_up_email': 'Yes',
    'heads_up_include_college': 'Yes',
    'heads_up_email_subject': 'Coming up {{highschool_name}}',
    'heads_up_email_message': (
        'HEADS {{signator_firstname}} {{role}} {{academic_year}} {{signature_url}}'
    ),
}


@override_settings(DEBUG=False)
class HeadsUpEmailTests(TestCase):
    def setUp(self):
        MOU, MOUSignator, MOUSignature, _ = _models()
        self.creator = CustomUser.objects.create(username='c', email='c@example.com')
        self.first = CustomUser.objects.create(
            username='first', email='first@example.com',
            first_name='Fay', last_name='First',
        )
        self.later = CustomUser.objects.create(
            username='later', email='later@example.com',
            first_name='Lee', last_name='Later',
        )
        self.college = CustomUser.objects.create(
            username='vp', email='vp@example.com',
            first_name='Val', last_name='Provost', is_staff=True,
        )
        self.hs = HighSchool.objects.create(name='North HS', code='N1', status='Active')
        self.pos = HSPosition.objects.create(name='Principal')
        self.ay = AcademicYear.objects.create(name='2026-27')
        self.mou = MOU.objects.create(
            title='District MOU', cron='0 7 * * *', academic_year=self.ay,
            created_by=self.creator,
        )
        self.tpl_first = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=1,
            role_type='highschool_admin', role=self.pos.id, meta={},
        )
        self.tpl_later = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=2,
            role_type='highschool_admin', role=uuid.uuid4(), meta={},
        )
        self.tpl_college = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=3,
            role_type='college_admin', role=uuid.uuid4(),
            college_user=self.college, title='Vice President',
        )
        self.sig_first = MOUSignature.objects.create(
            highschool=self.hs, signator=self.first,
            signator_template=self.tpl_first, status='',
            meta={'role': 'Principal'},
        )
        self.sig_later = MOUSignature.objects.create(
            highschool=self.hs, signator=self.later,
            signator_template=self.tpl_later, status='',
            meta={'role': 'Primary Contact'},
        )
        self.sig_college = MOUSignature.objects.create(
            highschool=self.hs, signator=self.college,
            signator_template=self.tpl_college, status='',
            meta={'role': 'Vice President'},
        )

    @patch(MAIL_PATH)
    def test_first_signer_gets_link_later_gets_heads_up_without_url(self, mock_send):
        _write_cfg(HEADS_UP_ON)
        self.sig_first.send_notification()
        self.assertEqual(mock_send.call_count, 3)
        first_body = mock_send.call_args_list[0][0][1]
        self.assertIn('SIGN Fay', first_body)
        self.assertIn('/mou/', first_body)

        heads_bodies = [c[0][1] for c in mock_send.call_args_list[1:]]
        self.assertTrue(any('HEADS Lee' in b for b in heads_bodies))
        self.assertTrue(any('HEADS Val' in b for b in heads_bodies))
        for body in heads_bodies:
            self.assertNotIn('/mou/', body)
            self.assertIn('2026-27', body)

        self.sig_later.refresh_from_db()
        self.sig_college.refresh_from_db()
        self.sig_first.refresh_from_db()
        self.assertEqual(self.sig_first.status, 'pending')
        self.assertTrue(self.sig_first.meta.get('notified_on'))
        self.assertEqual(self.sig_later.status, '')
        self.assertTrue(self.sig_later.meta.get('heads_up_sent'))
        self.assertTrue(self.sig_college.meta.get('heads_up_sent'))

    @patch(MAIL_PATH)
    def test_college_later_signer_skipped_when_include_college_is_no(self, mock_send):
        cfg = dict(HEADS_UP_ON)
        cfg['heads_up_include_college'] = 'No'
        _write_cfg(cfg)
        self.sig_first.send_notification()
        self.assertEqual(mock_send.call_count, 2)
        bodies = [c[0][1] for c in mock_send.call_args_list]
        self.assertTrue(any('HEADS Lee' in b for b in bodies))
        self.assertFalse(any('HEADS Val' in b for b in bodies))
        self.sig_college.refresh_from_db()
        self.assertFalse((self.sig_college.meta or {}).get('heads_up_sent'))

    @patch(MAIL_PATH)
    def test_reminder_does_not_send_another_heads_up(self, mock_send):
        _write_cfg(HEADS_UP_ON)
        self.sig_first.send_notification()
        self.assertEqual(mock_send.call_count, 3)
        self.sig_first.send_notification()
        self.assertEqual(mock_send.call_count, 4)
        self.assertEqual(mock_send.call_args[0][0], 'Reminder')

    @patch(MAIL_PATH)
    def test_feature_off_sends_only_please_sign(self, mock_send):
        cfg = dict(HEADS_UP_ON)
        cfg['heads_up_email'] = 'No'
        _write_cfg(cfg)
        self.sig_first.send_notification()
        self.assertEqual(mock_send.call_count, 1)
        self.sig_later.refresh_from_db()
        self.assertFalse((self.sig_later.meta or {}).get('heads_up_sent'))
