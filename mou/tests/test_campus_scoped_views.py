"""The remaining CE views honour campus scoping and state changes are POST
+ CSRF (package-mou#2, review P-1 follow-up).

``do_bulk_action`` and the API viewsets were scoped in 29156c7; the MOU detail
page, the index year list, preview and the Duplicate/Delete actions still
looked a record up by bare id, so a CE on campus A could open, duplicate or
delete campus B's MOU. ``mou?action=delete_signator`` also deleted on GET from
a ``csrf_exempt`` view, and copy/send signing link changed state on GET.
"""
from unittest import mock

from django.http import Http404
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, override_settings

from .. import compat, views
from ..models import MOU, MOUSignator
from .test_ce_only_endpoints import _Base, _mou, _sfx


def _json(payload=None):
    return views.JsonResponse(payload or {'rendered': True})


class _ScopedBase(_Base):
    def setUp(self):
        if not compat.HAS_CAMPUS:
            self.skipTest('cis.highschool_scope unavailable')
        super().setUp()
        from django.conf import settings
        from cis.campus_context import campus_context
        from cis.models.course import Campus
        from cis.models.term import AcademicYear

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

    def _request(self, method='get', **params):
        request = getattr(RequestFactory(), method)('/', params)
        request.user = self.ce
        request._dont_enforce_csrf_checks = True
        return request


class CampusScopedViewTests(_ScopedBase):
    @override_settings(MULTI_CAMPUS=True)
    def test_detail_of_other_campus_is_404(self):
        with self.campus_context(self.a), mock.patch.object(
                views, 'render', return_value=_json()):
            with self.assertRaises(Http404):
                views.mou(self._request(), self.theirs[0].id)
            self.assertEqual(
                views.mou(self._request(), self.mine[0].id).status_code, 200)

    @override_settings(MULTI_CAMPUS=True)
    def test_detail_post_to_other_campus_is_404_and_changes_nothing(self):
        title = self.theirs[0].title
        with self.campus_context(self.a):
            with self.assertRaises(Http404):
                views.mou(self._request('post', action='edit_mou',
                                        title='hijacked'), self.theirs[0].id)
        self.theirs[0].refresh_from_db()
        self.assertEqual(self.theirs[0].title, title)

    @override_settings(MULTI_CAMPUS=True)
    def test_preview_of_other_campus_is_404(self):
        with self.campus_context(self.a), mock.patch.object(
                views, 'render', return_value=_json()), \
                mock.patch.object(MOU, 'preview', create=True, return_value=''):
            with self.assertRaises(Http404):
                views.mou_preview(self._request(), self.theirs[0].id)

    @override_settings(MULTI_CAMPUS=True)
    def test_index_lists_only_this_campus_years(self):
        with self.campus_context(self.a), mock.patch.object(
                views, 'render', return_value=_json()) as render:
            views.mous(self._request())
        years = {y.id for y in render.call_args[0][2]['academic_years']}
        self.assertIn(self.mine[0].academic_year_id, years)
        self.assertNotIn(self.theirs[0].academic_year_id, years)

    @override_settings(MULTI_CAMPUS=True)
    def test_duplicate_other_campus_is_404(self):
        before = MOU.objects.count()
        with self.campus_context(self.a):
            with self.assertRaises(Http404):
                views.duplicate_mou(self._request(
                    'post', **{'ids[]': [str(self.theirs[0].id)]}))
        self.assertEqual(MOU.objects.count(), before)

    @override_settings(MULTI_CAMPUS=True)
    def test_duplicate_own_campus_works(self):
        before = MOU.objects.count()
        with self.campus_context(self.a):
            response = views.duplicate_mou(self._request(
                'post', **{'ids[]': [str(self.mine[0].id)]}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MOU.objects.count(), before + 1)

    @override_settings(MULTI_CAMPUS=True)
    def test_delete_other_campus_is_404(self):
        with self.campus_context(self.a):
            with self.assertRaises(Http404):
                views.delete_mou(self._request(
                    'post', **{'ids[]': [str(self.theirs[0].id)]}))
        self.assertTrue(MOU.objects.filter(pk=self.theirs[0].pk).exists())

    @override_settings(MULTI_CAMPUS=True)
    def test_delete_own_campus_works(self):
        with self.campus_context(self.a):
            views.delete_mou(self._request(
                'post', **{'ids[]': [str(self.mine[0].id)]}))
        self.assertFalse(MOU.objects.filter(pk=self.mine[0].pk).exists())

    @override_settings(MULTI_CAMPUS=True)
    def test_signator_of_another_mou_is_404(self):
        """Even inside one campus a signator id must belong to this MOU."""
        other_mou, other_tpl, _ = _mou(self.ce, self.mine[0].academic_year)
        with self.campus_context(self.a), mock.patch.object(
                views, 'render', return_value=_json()):
            with self.assertRaises(Http404):
                views.mou(self._request('post', action='delete_signator',
                                        signator_id=str(other_tpl.id)),
                          self.mine[0].id)
        self.assertTrue(MOUSignator.objects.filter(pk=other_tpl.pk).exists())


class SingleCampusUnchangedTests(_Base):
    def test_detail_and_actions_find_any_mou(self):
        request = RequestFactory().get('/')
        request.user = self.ce
        # MOU.preview does not exist (the view is unrouted); stub it so the
        # lookup is what is under test.
        with mock.patch.object(views, 'render', return_value=_json()), \
                mock.patch.object(MOU, 'preview', create=True, return_value=''):
            self.assertEqual(views.mou(request, self.mou.id).status_code, 200)
            self.assertEqual(
                views.mou_preview(request, self.mou.id).status_code, 200)
            self.assertEqual(views.mous(request).status_code, 200)


class StateChangesArePostWithCsrfTests(_Base):
    def _enforced(self, view, method='post', **params):
        request = getattr(RequestFactory(), method)('/', params)
        request.user = self.ce
        return CsrfViewMiddleware(lambda r: None).process_view(
            request, view, (), {})

    def test_detail_view_is_not_csrf_exempt(self):
        self.assertFalse(getattr(views.mou, 'csrf_exempt', False))
        self.assertEqual(
            self._enforced(views.mou, action='delete_signator').status_code, 403)

    def test_bulk_endpoint_enforces_csrf(self):
        self.assertEqual(
            self._enforced(views.do_bulk_action, action='delete_signator'
                           ).status_code, 403)

    def test_get_of_delete_signator_is_405_and_deletes_nothing(self):
        request = RequestFactory().get(
            '/', {'action': 'delete_signator', 'signator_id': str(self.tpl.id)})
        request.user = self.ce
        self.assertEqual(views.mou(request, self.mou.id).status_code, 405)
        self.assertTrue(MOUSignator.objects.filter(pk=self.tpl.pk).exists())

    def test_post_deletes_the_signator(self):
        request = RequestFactory().post(
            '/', {'action': 'delete_signator', 'signator_id': str(self.tpl.id)})
        request.user = self.ce
        request._dont_enforce_csrf_checks = True
        response = views.mou(request, self.mou.id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MOUSignator.objects.filter(pk=self.tpl.pk).exists())

    def test_signing_link_actions_refuse_get(self):
        for action in ('get_signature_link', 'send_signature_link'):
            with self.subTest(action=action):
                response = self._bulk(self.ce, action=action,
                                      **{'ids[]': [str(self.sig.id)]})
                self.assertEqual(response.status_code, 405)
        self.sig.refresh_from_db()
        self.assertEqual(self.sig.status, 'next')
