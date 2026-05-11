import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse


def _models():
    try:
        from mou.mou.models import MOU, MOUSignator, MOUSignature
    except ImportError:
        from mou.models import MOU, MOUSignator, MOUSignature
    return MOU, MOUSignator, MOUSignature


class MOUDuplicateModelTests(TestCase):
    def setUp(self):
        from cis.models.term import AcademicYear

        MOU, MOUSignator, MOUSignature = _models()
        User = get_user_model()
        self.user = User.objects.create_user(
            username='ce@example.com', email='ce@example.com',
            password='x', is_staff=True,
        )
        self.other = User.objects.create_user(
            username='ce2@example.com', email='ce2@example.com',
            password='x', is_staff=True,
        )
        self.ay = AcademicYear.objects.create(name='2025-26')
        self.mou = MOU.objects.create(
            title='Original MOU', cron='*/5 * * * *', group_by='highschool',
            academic_year=self.ay, created_by=self.user,
            description='desc', mou_text='Hello {{highschool_name}}',
            status='ready', meta={'k': 'v'},
        )
        self.sig1 = MOUSignator.objects.create(
            mou=self.mou, weight=1, role_type='highschool_admin',
            role=uuid.uuid4(), created_by=self.user, meta={'complete_extra_form': '1'},
        )
        self.sig2 = MOUSignator.objects.create(
            mou=self.mou, weight=2, role_type='district_admin',
            role=uuid.uuid4(), created_by=self.user,
        )

    def test_duplicate_copies_mou_fields_and_resets_status(self):
        MOU, _, _ = _models()
        dup = self.mou.duplicate(self.other)

        self.assertNotEqual(dup.pk, self.mou.pk)
        self.assertEqual(dup.title, 'Copy of Original MOU')
        self.assertEqual(dup.cron, '*/5 * * * *')
        self.assertEqual(dup.group_by, 'highschool')
        self.assertEqual(dup.academic_year_id, self.ay.id)
        self.assertEqual(dup.description, 'desc')
        self.assertEqual(dup.mou_text, 'Hello {{highschool_name}}')
        self.assertEqual(dup.status, 'draft')
        self.assertEqual(dup.meta, {'k': 'v'})
        self.assertEqual(dup.created_by_id, self.other.id)
        self.assertIsNone(dup.send_on_after)
        self.assertIsNone(dup.send_until)

    def test_duplicate_title_truncated_to_100_chars(self):
        MOU, _, _ = _models()
        self.mou.title = 'X' * 100
        self.mou.save()
        dup = self.mou.duplicate(self.user)
        self.assertEqual(len(dup.title), 100)
        self.assertTrue(dup.title.startswith('Copy of '))

    def test_duplicate_clones_signators_not_signatures(self):
        MOU, MOUSignator, MOUSignature = _models()
        from cis.models.highschool import HighSchool
        hs = HighSchool.objects.create(name='HS', code='HS1', status='Active')
        MOUSignature.objects.create(
            signator_template=self.sig1, highschool=hs,
            signator=self.user, status='pending',
        )

        dup = self.mou.duplicate(self.user)

        dup_sigs = MOUSignator.objects.filter(mou=dup).order_by('weight')
        self.assertEqual(dup_sigs.count(), 2)
        self.assertEqual([s.weight for s in dup_sigs], [1, 2])
        self.assertEqual(dup_sigs[0].role_type, 'highschool_admin')
        self.assertEqual(dup_sigs[0].role, self.sig1.role)
        self.assertEqual(dup_sigs[0].meta, {'complete_extra_form': '1'})
        self.assertEqual(dup_sigs[0].created_by_id, self.user.id)
        self.assertEqual(dup_sigs[1].role_type, 'district_admin')
        self.assertFalse(
            MOUSignature.objects.filter(signator_template__mou=dup).exists()
        )
        self.assertEqual(MOUSignator.objects.filter(mou=self.mou).count(), 2)


class MOUBulkActionTests(TestCase):
    def setUp(self):
        from cis.models.term import AcademicYear

        MOU, MOUSignator, MOUSignature = _models()
        User = get_user_model()
        self.user = User.objects.create_user(
            username='ce@example.com', email='ce@example.com',
            password='x', is_staff=True,
        )
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user.groups.add(ce_group)

        from django.contrib.auth.signals import user_logged_in
        from django_login_history.models import post_login
        user_logged_in.disconnect(post_login)
        try:
            self.client.force_login(self.user)
        finally:
            user_logged_in.connect(post_login)

        self.ay = AcademicYear.objects.create(name='2025-26')
        self.mou = MOU.objects.create(
            title='Src MOU', cron='*/5 * * * *',
            academic_year=self.ay, created_by=self.user, status='draft',
        )
        MOUSignator.objects.create(
            mou=self.mou, weight=1, role_type='highschool_admin',
            role=uuid.uuid4(), created_by=self.user,
        )
        self.url = reverse('mou_ce:bulk_action')

    def test_duplicate_mou_action_creates_copy_and_redirects(self):
        MOU, MOUSignator, _ = _models()
        resp = self.client.get(self.url, {'action': 'duplicate_mou', 'mou_id': str(self.mou.id)})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(body['action'], 'redirect_to')

        dup = MOU.objects.exclude(pk=self.mou.pk).get(academic_year=self.ay)
        self.assertEqual(dup.title, 'Copy of Src MOU')
        self.assertEqual(dup.status, 'draft')
        self.assertIn(str(dup.id), body['redirect_to'])
        self.assertEqual(MOUSignator.objects.filter(mou=dup).count(), 1)

    def test_duplicate_mou_bad_id_returns_404(self):
        resp = self.client.get(self.url, {'action': 'duplicate_mou', 'mou_id': str(uuid.uuid4())})
        self.assertEqual(resp.status_code, 404)

    def test_delete_mou_action_deletes_editable_mou(self):
        MOU, _, _ = _models()
        resp = self.client.get(self.url, {'action': 'delete_mou', 'mou_id': str(self.mou.id)})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        self.assertIn('/ce/highschools/mous', body['redirect_to'])
        self.assertFalse(MOU.objects.filter(pk=self.mou.pk).exists())

    def test_delete_mou_action_refuses_ready_mou(self):
        MOU, _, _ = _models()
        self.mou.status = 'ready'
        self.mou.save()
        resp = self.client.get(self.url, {'action': 'delete_mou', 'mou_id': str(self.mou.id)})
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(MOU.objects.filter(pk=self.mou.pk).exists())
