import uuid

from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.term import AcademicYear


def _models():
    try:
        from mou.mou.models import MOU, MOUSignator, MOUSignature
        from mou.mou.settings.email_settings import AVAILABLE_SHORTCODES
    except ImportError:
        from mou.models import MOU, MOUSignator, MOUSignature
        from mou.settings.email_settings import AVAILABLE_SHORTCODES
    return MOU, MOUSignator, MOUSignature, AVAILABLE_SHORTCODES


class ShortcodeAllowListTests(TestCase):
    def test_allow_list_includes_district_and_approved_courses_and_signature_6(self):
        _, _, _, AVAILABLE_SHORTCODES = _models()
        keys = {k for k, _ in AVAILABLE_SHORTCODES}
        for expected in (
            'district_name', 'district_address1', 'district_city',
            'district_state', 'district_zip', 'approved_course_list',
            'signature_1', 'signature_6', 'signature_8',
        ):
            self.assertIn(expected, keys)


class DistrictShortcodeRenderTests(TestCase):
    def setUp(self):
        MOU, MOUSignator, MOUSignature, _ = _models()
        self.creator = CustomUser.objects.create(username='c', email='c@example.com')
        self.signer = CustomUser.objects.create(username='s', email='s@example.com')
        ay = AcademicYear.objects.create(name='2026-27')
        self.mou = MOU.objects.create(
            title='T', cron='0 7 * * *', academic_year=ay, created_by=self.creator,
            mou_text='District: {{district_name}} Year: {{academic_year}} {{signature_6}}',
        )
        tpl = MOUSignator.objects.create(
            mou=self.mou, created_by=self.creator, weight=1,
            role_type='college_admin', role=uuid.uuid4(),
        )
        self.hs = HighSchool.objects.create(
            name='North HS', code='N1', status='Active',
        )
        self.signature = MOUSignature.objects.create(
            highschool=self.hs, signator=self.signer, signator_template=tpl,
            status='pending', meta={},
        )

    def test_missing_district_renders_empty_not_error(self):
        html = self.signature.mou_text
        self.assertIn('District:', html)
        self.assertIn('2026-27', html)
        self.assertIn('Not yet signed', html)
