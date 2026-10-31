"""mou installs and runs on a tenant whose cis has no campus scoping, no
tenant-services seam, or whose host has no myce.component_registry
(package-mou#2). Without campus scoping it behaves as before campus links:
every Active school is offered and seeded. Multi-campus with no campus still
fails closed (test_initialize_signatures_campus)."""
import configparser
import os
import tomllib
import uuid
from unittest import mock

from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.term import AcademicYear

from .. import _actions, compat, views
from ..forms import AddHighSchoolForm
from ..models import MOU, _tenant_mou_override

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def _sfx():
    return uuid.uuid4().hex[:8]


class MetadataTests(SimpleTestCase):
    """myce_cis is the optional ``campus`` extra, never a requirement."""

    def _read(self, name):
        path = os.path.join(REPO_ROOT, name)
        if not os.path.exists(path):  # installed wheel: no repo metadata
            self.skipTest(f'{name} not shipped')
        with open(path) as fh:
            return fh.read()

    def test_setup_cfg(self):
        cfg = configparser.ConfigParser()
        cfg.read_string(self._read('setup.cfg'))
        self.assertNotIn('myce_cis', cfg['options']['install_requires'])
        self.assertIn('myce_cis', cfg['options.extras_require']['campus'])

    def test_pyproject(self):
        project = tomllib.loads(self._read('pyproject.toml'))['project']
        self.assertFalse(any('myce_cis' in d for d in project['dependencies']))
        self.assertTrue(any('myce_cis' in d
                            for d in project['optional-dependencies']['campus']))


class HasModuleTests(SimpleTestCase):
    def test_present(self):
        self.assertTrue(compat.has_module('cis.models'))

    def test_missing_leaf(self):
        self.assertFalse(compat.has_module('cis.no_such_module_xyz'))

    def test_missing_parent(self):
        # find_spec('a.b') raises when package a is absent: still "missing".
        self.assertFalse(compat.has_module('cis.no_such_pkg_xyz.tenant_services'))


class TenantOverrideTests(SimpleTestCase):
    def test_no_tenant_services_means_no_override(self):
        with mock.patch.object(compat, 'HAS_TENANT_SERVICES', False):
            self.assertIsNone(_tenant_mou_override('teacher_queryset'))


class VendoredActionRegistryTests(SimpleTestCase):
    def test_dispatch_and_scope(self):
        reg = _actions.ActionRegistry()

        @reg.action('general', label='Go', scope=['detail'], slug='go')
        def go(request):
            return 'ran'

        self.assertEqual(reg.dispatch(HttpRequest(), 'go'), 'ran')
        self.assertEqual(reg.dispatch(HttpRequest(), 'nope').status_code, 400)
        self.assertIn('go', reg.for_scope('detail')['general']['actions'])
        self.assertEqual(reg.for_scope('list'), {})


class _Schools(TestCase):
    def setUp(self):
        self.active = HighSchool.objects.create(
            name=f'Active {_sfx()}', code=_sfx(), status='Active')
        self.inactive = HighSchool.objects.create(
            name=f'Inactive {_sfx()}', code=_sfx(), status='Inactive')

    def _mou(self):
        creator = CustomUser.objects.create(
            username=f'c-{_sfx()}', email=f'{_sfx()}@x.com')
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        if getattr(ay, 'campus_id', None) is not None:
            AcademicYear.objects.filter(pk=ay.pk).update(campus=None)
            ay.refresh_from_db()
        return MOU.objects.create(
            title='T', cron='*/5 * * * *', academic_year=ay,
            created_by=creator, mou_text='')

    def _seed(self, mou):
        with mock.patch.object(MOU, 'can_edit', return_value=False):
            return mou.initialize_signatures()


@mock.patch.object(compat, 'HAS_CAMPUS', False)
class WithoutCampusScopingTests(_Schools):
    """A cis without cis.highschool_scope: the pre-campus behaviour."""

    def test_picker_offers_active_schools(self):
        pks = set(AddHighSchoolForm(mou_id='x').fields['highschools']
                  .queryset.values_list('pk', flat=True))
        self.assertIn(self.active.pk, pks)
        self.assertNotIn(self.inactive.pk, pks)

    def test_initialize_signatures_seeds_active_schools(self):
        result = self._seed(self._mou())
        self.assertIn(self.active.code, result)
        self.assertNotIn(self.inactive.code, result)

    def test_add_highschools_modal_uses_own_status(self):
        captured = {}

        def fake_render(request, template, context):
            captured.update(context)

        request = RequestFactory().get('/', {'mou_id': str(uuid.uuid4())})
        with mock.patch.object(views, 'render', fake_render):
            views.add_highschools(request)
        rows = {r.pk: r for r in captured['highschools']}
        self.assertEqual(rows[self.active.pk].campus_status, 'Active')
        self.assertNotIn(self.inactive.pk, rows)
        self.assertIn('Active schools.', str(captured['form_header']))
        self.assertNotIn('this campus', str(captured['form_header']))


@override_settings(MULTI_CAMPUS=False)
class SingleCampusNoCampusTests(_Schools):
    """Campus-aware cis, single-campus, but no campus resolves at all."""

    def setUp(self):
        if not compat.HAS_CAMPUS:
            self.skipTest('cis.highschool_scope unavailable')
        super().setUp()

    def test_initialize_signatures_seeds_active_schools(self):
        with mock.patch('cis.campus_context.deployment_campus', return_value=None):
            result = self._seed(self._mou())
        self.assertIn(self.active.code, result)
        self.assertNotIn(self.inactive.code, result)


class CampusStatusModelDetectionTests(_Schools):
    """``with_campus_status`` decides on the HighSchoolCampus *model* and a
    real campus, not on ``cis.highschool_scope`` (review I-1). Embry ships a
    stand-in ``highschool_scope`` with a non-model HighSchoolCampus shim and a
    pk-less stand-in campus."""

    def _rows(self, campus):
        qs = compat.with_campus_status(
            HighSchool.objects.filter(pk__in=[self.active.pk, self.inactive.pk]),
            campus)
        return {r.pk: r.campus_status for r in qs}

    def test_no_highschoolcampus_model_falls_back_even_with_highschool_scope(self):
        from django.apps import apps
        real = apps.get_model

        def get_model(app_label, model_name=None, *a, **kw):
            if (app_label, model_name) == ('cis', 'HighSchoolCampus') or \
                    app_label == 'cis.HighSchoolCampus':
                raise LookupError('no HighSchoolCampus model')
            return real(app_label, model_name, *a, **kw)

        with mock.patch.object(compat, 'HAS_CAMPUS', True), \
                mock.patch.object(apps, 'get_model', get_model), \
                mock.patch.dict('sys.modules', {'cis.models.highschool': None}):
            rows = self._rows(object())
        self.assertEqual(rows[self.active.pk], 'Active')
        self.assertEqual(rows[self.inactive.pk], 'Inactive')

    def test_campus_without_pk_falls_back(self):
        stand_in = type('SingleCampus', (), {'pk': None})()
        with mock.patch.object(compat, 'HAS_CAMPUS', True):
            rows = self._rows(stand_in)
        self.assertEqual(rows[self.active.pk], 'Active')

    def test_no_campus_falls_back(self):
        with mock.patch.object(compat, 'HAS_CAMPUS', True):
            rows = self._rows(None)
        self.assertEqual(rows[self.inactive.pk], 'Inactive')
