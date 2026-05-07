import json
import uuid

from django.test import SimpleTestCase

try:
    from mou.mou.services.signatures_table import build_config
except ImportError:
    from mou.services.signatures_table import build_config


class BuildConfigByAcademicYearTests(SimpleTestCase):
    def test_returns_table_id_and_column_headers(self):
        cfg = build_config(
            variant='by_academic_year',
            api_url='/ce/highschools/mous/api/mou_signatures?format=datatables&academic_year_id=42',
        )

        self.assertEqual(cfg['table_id'], 'tbl_mou_signatures_by_year')
        # 9 visible columns: select, MOU title, academic year, highschool,
        # signator, role, status, last updated, actions.
        self.assertEqual(len(cfg['column_headers']), 9)
        for header in cfg['column_headers']:
            self.assertTrue(header.startswith('<th'))

    def test_opts_json_carries_api_url_and_action_scope(self):
        cfg = build_config(
            variant='by_academic_year',
            api_url='/x?academic_year_id=42',
        )

        opts = json.loads(cfg['opts_json'])
        self.assertEqual(opts['apiUrl'], '/x?academic_year_id=42')
        self.assertEqual(opts['actionScope'], 'by_academic_year')
        self.assertIn('select', opts['columns'])
        self.assertIn('signator', opts['columns'])
        self.assertIn('status', opts['columns'])

    def test_unknown_variant_raises(self):
        with self.assertRaises(KeyError):
            build_config(variant='nope', api_url='/x')


from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class MOUSignatureAPIFilterTests(TestCase):
    def setUp(self):
        from cis.models.term import AcademicYear
        from cis.models.highschool import HighSchool
        try:
            from mou.mou.models import MOU, MOUSignator, MOUSignature
        except ImportError:
            from mou.models import MOU, MOUSignator, MOUSignature

        User = get_user_model()
        self.user = User.objects.create_user(
            username='ce@example.com', email='ce@example.com',
            password='x', is_staff=True,
        )
        from django.contrib.auth.signals import user_logged_in
        from django_login_history.models import post_login
        user_logged_in.disconnect(post_login)
        try:
            self.client.force_login(self.user)
        finally:
            user_logged_in.connect(post_login)


        self.ay_a = AcademicYear.objects.create(name='2024-25')
        self.ay_b = AcademicYear.objects.create(name='2025-26')

        self.hs = HighSchool.objects.create(name='HS-A', code='AA1', status='Active')

        self.mou_a = MOU.objects.create(
            title='AY-A MOU', cron='* * * * *',
            academic_year=self.ay_a, created_by=self.user,
        )
        self.mou_b = MOU.objects.create(
            title='AY-B MOU', cron='* * * * *',
            academic_year=self.ay_b, created_by=self.user,
        )

        signator_a = MOUSignator.objects.create(
            mou=self.mou_a, weight=1, role_type='highschool_admin', role=uuid.uuid4(),
            created_by=self.user
        )
        signator_b = MOUSignator.objects.create(
            mou=self.mou_b, weight=1, role_type='highschool_admin', role=uuid.uuid4(),
            created_by=self.user
        )

        MOUSignature.objects.create(
            signator_template=signator_a, highschool=self.hs,
            signator=self.user, status='pending',
        )
        MOUSignature.objects.create(
            signator_template=signator_b, highschool=self.hs,
            signator=self.user, status='pending',
        )

    def test_filter_by_academic_year_id(self):
        url = '/ce/highschools/mous/api/mou_signatures/?format=datatables&academic_year_id=' + str(self.ay_a.id)
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['recordsFiltered'], 1)
        self.assertEqual(
            body['data'][0]['signator_template']['mou']['title'],
            'AY-A MOU',
        )

    def test_no_academic_year_id_returns_all(self):
        url = '/ce/highschools/mous/api/mou_signatures/?format=datatables'
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['recordsFiltered'], 2)
