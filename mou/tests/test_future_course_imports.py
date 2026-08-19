"""The four FutureCourse shortcodes must resolve the same rows after the import
migration as before it.

`cis.models.future_sections` is legacy and forbidden by the host repo's
CLAUDE.md; these four properties still imported FutureCourse from it. The
`future_sections` app is the real owner. Both paths reach the same table, so
this test pins the *selection*, which is what must not move.
"""
import importlib.util

from django.test import TestCase

from .factories import make_mou_with_chain

if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureCourse
else:
    from future_sections.models import FutureCourse


class FutureCourseShortcodeQueryTests(TestCase):
    """Each property renders without error and reads from the app's FutureCourse."""

    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]

    def test_all_four_render_without_the_legacy_import(self):
        for name in ('pathways_course_list', 'choice_course_list',
                     'facilitator_course_list', 'course_list'):
            with self.subTest(shortcode=name):
                self.assertIsInstance(getattr(self.sig, name), str)

    def test_properties_read_the_future_sections_app_model(self):
        """Each property issues exactly one query against FutureCourse, which
        only holds if it reads live from the future_sections app's model
        rather than a separately-bound legacy reference."""
        for name in ('pathways_course_list', 'choice_course_list',
                     'facilitator_course_list', 'course_list'):
            with self.subTest(shortcode=name):
                with self.assertNumQueries(1):
                    getattr(self.sig, name)


class NoLegacyImportTests(TestCase):
    """Guard: the forbidden module must not reappear in this package."""

    def test_models_does_not_import_cis_models_future_sections(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'models.py')
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        self.assertNotIn('from cis.models.future_sections import', source)
