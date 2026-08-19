import importlib.util

from django.contrib.auth.models import Group
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)
from cis.models.settings import Setting
from cis.models.term import AcademicYear


def _models():
    try:
        from mou.mou.models import MOU, MOUSignator, MOUSignature
    except ImportError:
        from mou.models import MOU, MOUSignator, MOUSignature
    return MOU, MOUSignator, MOUSignature


def _write_cfg(value):
    for key in ('mou.mou.settings.email_settings', 'mou.settings.email_settings'):
        Setting.objects.update_or_create(key=key, defaults={'value': value})


_PKG = 'mou.mou' if importlib.util.find_spec('mou.mou') else 'mou'


@override_settings(
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    ROOT_URLCONF=f'{_PKG}.tests.urls_hs',
)
class SignedMousHsAdminTests(TestCase):
    def setUp(self):
        MOU, MOUSignator, MOUSignature = _models()
        self.client = Client()
        self.hs_group, _ = Group.objects.get_or_create(name='highschool_admin')
        self.user = CustomUser.objects.create_user(
            username='hs@example.com', email='hs@example.com', password='x',
        )
        self.user.groups.add(self.hs_group)
        self.hs = HighSchool.objects.create(name='North HS', code='N1', status='Active')
        self.admin = HSAdministrator.objects.create(user=self.user)
        pos = HSPosition.objects.create(name='Principal')
        HSAdministratorPosition.objects.create(
            hsadmin=self.admin, highschool=self.hs, position=pos, status='Active',
        )

        creator = CustomUser.objects.create(username='ce', email='ce@example.com')
        ay = AcademicYear.objects.create(name='2026-27')
        self.mou = MOU.objects.create(
            title='District MOU', cron='0 7 * * *', academic_year=ay, created_by=creator,
        )
        tpl = MOUSignator.objects.create(
            mou=self.mou, created_by=creator, weight=1,
            role_type='highschool_admin', role=pos.id,
        )
        self.signature = MOUSignature.objects.create(
            highschool=self.hs, signator=self.user, signator_template=tpl,
            status='signed',
            meta={'signed_on': timezone.now().strftime('%m/%d/%Y %I:%M %p')},
        )

        from django.contrib.auth.signals import user_logged_in
        from django_login_history.models import post_login
        user_logged_in.disconnect(post_login)
        try:
            self.client.force_login(
                self.user,
                backend='django.contrib.auth.backends.ModelBackend',
            )
        finally:
            user_logged_in.connect(post_login)

    def test_hidden_when_setting_off(self):
        _write_cfg({'hs_admin_can_view_signed_mous': 'No'})
        resp = self.client.get(reverse('mou_hs:signed_mous'))
        self.assertEqual(resp.status_code, 404)

    def test_lists_signed_mou_for_admins_school(self):
        _write_cfg({
            'hs_admin_can_view_signed_mous': 'Yes',
            'retention_years': 6,
        })
        resp = self.client.get(reverse('mou_hs:signed_mous'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'District MOU')
        self.assertContains(resp, 'North HS')
        self.assertContains(resp, 'Download PDF')
