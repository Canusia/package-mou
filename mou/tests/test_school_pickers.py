"""Campus-scoped school picker on the MOU "Add High School(s)" form
(cis HighSchoolCampus)."""
import uuid

from django.conf import settings
from django.test import RequestFactory, TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus

try:
    from mou.mou.forms import AddHighSchoolForm
except ImportError:  # pragma: no cover - installed (non-nested) layout
    from mou.forms import AddHighSchoolForm


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(
        name=f'C-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}_{_sfx()[:6]}')


def _hs(name, campus=None, status='Active'):
    hs = HighSchool.objects.create(name=name, code=_sfx())
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    if campus is not None:
        HighSchoolCampus.objects.create(
            highschool=hs, campus=campus, status=status)
    return hs


class _Base(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.mine = _hs('Mine', self.a)
        self.foreign = _hs('Foreign', self.b)
        self.dormant = _hs('Dormant', self.a, 'Inactive')

    def _form(self, data=None):
        return AddHighSchoolForm(mou_id=str(uuid.uuid4()), data=data)


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTests(_Base):
    def test_excludes_other_campus_and_inactive_schools(self):
        with campus_context(self.a):
            qs = self._form().fields['highschools'].queryset
            self.assertEqual(list(qs), [self.mine])

    def test_foreign_post_is_rejected(self):
        with campus_context(self.a):
            form = self._form({
                'highschools': [str(self.foreign.pk)],
                'action': 'add_highschools', 'mou_id': str(uuid.uuid4())})
            self.assertFalse(form.is_valid())
            self.assertIn('highschools', form.errors)

    def test_own_school_post_passes_field_validation(self):
        with campus_context(self.a):
            form = self._form({
                'highschools': [str(self.mine.pk)],
                'action': 'add_highschools', 'mou_id': str(uuid.uuid4())})
            form.is_valid()
            self.assertNotIn('highschools', form.errors)

    def test_follows_the_request_campus(self):
        with campus_context(self.b):
            qs = self._form().fields['highschools'].queryset
            self.assertEqual(list(qs), [self.foreign])


@override_settings(MULTI_CAMPUS=False)
class SingleCampusTests(_Base):
    def test_options_are_campus_linked_active_schools(self):
        with campus_context(self.a):
            qs = self._form().fields['highschools'].queryset
            self.assertEqual(list(qs), [self.mine])


@override_settings(MULTI_CAMPUS=True)
class ModalListTests(_Base):
    """The modal's checkbox list is the same chooser as the form field."""

    def test_modal_lists_only_the_campus_schools(self):
        from mou.mou import views
        captured = {}

        def fake_render(request, template, context):
            captured.update(context)
            return None

        from unittest import mock
        request = RequestFactory().get('/', {'mou_id': str(uuid.uuid4())})
        with campus_context(self.a), mock.patch.object(views, 'render', fake_render):
            views.add_highschools(request)
        self.assertEqual(list(captured['highschools']), [self.mine])
