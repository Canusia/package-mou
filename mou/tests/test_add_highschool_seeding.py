"""Signatures are created by the Add High School(s) form, not by finalizing
(review I-2): ``MOU.initialize_signatures()`` has no caller. The form's school
choices follow the same fallback the dead method documents:

* no campus scoping in cis (in-repo cis): every Active school;
* campus-aware cis, single-campus, no campus resolves: every Active school;
* multi-campus with no campus: none (fails closed).
"""
import uuid
from unittest import mock

from django.test import TestCase, override_settings

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.term import AcademicYear

from .. import compat
from ..forms import AddHighSchoolForm
from ..models import MOU, MOUSignator, MOUSignature


def _sfx():
    return uuid.uuid4().hex[:8]


class _Base(TestCase):
    def setUp(self):
        self.ce = CustomUser.objects.create(
            username=f'ce-{_sfx()}', email=f'{_sfx()}@x.com')
        self.college = CustomUser.objects.create(
            username=f'col-{_sfx()}', email=f'{_sfx()}@x.com')
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        if getattr(ay, 'campus_id', None) is not None:
            AcademicYear.objects.filter(pk=ay.pk).update(campus=None)
        self.mou = MOU.objects.create(
            title='T', cron='*/5 * * * *', academic_year_id=ay.pk,
            created_by=self.ce, mou_text='')
        self.signator = MOUSignator.objects.create(
            mou=self.mou, weight=3, role_type='college_admin', role=uuid.uuid4(),
            college_user=self.college, created_by=self.ce, meta={})
        self.active = HighSchool.objects.create(
            name=f'Active {_sfx()}', code=_sfx(), status='Active')
        self.inactive = HighSchool.objects.create(
            name=f'Inactive {_sfx()}', code=_sfx(), status='Inactive')

    def _post(self, *schools):
        return AddHighSchoolForm(mou_id=self.mou.id, data={
            'action': 'add_highschools',
            'mou_id': str(self.mou.id),
            'highschools': [str(s.pk) for s in schools],
        })

    def _assert_seeds_active_only(self):
        form = self._post(self.active)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertTrue(MOUSignature.objects.filter(
            highschool=self.active, signator_template=self.signator,
            signator=self.college).exists())
        self.assertFalse(self._post(self.inactive).is_valid())


@mock.patch.object(compat, 'HAS_CAMPUS', False)
class NoCampusScopingTests(_Base):
    def test_add_highschools_seeds_active_schools(self):
        self._assert_seeds_active_only()


@override_settings(MULTI_CAMPUS=False)
class SingleCampusNoCampusTests(_Base):
    def setUp(self):
        if not compat.HAS_CAMPUS:
            self.skipTest('cis.highschool_scope unavailable')
        super().setUp()

    def test_add_highschools_seeds_active_schools(self):
        with mock.patch('cis.campus_context.deployment_campus', return_value=None):
            self._assert_seeds_active_only()


class MultiCampusNoCampusTests(_Base):
    def setUp(self):
        if not compat.HAS_CAMPUS:
            self.skipTest('cis.highschool_scope unavailable')
        super().setUp()

    @override_settings(MULTI_CAMPUS=True)
    def test_add_highschools_offers_nothing(self):
        self.assertFalse(self._post(self.active).is_valid())
        self.assertFalse(MOUSignature.objects.filter(
            signator_template=self.signator).exists())
