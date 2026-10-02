"""MOU.initialize_signatures only seeds the MOU's campus's Active schools
(cis HighSchoolCampus), and the Add High School(s) modal shows the link
status for the current campus."""
import uuid
from unittest import mock

from django.conf import settings
from django.test import RequestFactory, TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool, HighSchoolCampus
from cis.models.term import AcademicYear

try:
    from mou.mou.models import MOU
    from mou.mou import views
except ImportError:  # pragma: no cover - installed (non-nested) layout
    from mou.models import MOU
    from mou import views


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(
        name=f'C-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}_{_sfx()[:6]}')


def _hs(name, campus=None, status='Active'):
    hs = HighSchool.objects.create(name=name, code=_sfx())
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    if campus is not None:
        HighSchoolCampus.objects.create(highschool=hs, campus=campus, status=status)
    return hs


def _mou(campus=None):
    creator = CustomUser.objects.create(username=f'c-{_sfx()}', email=f'{_sfx()}@x.com')
    ay = AcademicYear.objects.create(name=f'AY-{_sfx()}', campus=campus or _campus())
    if campus is None:
        # A campus-less year (legacy data): save() refuses one in multi-campus.
        AcademicYear.objects.filter(pk=ay.pk).update(campus=None)
        ay.refresh_from_db()
    return MOU.objects.create(
        title='T', cron='*/5 * * * *', academic_year=ay,
        created_by=creator, mou_text='')


@override_settings(MULTI_CAMPUS=True)
class InitializeSignaturesTests(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.mine = _hs('Mine', self.a)
        self.dormant = _hs('Dormant', self.a, 'Inactive')
        self.foreign = _hs('Foreign', self.b)

    def _run(self, mou):
        with mock.patch.object(MOU, 'can_edit', return_value=False):
            return mou.initialize_signatures()

    def test_uses_the_mous_campus(self):
        mou = _mou(self.b)
        with campus_context(self.a):
            result = self._run(mou)
        self.assertEqual(set(result), {self.foreign.code})

    def test_falls_back_to_current_campus(self):
        mou = _mou(None)
        with campus_context(self.a):
            result = self._run(mou)
        self.assertEqual(set(result), {self.mine.code})

    def test_no_campus_creates_none_and_logs(self):
        mou = _mou(None)
        with self.assertLogs(level='WARNING'):
            result = self._run(mou)
        self.assertEqual(result, {})


@override_settings(MULTI_CAMPUS=True)
class ModalCampusStatusTests(TestCase):
    def test_modal_shows_campus_link_status_not_global(self):
        a, b = _campus(), _campus()
        hs = _hs('Shared', a, 'Active')
        HighSchoolCampus.objects.create(highschool=hs, campus=b, status='Inactive')
        request = RequestFactory().get('/', {'mou_id': str(uuid.uuid4())})
        captured = {}

        def fake_render(request, template, context):
            captured.update(context)
            return None

        with campus_context(b):
            # Inactive on b: not offered at all.
            with mock.patch.object(views, 'render', fake_render):
                views.add_highschools(request)
            self.assertEqual(list(captured['highschools']), [])
        with campus_context(a):
            with mock.patch.object(views, 'render', fake_render):
                views.add_highschools(request)
            rows = list(captured['highschools'])
        self.assertEqual([r.campus_status for r in rows], ['Active'])
        self.assertNotIn('or status', str(captured['form_header']))
