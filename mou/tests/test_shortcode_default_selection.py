"""Row-level pins for the nine list shortcodes' *default* selection.

No prior test built real fixture rows and asserted which rows survive the
package's own filters with no tenant override in play -- every override test
in test_shortcode_overrides.py patches `get_tenant_override` and only checks
that the queryset the override receives has a `.filter` method, and
test_future_course_imports.py runs against zero FutureCourse rows. That means
dropping the `teacher_course_status` filter, or `choice_teacher_list`'s
`pathways` exclusion, or a `FutureCourse` property's
`section_info__teaching='yes'` filter would fail nothing. This module closes
that gap.
"""
from django.test import TestCase

from cis.models.settings import Setting
from cis.models.term import AcademicYear

from ..settings.email_settings import email_settings
from .factories import (
    make_mou_with_chain, make_certificate, make_course, make_future_course,
)


def _configure(teacher_course_status):
    """Write the SettingForm's teacher_course_status list the way the CE
    admin UI would, under whichever key this layout's configurator resolves
    to (`email_settings.from_db` already handles the nested/flat ambiguity;
    writing under `email_settings.key` matches what `install()`/`run_record`
    would have written)."""
    setting, _ = Setting.objects.get_or_create(
        key=email_settings.key,
        defaults={'value': {'teacher_course_status': teacher_course_status}},
    )
    setting.value = {'teacher_course_status': teacher_course_status}
    setting.save()


class TeacherCourseStatusFilterTests(TestCase):
    """`teacher_list` (and its choice/pathways siblings) only include
    certificates whose status is in the configured `teacher_course_status`
    list."""

    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]
        _configure(['Teaching'])

    def test_teacher_course_status_filter_excludes_a_non_matching_status(self):
        matching = make_certificate(self.school, status='Teaching')
        excluded = make_certificate(self.school, status='Inactive')

        rendered = self.sig.teacher_list

        # first_name is per-fixture-instance ('Fixture<n>'); last_name is a
        # constant 'Teacher' shared by every make_certificate() call and
        # would not distinguish the two rows.
        self.assertIn(matching.teacher_highschool.teacher.user.first_name, rendered)
        self.assertNotIn(excluded.teacher_highschool.teacher.user.first_name, rendered)


class ChoiceVsPathwaysTeacherListTests(TestCase):
    """`choice_teacher_list` excludes `pathways` courses; `pathways_teacher_list`
    includes them. Same certificate queryset, opposite `stream` filter."""

    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]

    def test_choice_teacher_list_excludes_a_pathways_course(self):
        pathways_course = make_course(stream='pathways')
        cert = make_certificate(self.school, course=pathways_course)

        rendered = self.sig.choice_teacher_list

        self.assertNotIn(cert.teacher_highschool.teacher.user.last_name, rendered)

    def test_pathways_teacher_list_includes_a_pathways_course(self):
        pathways_course = make_course(stream='pathways')
        cert = make_certificate(self.school, course=pathways_course)

        rendered = self.sig.pathways_teacher_list

        self.assertIn(cert.teacher_highschool.teacher.user.last_name, rendered)


class FutureCourseTeachingFilterTests(TestCase):
    """`course_list` (representative of the pathways/choice/facilitator/course
    family) only includes FutureCourse rows whose `section_info.teaching`
    is 'yes'."""

    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]
        self.ay, _ = AcademicYear.objects.get_or_create(name='2025-2026')
        # make_mou_with_chain always uses this same AcademicYear name, so
        # get_or_create above resolves to the MOU's own academic_year.

    def test_teaching_no_row_is_excluded(self):
        teaching_course = make_course(name='Teaching Course')
        not_teaching_course = make_course(name='Not Teaching Course')
        teaching_cert = make_certificate(self.school, course=teaching_course)
        not_teaching_cert = make_certificate(self.school, course=not_teaching_course)

        make_future_course(teaching_cert, self.ay, teaching='yes')
        make_future_course(not_teaching_cert, self.ay, teaching='no')

        rendered = self.sig.course_list

        self.assertIn('Teaching Course', rendered)
        self.assertNotIn('Not Teaching Course', rendered)
