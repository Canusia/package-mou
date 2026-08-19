"""Tenant overrides for the MOU list shortcodes.

Which records belong in an MOU is tenant policy -- `approved_course_list`'s own
docstring cites one deployment's workbook -- but it was hardcoded in shared
package code. Each shortcode now resolves an opt-in override through
`cis.services.tenant_services.get_tenant_override`, the same mechanism behind
`StudentRegistration.needs_recommendation`.

The override receives (signature, default_queryset) so a tenant can refine the
package's selection rather than restate it.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ..models import _tenant_mou_override
from .factories import make_mou_with_chain

# The package installs nested (in-tree submodule, mou.mou -- what ewu mounts)
# or flat (pip-installed, mou). Resolve the render_to_string patch target the
# same way test_heads_up.py / test_request_changes.py resolve send_html_mail,
# so this test module works under either layout.
try:
    from mou.mou import models as _models_module
    _RENDER_TO_STRING = 'mou.mou.models.render_to_string'
except ImportError:
    from mou import models as _models_module
    _RENDER_TO_STRING = 'mou.models.render_to_string'


class TenantOverrideResolverTests(TestCase):
    def test_returns_none_when_the_tenant_ships_nothing(self):
        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=None):
            self.assertIsNone(_tenant_mou_override('future_course_queryset'))

    def test_returns_the_tenant_callable_when_present(self):
        sentinel = lambda signature, queryset: queryset
        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=sentinel):
            self.assertIs(
                _tenant_mou_override('future_course_queryset'), sentinel)

    def test_looks_the_override_up_in_the_mou_services_module(self):
        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=None) as gto:
            _tenant_mou_override('future_course_queryset')
        gto.assert_called_once_with('mou', 'future_course_queryset')


class FutureCourseListOverrideTests(TestCase):
    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]

    def test_default_selection_is_unchanged_without_an_override(self):
        """A tenant that opts in with a pass-through override must see byte-
        identical output to a tenant that ships no override at all -- the
        seam must be transparent when a tenant does nothing.
        """
        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=None):
            without_override = self.sig.future_course_list

        def pass_through(signature, queryset):
            return queryset

        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=pass_through):
            with_pass_through_override = self.sig.future_course_list

        self.assertIsInstance(without_override, str)
        self.assertEqual(without_override, with_pass_through_override)

    def test_override_receives_signature_and_default_queryset(self):
        seen = {}

        def override(signature, queryset):
            seen['signature'] = signature
            seen['queryset'] = queryset
            return queryset

        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=override):
            self.sig.future_course_list

        self.assertIs(seen['signature'], self.sig)
        # The default queryset, not a list -- so a tenant can refine it.
        self.assertTrue(hasattr(seen['queryset'], 'filter'))

    def test_override_return_value_is_what_gets_rendered(self):
        marker = MagicMock()
        marker.__len__ = MagicMock(return_value=1)
        marker.__iter__ = MagicMock(return_value=iter([]))

        def override(signature, queryset):
            return marker

        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=override):
            self.sig.future_course_list

        self.assertTrue(marker.__iter__.called)

    def test_a_refining_override_narrows_the_default(self):
        """The motivating case: default plus one extra filter.

        Asserts on the queryset actually handed to the template, not just on
        what the override happened to build -- an implementation that called
        the override but discarded its return value would otherwise still
        pass this test.
        """
        captured = {}

        def override(signature, queryset):
            refined = queryset.filter(submitted_on__isnull=False)
            captured['returned'] = refined
            return refined

        with patch('cis.services.tenant_services.get_tenant_override',
                    return_value=override), \
             patch(_RENDER_TO_STRING) as mock_render:
            self.sig.future_course_list

        rendered_courses = mock_render.call_args.args[1]['courses']
        self.assertIs(rendered_courses, captured['returned'])
        self.assertIn('submitted_on', str(rendered_courses.query))


class FutureCourseFamilyOverrideTests(TestCase):
    """Each FutureCourse shortcode has its own override name, and each is
    independent -- overriding one must not affect the others."""

    CASES = (
        ('pathways_course_list', 'pathways_course_queryset'),
        ('choice_course_list', 'choice_course_queryset'),
        ('facilitator_course_list', 'facilitator_course_queryset'),
        ('course_list', 'course_queryset'),
    )

    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]

    def test_each_property_looks_up_its_own_override_name(self):
        for prop, expected_name in self.CASES:
            with self.subTest(shortcode=prop):
                with patch('cis.services.tenant_services.get_tenant_override',
                           return_value=None) as gto:
                    getattr(self.sig, prop)
                names = [c.args[1] for c in gto.call_args_list]
                self.assertIn(expected_name, names)
                self.assertTrue(all(c.args[0] == 'mou'
                                    for c in gto.call_args_list))

    def test_each_override_receives_the_default_queryset(self):
        for prop, _name in self.CASES:
            with self.subTest(shortcode=prop):
                seen = {}

                def override(signature, queryset):
                    seen['qs'] = queryset
                    return queryset

                with patch('cis.services.tenant_services.get_tenant_override',
                           return_value=override):
                    getattr(self.sig, prop)
                self.assertTrue(hasattr(seen['qs'], 'filter'))

    def test_default_behaviour_is_unchanged_without_overrides(self):
        for prop, _name in self.CASES:
            with self.subTest(shortcode=prop):
                with patch('cis.services.tenant_services.get_tenant_override',
                           return_value=None):
                    self.assertIsInstance(getattr(self.sig, prop), str)

    def test_a_refining_override_narrows_what_is_rendered(self):
        """Asserts on the queryset actually handed to the template, not just
        on what the override built -- catches an implementation that calls
        the override but discards its return value.
        """
        for prop, _name in self.CASES:
            with self.subTest(shortcode=prop):
                captured = {}

                def override(signature, queryset):
                    refined = queryset.filter(id__in=[])
                    captured['returned'] = refined
                    return refined

                with patch('cis.services.tenant_services.get_tenant_override',
                            return_value=override), \
                     patch(_RENDER_TO_STRING) as mock_render:
                    getattr(self.sig, prop)

                rendered_courses = mock_render.call_args.args[1]['courses']
                self.assertIs(rendered_courses, captured['returned'])


class TeacherCertFamilyOverrideTests(TestCase):
    CASES = (
        ('teacher_list', 'teacher_queryset'),
        ('choice_teacher_list', 'choice_teacher_queryset'),
        ('pathways_teacher_list', 'pathways_teacher_queryset'),
    )

    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]

    def test_each_property_looks_up_its_own_override_name(self):
        for prop, expected_name in self.CASES:
            with self.subTest(shortcode=prop):
                with patch('cis.services.tenant_services.get_tenant_override',
                           return_value=None) as gto:
                    getattr(self.sig, prop)
                names = [c.args[1] for c in gto.call_args_list]
                self.assertIn(expected_name, names)

    def test_override_receives_a_refinable_queryset(self):
        for prop, _name in self.CASES:
            with self.subTest(shortcode=prop):
                seen = {}

                def override(signature, queryset):
                    seen['qs'] = queryset
                    return queryset

                with patch('cis.services.tenant_services.get_tenant_override',
                           return_value=override):
                    getattr(self.sig, prop)
                self.assertTrue(hasattr(seen['qs'], 'filter'))

    def test_a_refining_override_narrows_what_is_rendered(self):
        """Asserts on the queryset actually handed to the template -- catches
        an implementation that calls the override but discards the result.
        """
        for prop, _name in self.CASES:
            with self.subTest(shortcode=prop):
                captured = {}

                def override(signature, queryset):
                    refined = queryset.filter(id__in=[])
                    captured['returned'] = refined
                    return refined

                with patch('cis.services.tenant_services.get_tenant_override',
                            return_value=override), \
                     patch(_RENDER_TO_STRING) as mock_render:
                    getattr(self.sig, prop)

                rendered_teachers = mock_render.call_args.args[1]['teachers']
                self.assertIs(rendered_teachers, captured['returned'])


class ApprovedCourseListOverrideTests(TestCase):
    """This one hands over the deduplicated list, not the certificate queryset --
    the dedup is the property's purpose and must not be overridable away."""

    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]

    def test_override_name_and_payload(self):
        seen = {}

        def override(signature, courses):
            seen['courses'] = courses
            return courses

        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=override) as gto:
            self.sig.approved_course_list

        self.assertIn('approved_course_list',
                      [c.args[1] for c in gto.call_args_list])
        self.assertIsInstance(seen['courses'], list)

    def test_dedup_still_happens_before_the_override_sees_it(self):
        seen = {}

        def override(signature, courses):
            seen['ids'] = [c.id for c in courses]
            return courses

        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=override):
            self.sig.approved_course_list

        self.assertEqual(len(seen['ids']), len(set(seen['ids'])))

    def test_override_return_value_is_what_gets_rendered(self):
        """Asserts on the list actually handed to the template, not just on
        what the override built -- catches an implementation that calls the
        override but discards its return value.
        """
        marker = ['sentinel-course']

        def override(signature, courses):
            return marker

        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=override), \
             patch(_RENDER_TO_STRING) as mock_render:
            self.sig.approved_course_list

        rendered_courses = mock_render.call_args.args[1]['courses']
        self.assertIs(rendered_courses, marker)
