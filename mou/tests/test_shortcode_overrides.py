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
        with patch('cis.services.tenant_services.get_tenant_override',
                   return_value=None):
            html = self.sig.future_course_list
        self.assertIsInstance(html, str)

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
             patch('mou.mou.models.render_to_string') as mock_render:
            self.sig.future_course_list

        rendered_courses = mock_render.call_args.args[1]['courses']
        self.assertIs(rendered_courses, captured['returned'])
        self.assertIn('submitted_on', str(rendered_courses.query))
