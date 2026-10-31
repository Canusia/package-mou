"""Security re-review: every child id a CE view takes must belong to the MOU
posted or viewed (and the campus), and malformed ids are 404, not 500."""
import uuid
from unittest import mock

from django.http import Http404
from django.test import RequestFactory, override_settings

from .. import compat, forms, views
from ..models import MOU, MOUSignator, MOUSignature
from .test_campus_scoped_views import _ScopedBase
from .test_ce_only_endpoints import _Base, _mou
from cis.models.term import AcademicYear


def _post_data(sig, **extra):
    data = {'action': 'edit_mou_signator', 'id': str(sig.id), 'weight': 2,
            'role_type': 'college_admin', 'college_title': 'pwned'}
    data.update(extra)
    return data


class DetailEditSignatorMembershipTests(_Base):
    def _post(self, mou, data):
        request = RequestFactory().post('/', data)
        request.user = self.ce
        request._dont_enforce_csrf_checks = True
        with mock.patch.object(views, 'render',
                               return_value=views.JsonResponse({})):
            return views.mou(request, mou.id)

    def test_other_mous_signator_is_404_and_unchanged(self):
        other, other_tpl, _ = _mou(self.ce, self.mou.academic_year)
        weight, title = other_tpl.weight, other_tpl.title
        with self.assertRaises(Http404):
            self._post(self.mou, _post_data(other_tpl))
        other_tpl.refresh_from_db()
        self.assertEqual((other_tpl.weight, other_tpl.title), (weight, title))

    def test_non_uuid_signator_id_is_404(self):
        with self.assertRaises(Http404):
            self._post(self.mou, _post_data(self.tpl, id='not-a-uuid'))

    def test_form_save_is_bound_to_the_mou(self):
        other, other_tpl, _ = _mou(self.ce, self.mou.academic_year)
        form = forms.MOUSignatorForm(record=None, data=_post_data(other_tpl))
        form.cleaned_data = {'id': str(other_tpl.id), 'weight': 2,
                             'role_type': 'college_admin'}
        request = mock.Mock(user=self.ce)
        with self.assertRaises(MOUSignator.DoesNotExist):
            form.save(request, self.mou)


class BulkMembershipTests(_Base):
    def test_signator_ids_must_belong_to_posted_mou(self):
        other, other_tpl, _ = _mou(self.ce, self.mou.academic_year)
        response = self._bulk(self.ce, method='post', action='delete_signator',
                              mou_id=str(self.mou.id), ids=[str(other_tpl.id)])
        self.assertEqual(response.status_code, 404)
        self.assertTrue(MOUSignator.objects.filter(pk=other_tpl.pk).exists())

    def test_edit_signator_of_another_mou_is_refused(self):
        other, other_tpl, _ = _mou(self.ce, self.mou.academic_year)
        response = self._bulk(self.ce, method='post', action='edit_mou_signator',
                              mou_id=str(self.mou.id), id=str(other_tpl.id),
                              weight=2, role_type='college_admin')
        self.assertEqual(response.status_code, 404)
        other_tpl.refresh_from_db()
        self.assertEqual(other_tpl.weight, 1)

    def test_delete_signator_requires_mou_id(self):
        response = self._bulk(self.ce, method='post', action='delete_signator',
                              ids=[str(self.tpl.id)])
        self.assertEqual(response.status_code, 404)
        self.assertTrue(MOUSignator.objects.filter(pk=self.tpl.pk).exists())

    def test_signature_of_another_mou_is_refused_when_mou_posted(self):
        other, _, other_sig = _mou(self.ce, self.mou.academic_year)
        response = self._bulk(self.ce, method='post', action='delete_signature',
                              mou_id=str(self.mou.id), ids=[str(other_sig.id)])
        self.assertEqual(response.status_code, 404)
        self.assertTrue(MOUSignature.objects.filter(pk=other_sig.pk).exists())

    def test_own_signator_delete_works(self):
        response = self._bulk(self.ce, method='post', action='delete_signator',
                              mou_id=str(self.mou.id), confirm='on',
                              ids=[str(self.tpl.id)])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MOUSignator.objects.filter(pk=self.tpl.pk).exists())

    def test_non_uuid_ids_are_404(self):
        for params in ({'action': 'delete_signature', 'ids': ['zzz']},
                       {'action': 'add_signator', 'mou_id': 'zzz'},
                       {'action': 'get_signature_link', 'ids[]': ['zzz']}):
            with self.subTest(params=params):
                response = self._bulk(self.ce, method='post', **params)
                self.assertEqual(response.status_code, 404)

    def test_unknown_mou_id_is_404_not_500(self):
        response = self._bulk(self.ce, action='add_signator',
                              mou_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 404)


class NonUuidActionIdTests(_Base):
    def _req(self, value):
        request = RequestFactory().post('/', {'ids[]': [value]})
        request.user = self.ce
        return request

    def test_duplicate_and_delete_non_uuid_are_404(self):
        for fn in (views.duplicate_mou, views.delete_mou):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(Http404):
                    fn(self._req('not-a-uuid'))
        self.assertTrue(MOU.objects.filter(pk=self.mou.pk).exists())


class MultiCampusFormsAndIdsTests(_ScopedBase):
    @override_settings(MULTI_CAMPUS=True)
    def test_year_choices_are_this_campuss(self):
        request = RequestFactory().get('/')
        request.user = self.ce
        with self.campus_context(self.a):
            for form in (forms.MOUInitForm(request),
                         forms.MOUFinalizeForm(request, self.mine[0])):
                years = set(form.fields['academic_year'].queryset
                            .values_list('pk', flat=True))
                self.assertIn(self.mine[0].academic_year_id, years)
                self.assertNotIn(self.theirs[0].academic_year_id, years)

    @override_settings(MULTI_CAMPUS=True)
    def test_other_campus_year_is_rejected_on_create(self):
        request = RequestFactory().get('/')
        request.user = self.ce
        with self.campus_context(self.a):
            form = forms.MOUInitForm(request, data={
                'group_by': MOU.GROUP_BY_CHOICES[0][0], 'title': 't',
                'academic_year': str(self.theirs[0].academic_year_id)})
            self.assertFalse(form.is_valid())
            self.assertIn('academic_year', form.errors)

    @override_settings(MULTI_CAMPUS=True)
    def test_bulk_ids_field_name_is_scope_checked(self):
        sig = self.theirs[2]
        with self.campus_context(self.a):
            response = self._bulk(self.ce, method='post',
                                  action='delete_signature', ids=[str(sig.id)])
        self.assertEqual(response.status_code, 404)
        self.assertTrue(MOUSignature.objects.filter(pk=sig.pk).exists())

    @override_settings(MULTI_CAMPUS=True)
    def test_detail_edit_of_other_campus_signator_changes_nothing(self):
        tpl = self.theirs[1]
        request = RequestFactory().post('/', _post_data(tpl))
        request.user = self.ce
        request._dont_enforce_csrf_checks = True
        with self.campus_context(self.a):
            with self.assertRaises(Http404):
                views.mou(request, self.mine[0].id)
        tpl.refresh_from_db()
        self.assertEqual((tpl.weight, tpl.title), (1, ''))
