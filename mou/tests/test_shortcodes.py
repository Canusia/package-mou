import uuid

from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.settings import Setting
from cis.models.term import AcademicYear

from .factories import make_mou_with_chain
from ..settings.email_settings import email_settings


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


class SignatureShortcodeGateTests(TestCase):
    """signature_N is structural: the choice gate must not blank it.

    AVAILABLE_SHORTCODES is built at import from DEFAULT_MAX_SIGNATOR_WEIGHT,
    while the rendered set comes from the max_signator_weight setting, so a
    tenant whose saved available_shortcodes predates a chain-length increase
    silently lost its signature blocks.
    """

    def test_signature_block_renders_when_missing_from_saved_shortcodes(self):
        Setting.objects.update_or_create(
            key=email_settings.key,
            defaults={'value': {
                # A pre-PR row: only the first four signature slots were offered.
                'available_shortcodes': [
                    'signature_1', 'signature_2', 'signature_3', 'signature_4',
                    'highschool_name',
                ],
                'max_signator_weight': 6,
            }},
        )
        mou, school, sigs = make_mou_with_chain(weights=[1, 5])
        mou.mou_text = 'Sig five: {{signature_5}}'
        mou.save(update_fields=['mou_text'])
        rendered = sigs[5].mou_text
        self.assertNotIn('Sig five: \n', rendered)
        self.assertIn('Not yet signed', rendered)

    def test_non_signature_shortcode_is_still_gated(self):
        Setting.objects.update_or_create(
            key=email_settings.key,
            defaults={'value': {
                'available_shortcodes': ['signature_1'],
                'max_signator_weight': 2,
            }},
        )
        mou, school, sigs = make_mou_with_chain(weights=[1])
        mou.mou_text = 'School: {{highschool_name}}'
        mou.save(update_fields=['mou_text'])
        self.assertEqual(sigs[1].mou_text.strip(), 'School:')
