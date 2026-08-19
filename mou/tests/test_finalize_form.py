import datetime
import uuid

from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory

from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear

try:
    from mou.mou.forms import MOUFinalizeForm
    from mou.mou.models import MOU
except ImportError:
    from mou.forms import MOUFinalizeForm
    from mou.models import MOU


class MOUFinalizeFormManagerTest(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.creator = CustomUser.objects.create(
            username='creator', email='creator@example.com'
        )
        self.ce_group, _ = Group.objects.get_or_create(name='ce')
        self.manager_user = CustomUser.objects.create(
            username='mgr', email='mgr@example.com',
            first_name='Mary', last_name='Manager',
        )
        self.manager_user.groups.add(self.ce_group)

        self.non_ce_user = CustomUser.objects.create(
            username='other', email='other@example.com',
        )

        self.ay = AcademicYear.objects.create(
            name='2025-2026',
        )
        self.mou = MOU.objects.create(
            title='Test MOU',
            cron='*/5 * * * *',
            academic_year=self.ay,
            created_by=self.creator,
        )

    def test_manager_queryset_only_includes_ce_users(self):
        form = MOUFinalizeForm(None, self.mou)
        manager_ids = list(form.fields['manager'].queryset.values_list('id', flat=True))
        self.assertIn(self.manager_user.id, manager_ids)
        self.assertNotIn(self.non_ce_user.id, manager_ids)

    def test_save_persists_manager(self):
        form = MOUFinalizeForm(
            None,
            self.mou,
            data={
                'action': 'finalize',
                'title': self.mou.title,
                'academic_year': self.ay.id,
                'status': 'draft',
                'send_after': '01/01/2026',
                'send_until': '12/31/2026',
                'cron': '*/5 * * * *',
                'manager': self.manager_user.id,
            },
        )
        self.assertTrue(form.is_valid(), msg=form.errors)
        form.save(None, self.mou)
        self.mou.refresh_from_db()
        self.assertEqual(self.mou.manager_id, self.manager_user.id)

    def test_save_allows_blank_manager(self):
        form = MOUFinalizeForm(
            None,
            self.mou,
            data={
                'action': 'finalize',
                'title': self.mou.title,
                'academic_year': self.ay.id,
                'status': 'draft',
                'send_after': '01/01/2026',
                'send_until': '12/31/2026',
                'cron': '*/5 * * * *',
                'manager': '',
            },
        )
        self.assertTrue(form.is_valid(), msg=form.errors)
        form.save(None, self.mou)
        self.mou.refresh_from_db()
        self.assertIsNone(self.mou.manager)
