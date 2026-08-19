"""Every shortcode with an override must document its override name.

A seam nobody can find is a seam nobody uses. This fails if a shortcode gains an
override without a matching line in the readme.
"""
import os

from django.test import SimpleTestCase

OVERRIDE_NAMES = (
    'teacher_queryset', 'choice_teacher_queryset', 'pathways_teacher_queryset',
    'approved_course_list', 'pathways_course_queryset', 'choice_course_queryset',
    'facilitator_course_queryset', 'course_queryset', 'future_course_queryset',
)

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OverrideNamesAreDocumentedTests(SimpleTestCase):
    def test_every_override_name_appears_in_the_readme(self):
        """Plain substring containment is too weak: `course_queryset` is a
        substring of `future_course_queryset`, `choice_course_queryset`,
        `pathways_course_queryset` and `facilitator_course_queryset` (and
        likewise `teacher_queryset` is a substring of its `choice_`/
        `pathways_` siblings), so deleting `course_queryset`'s own readme row
        would not fail this test under plain `in`. The readme documents each
        override name as a backticked table token (see readme.md section 6),
        so require that exact token rather than a bare substring.
        """
        with open(os.path.join(PKG_ROOT, 'readme.md'), encoding='utf-8') as fh:
            readme = fh.read()
        missing = [n for n in OVERRIDE_NAMES if f'`{n}`' not in readme]
        self.assertEqual(missing, [], f'undocumented overrides: {missing}')

    def test_every_documented_name_is_actually_consulted(self):
        with open(os.path.join(PKG_ROOT, 'models.py'), encoding='utf-8') as fh:
            models_src = fh.read()
        missing = [n for n in OVERRIDE_NAMES
                   if f"_tenant_mou_override('{n}')" not in models_src]
        self.assertEqual(missing, [], f'documented but never consulted: {missing}')
