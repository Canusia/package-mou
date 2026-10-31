"""The MOU CE endpoints are CE-only (pre-existing P-1, review 2026-10).

Before: ``do_bulk_action`` had no role check and the three API viewsets used
DRF's default IsAuthenticated with every row, so any logged-in user (a
student, another school's HS admin) could list every signature id -- the
bearer token of the public signing page -- copy signing links (which also
flips rows to pending) or delete signatures.

No portal other than CE calls these endpoints (checked: package templates and
JS, ewu highschool_admin / myce_tenant_configs / templates, and the other
tenants under /repos/*/webapp), so non-CE users simply get 403. In
multi-campus mode CE sees and acts on the current campus's MOUs only.
"""
import uuid
from unittest import mock

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.term import AcademicYear

from .. import compat, views
from ..models import MOU, MOUSignator, MOUSignature


def _sfx():
    return uuid.uuid4().hex[:8]


def _user(role=None):
    user = CustomUser.objects.create_user(
        username=f'{role or "x"}-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
    if role:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def _mou(ce, ay):
    mou = MOU.objects.create(
        title=f'M {_sfx()}', cron='*/5 * * * *', academic_year=ay,
        created_by=ce, mou_text='')
    tpl = MOUSignator.objects.create(
        mou=mou, weight=1, role_type='highschool_admin', role=uuid.uuid4(),
        created_by=ce, meta={})
    hs = HighSchool.objects.create(name=f'HS {_sfx()}', code=_sfx(), status='Active')
    sig = MOUSignature.objects.create(
        highschool=hs, signator=_user(), signator_template=tpl, status='next',
        meta={})
    return mou, tpl, sig


class _Base(TestCase):
    def setUp(self):
        self.ce = _user('ce')
        self.hs_admin = _user('highschool_admin')
        self.student = _user('student')
        self.mou, self.tpl, self.sig = _mou(
            self.ce, AcademicYear.objects.create(name=f'AY-{_sfx()}'))

    def _api(self, viewset, user, **params):
        request = APIRequestFactory().get('/', dict(params, format='json'))
        force_authenticate(request, user=user)
        return viewset.as_view({'get': 'list'})(request)

    def _ids(self, response):
        data = response.data
        rows = data.get('results', data) if isinstance(data, dict) else data
        return {str(r['id']) for r in rows}

    def _bulk(self, user, method='get', **params):
        rf = RequestFactory()
        request = getattr(rf, method)('/', params)
        request.user = user
        request._dont_enforce_csrf_checks = True
        with mock.patch.object(views, 'render',
                               return_value=views.JsonResponse({'rendered': True})):
            return views.do_bulk_action(request)


class ApiRoleTests(_Base):
    VIEWSETS = ('MOUViewSet', 'MOUSignatorViewSet', 'MOUSignatureViewSet')

    def test_ce_lists_rows(self):
        self.assertIn(str(self.mou.id), self._ids(self._api(views.MOUViewSet, self.ce)))
        self.assertIn(str(self.tpl.id),
                      self._ids(self._api(views.MOUSignatorViewSet, self.ce)))
        self.assertIn(str(self.sig.id),
                      self._ids(self._api(views.MOUSignatureViewSet, self.ce)))

    def test_hs_admin_and_student_are_forbidden(self):
        for name in self.VIEWSETS:
            for user in (self.hs_admin, self.student):
                with self.subTest(viewset=name, user=user.username):
                    response = self._api(getattr(views, name), user)
                    self.assertEqual(response.status_code, 403)


class BulkActionRoleTests(_Base):
    def test_hs_admin_cannot_copy_a_signing_link(self):
        response = self._bulk(self.hs_admin, action='get_signature_link',
                              **{'ids[]': [str(self.sig.id)]})
        self.assertEqual(response.status_code, 403)
        self.sig.refresh_from_db()
        self.assertEqual(self.sig.status, 'next')

    def test_student_cannot_delete_signatures(self):
        response = self._bulk(self.student, method='post',
                              action='delete_signature', ids=[str(self.sig.id)])
        self.assertEqual(response.status_code, 403)
        self.assertTrue(MOUSignature.objects.filter(pk=self.sig.pk).exists())

    def test_every_action_is_forbidden_to_non_ce(self):
        for action in ('change_signature_status', 'delete_signator',
                       'add_signator', 'edit_mou_signator', 'delete_signature',
                       'add_highschools', 'get_signature_link',
                       'send_signature_link', 'bogus'):
            with self.subTest(action=action):
                self.assertEqual(
                    self._bulk(self.hs_admin, action=action).status_code, 403)

    def test_ce_can_copy_a_signing_link(self):
        response = self._bulk(self.ce, action='get_signature_link',
                              **{'ids[]': [str(self.sig.id)]})
        self.assertEqual(response.status_code, 200)
        self.sig.refresh_from_db()
        self.assertEqual(self.sig.status, 'pending')


class MultiCampusScopeTests(_Base):
    """CE on campus A sees and acts on campus A's MOUs only."""

    def setUp(self):
        if not compat.HAS_CAMPUS:
            self.skipTest('cis.highschool_scope unavailable')
        super().setUp()
        from django.conf import settings
        from cis.campus_context import campus_context
        from cis.models.course import Campus

        def campus():
            return Campus.objects.create(
                name=f'C-{_sfx()}',
                code=f'{settings.CAMPUS_CODE_PREFIX}_{_sfx()[:6]}')

        self.a, self.b = campus(), campus()
        self.campus_context = campus_context
        with override_settings(MULTI_CAMPUS=True):
            with campus_context(self.a):
                ay_a = AcademicYear.objects.create(name=f'A-{_sfx()}', campus=self.a)
            with campus_context(self.b):
                ay_b = AcademicYear.objects.create(name=f'B-{_sfx()}', campus=self.b)
        self.mine = _mou(self.ce, ay_a)
        self.theirs = _mou(self.ce, ay_b)

    @override_settings(MULTI_CAMPUS=True)
    def test_api_rows_are_campus_scoped(self):
        with self.campus_context(self.a):
            mous = self._ids(self._api(views.MOUViewSet, self.ce))
            tpls = self._ids(self._api(views.MOUSignatorViewSet, self.ce))
            sigs = self._ids(self._api(views.MOUSignatureViewSet, self.ce))
        self.assertIn(str(self.mine[0].id), mous)
        self.assertNotIn(str(self.theirs[0].id), mous)
        self.assertIn(str(self.mine[1].id), tpls)
        self.assertNotIn(str(self.theirs[1].id), tpls)
        self.assertIn(str(self.mine[2].id), sigs)
        self.assertNotIn(str(self.theirs[2].id), sigs)

    @override_settings(MULTI_CAMPUS=True)
    def test_no_campus_lists_nothing(self):
        self.assertEqual(self._ids(self._api(views.MOUSignatureViewSet, self.ce)), set())

    @override_settings(MULTI_CAMPUS=True)
    def test_bulk_action_on_other_campus_row_is_refused(self):
        sig = self.theirs[2]
        with self.campus_context(self.a):
            response = self._bulk(self.ce, action='get_signature_link',
                                  **{'ids[]': [str(sig.id)]})
        self.assertEqual(response.status_code, 404)
        sig.refresh_from_db()
        self.assertEqual(sig.status, 'next')

    @override_settings(MULTI_CAMPUS=True)
    def test_bulk_action_on_own_campus_row_works(self):
        sig = self.mine[2]
        with self.campus_context(self.a):
            response = self._bulk(self.ce, action='get_signature_link',
                                  **{'ids[]': [str(sig.id)]})
        self.assertEqual(response.status_code, 200)
