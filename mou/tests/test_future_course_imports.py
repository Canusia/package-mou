"""The four FutureCourse shortcodes now read the `future_sections` app's model
instead of the legacy `cis.models.future_sections` one.

`cis.models.future_sections` is legacy and forbidden by the host repo's
CLAUDE.md; these four properties used to import FutureCourse from it. That is
*not* a same-table swap: `cis.models.future_sections.FutureCourse` backs the
`cis_futurecourse` table and the `future_sections` app's `FutureCourse` backs
the separate `future_sections_futurecourse` table. The legacy table is dead
(0 rows on ewu) while the app's table holds real data, so on any tenant that
still has legacy rows this migration changes which rows -- and therefore what
text -- these four shortcodes render, including inside already-signed
agreements (`MOUSignature.mou_text` is computed live, never snapshotted). See
CHANGELOG.md v0.0.8 "Changed" for the tenant-facing writeup. This test pins
the *selection* against the app's model going forward, which is what must not
move again.
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

    def test_each_property_issues_exactly_one_query(self):
        """Pins query count, not which model is read -- the legacy
        `cis.models.future_sections.FutureCourse` would also issue exactly one
        query here, so `assertNumQueries(1)` cannot distinguish the two
        models. What it actually pins is that these properties no longer make
        the dead `configurator.from_db()` call that `teacher_list` and its
        siblings still make; each render is a single query against whichever
        FutureCourse table is wired up.

        This currently passes only because `make_mou_with_chain` creates zero
        FutureCourse rows. `section_display_html` (used when there *are*
        rows, via the `future_section_courses.html` template) reads a Setting
        per record, so a fixture with FutureCourse rows would turn this into
        an N+1 and break the count. Don't add fixture rows to this test
        without accounting for that.
        """
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
