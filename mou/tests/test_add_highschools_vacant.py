from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition
from cis.models.settings import Setting
from cis.models.term import AcademicYear


def _models():
    try:
        from mou.mou.models import MOU, MOUSignator, MOUSignature
        from mou.mou.forms import AddHighSchoolForm
    except ImportError:
        from mou.models import MOU, MOUSignator, MOUSignature
        from mou.forms import AddHighSchoolForm
    return MOU, MOUSignator, MOUSignature, AddHighSchoolForm


class AddHighSchoolsVacantRoleTests(TestCase):
    def setUp(self):
        MOU, MOUSignator, _, _ = _models()
        User = get_user_model()
        self.user = User.objects.create_user(
            username='ce@example.com', email='ce@example.com',
            password='x', is_staff=True,
        )
        self.ay = AcademicYear.objects.create(name='2026-27')
        self.mou = MOU.objects.create(
            title='AY MOU', cron='0 7 * * *', academic_year=self.ay,
            created_by=self.user,
        )
        self.pos = HSPosition.objects.create(name='Principal')
        MOUSignator.objects.create(
            mou=self.mou, weight=1, role_type='highschool_admin',
            role=self.pos.id, created_by=self.user, meta={},
        )
        self.hs = HighSchool.objects.create(name='Empty HS', code='E1', status='Active')

    def _write(self, policy):
        value = {'vacant_role_policy': policy, 'is_active': 'No', 'notify_address': 'ops@example.com'}
        for key in ('mou.mou.settings.email_settings', 'mou.settings.email_settings'):
            Setting.objects.update_or_create(key=key, defaults={'value': value})

    def test_skip_silent_creates_no_signature_and_records_miss(self):
        MOU, _, MOUSignature, AddHighSchoolForm = _models()
        self._write('skip_silent')
        form = AddHighSchoolForm(mou_id=self.mou.id, data={
            'action': 'add_highschools',
            'mou_id': str(self.mou.id),
            'highschools': [str(self.hs.id)],
        })
        self.assertTrue(form.is_valid(), msg=form.errors)
        result = form.save()
        self.assertEqual(len(result['_misses']), 1)
        self.assertEqual(result['_misses'][0]['role'], 'Principal')
        self.assertFalse(MOUSignature.objects.filter(highschool=self.hs).exists())

    def test_hold_school_does_not_create_rows(self):
        _, _, MOUSignature, AddHighSchoolForm = _models()
        self._write('hold_school')
        form = AddHighSchoolForm(mou_id=self.mou.id, data={
            'action': 'add_highschools',
            'mou_id': str(self.mou.id),
            'highschools': [str(self.hs.id)],
        })
        self.assertTrue(form.is_valid(), msg=form.errors)
        result = form.save()
        self.assertTrue(result[self.hs.code].get('held'))
        self.assertFalse(MOUSignature.objects.filter(highschool=self.hs).exists())

    @patch('mailer.send_html_mail')
    def test_skip_and_notify_emails_when_active(self, mock_send):
        # Vacant notify uses notification_recipients, which is No in _write.
        # Flip to Yes so a mail is attempted; DEBUG extra-redirect still applies.
        _, _, _, AddHighSchoolForm = _models()
        value = {
            'vacant_role_policy': 'skip_and_notify',
            'is_active': 'Yes',
            'notify_address': 'ops@example.com',
        }
        for key in ('mou.mou.settings.email_settings', 'mou.settings.email_settings'):
            Setting.objects.update_or_create(key=key, defaults={'value': value})
        form = AddHighSchoolForm(mou_id=self.mou.id, data={
            'action': 'add_highschools',
            'mou_id': str(self.mou.id),
            'highschools': [str(self.hs.id)],
        })
        self.assertTrue(form.is_valid(), msg=form.errors)
        with patch.object(form, '_notify_vacant_roles') as notify:
            result = form.save()
        self.assertEqual(len(result['_misses']), 1)
        notify.assert_called_once()

    @patch('mailer.send_html_mail')
    def test_vacant_role_email_escapes_interpolated_values(self, send):
        """mou.title / highschool.name / role name go straight into an HTML
        email body built with format_html/format_html_join, so they must be
        escaped exactly once. cis/email.html's own {{message}} placeholder
        has no |safe filter and autoescapes whatever it's handed -- a plain
        str body would get escaped a second time there (or, if never escaped
        at all, would render as literal markup / carry unescaped user text).
        This exercises the real get_template('cis/email.html').render(...)
        path so both failure modes are covered: double-escaped entities and
        the body's own structural tags surviving as real markup rather than
        escaped text."""
        _, _, _, AddHighSchoolForm = _models()
        self.mou.title = 'Dual Credit <script>alert(1)</script>'
        self.mou.save(update_fields=['title'])
        self.hs.name = 'Smith & Jones HS'
        self.hs.save(update_fields=['name'])

        value = {
            'vacant_role_policy': 'skip_and_notify',
            'is_active': 'Yes',
            'notify_address': 'ops@example.com',
        }
        for key in ('mou.mou.settings.email_settings', 'mou.settings.email_settings'):
            Setting.objects.update_or_create(key=key, defaults={'value': value})
        form = AddHighSchoolForm(mou_id=self.mou.id, data={
            'action': 'add_highschools',
            'mou_id': str(self.mou.id),
            'highschools': [str(self.hs.id)],
        })
        self.assertTrue(form.is_valid(), msg=form.errors)

        form.save()

        self.assertTrue(send.called)
        html_body = send.call_args.args[2]
        self.assertNotIn('<script>', html_body)
        # Escaped exactly once: '&' -> '&amp;', not double-escaped to
        # '&amp;amp;'.
        self.assertEqual(html_body.count('&amp;'), 1)
        self.assertNotIn('&amp;amp;', html_body)
        # The body's own markup survives as real tags, not escaped text.
        self.assertIn('<p>', html_body)
        self.assertIn('<li>', html_body)
        self.assertNotIn('&lt;p&gt;', html_body)
        self.assertNotIn('&lt;li&gt;', html_body)


class AddHighSchoolsMarksNextUpTests(TestCase):
    def test_filled_role_is_next_up_until_emailed(self):
        from django.contrib.auth.models import Group
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition,
        )
        MOU, MOUSignator, MOUSignature, AddHighSchoolForm = _models()
        Group.objects.get_or_create(name='highschool_admin')
        User = get_user_model()
        ce = User.objects.create_user(
            username='ce2@example.com', email='ce2@example.com',
            password='x', is_staff=True,
        )
        signer = User.objects.create_user(
            username='p@example.com', email='p@example.com', password='x',
        )
        ay = AcademicYear.objects.create(name='2026-27')
        mou = MOU.objects.create(
            title='AY MOU', cron='0 7 * * *', academic_year=ay, created_by=ce,
        )
        pos = HSPosition.objects.create(name='Principal')
        MOUSignator.objects.create(
            mou=mou, weight=1, role_type='highschool_admin',
            role=pos.id, created_by=ce, meta={},
        )
        hs = HighSchool.objects.create(name='Ready HS', code='R1', status='Active')
        admin = HSAdministrator.objects.create(user=signer)
        HSAdministratorPosition.objects.create(
            hsadmin=admin, highschool=hs, position=pos, status='Active',
        )
        form = AddHighSchoolForm(mou_id=mou.id, data={
            'action': 'add_highschools',
            'mou_id': str(mou.id),
            'highschools': [str(hs.id)],
        })
        self.assertTrue(form.is_valid(), msg=form.errors)
        form.save()
        sig = MOUSignature.objects.get(highschool=hs)
        self.assertEqual(sig.status, 'next')
        self.assertFalse((sig.meta or {}).get('notified_on'))
