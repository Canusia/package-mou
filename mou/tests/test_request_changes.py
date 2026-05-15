import datetime
import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition

from mou.mou.models import MOU, MOUSignator, MOUSignature, MOUNote


@override_settings(DEBUG=False)
class SignMouRequestChangesViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.creator = CustomUser.objects.create(
            username='creator', email='creator@example.com'
        )
        self.ce_group, _ = Group.objects.get_or_create(name='ce')
        self.manager_user = CustomUser.objects.create(
            username='mgr', email='mgr@example.com',
        )
        self.manager_user.groups.add(self.ce_group)

        self.signator_user = CustomUser.objects.create(
            username='principal', email='principal@example.com',
            first_name='Pat', last_name='Principal',
        )
        self.hs = HighSchool.objects.create(
            name='Test HS', code='000001', status='active',
        )
        self.position = HSPosition.objects.create(name='Principal')

        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.mou = MOU.objects.create(
            title='Test MOU',
            cron='*/5 * * * *',
            academic_year=self.ay,
            created_by=self.creator,
            manager=self.manager_user,
            mou_text='',
        )
        self.signator_tpl = MOUSignator.objects.create(
            mou=self.mou,
            created_by=self.creator,
            weight=1,
            role_type='highschool_admin',
            role=self.position.id,
            meta={},
        )
        self.signature = MOUSignature.objects.create(
            highschool=self.hs,
            signator=self.signator_user,
            signator_template=self.signator_tpl,
            status='pending',
            meta={},
        )

    def _url(self):
        return reverse('mou:sign', kwargs={'signature_id': self.signature.id})

    @patch('mou.mou.models.send_html_mail')
    def test_request_changes_sets_status_and_stores_comment(self, mock_send):
        resp = self.client.post(self._url(), {
            'action': 'request_changes',
            'change_request_comment': 'Section 3 is too restrictive.',
        })
        self.assertEqual(resp.status_code, 302)

        self.signature.refresh_from_db()
        self.assertEqual(self.signature.status, 'changes_requested')
        self.assertEqual(
            self.signature.meta.get('change_request_comment'),
            'Section 3 is too restrictive.',
        )
        self.assertIn('change_requested_on', self.signature.meta)

    @patch('mou.mou.models.send_html_mail')
    def test_request_changes_creates_mou_note(self, mock_send):
        self.client.post(self._url(), {
            'action': 'request_changes',
            'change_request_comment': 'Please revise section 3.',
        })
        notes = MOUNote.objects.filter(meo=self.mou, meta__type='change_request')
        self.assertEqual(notes.count(), 1)
        self.assertIn('Please revise section 3.', notes.first().note)

    @patch('mou.mou.models.send_html_mail')
    def test_request_changes_emails_manager(self, mock_send):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(
            key='mou.mou.settings.email_settings',
            defaults={'value': {
                'change_request_email_subject': 'Change Requested',
                'change_request_email_message': '{{signator_firstname}} requested: {{comment}}',
                'notify_address': 'fallback@example.com',
            }},
        )
        self.client.post(self._url(), {
            'action': 'request_changes',
            'change_request_comment': 'Revise pricing.',
        })
        self.assertEqual(mock_send.call_count, 1)
        args, _kwargs = mock_send.call_args
        recipients = args[4]
        self.assertEqual(recipients, ['mgr@example.com'])

    @patch('mou.mou.models.send_html_mail')
    def test_request_changes_requires_comment(self, mock_send):
        resp = self.client.post(self._url(), {
            'action': 'request_changes',
            'change_request_comment': '',
        })
        self.signature.refresh_from_db()
        self.assertEqual(self.signature.status, 'pending')
        mock_send.assert_not_called()

    @patch('mou.mou.models.send_html_mail')
    def test_falls_back_to_notify_address_when_no_manager(self, mock_send):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(
            key='mou.mou.settings.email_settings',
            defaults={'value': {
                'change_request_email_subject': 'X',
                'change_request_email_message': 'body',
                'notify_address': 'ops@example.com,backup@example.com',
            }},
        )
        self.mou.manager = None
        self.mou.save()

        self.client.post(self._url(), {
            'action': 'request_changes',
            'change_request_comment': 'Comment.',
        })
        recipients = mock_send.call_args[0][4]
        self.assertEqual(recipients, ['ops@example.com', 'backup@example.com'])
