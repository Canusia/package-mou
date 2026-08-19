"""Shared test object graphs for mou/tests/.

Copied from the setUp() in test_request_changes.py, which already proves
this graph works end-to-end (creation, signing, notifications). Extended to
build a chain of signers at arbitrary weights for a single school.

`make_mou_with_chain`'s signature and return shape (mou, highschool, sigs) are
depended on by four test modules -- do not change either. New fixture helpers
for courses / certificates / future-course rows are added below instead,
built to compose with `make_mou_with_chain`'s output rather than replace it.
"""
import itertools

from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition
from cis.models.course import Course, Cohort
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate

from ..models import MOU, MOUSignator, MOUSignature

_counter = itertools.count()


def make_mou_with_chain(weights):
    """Build one MOU, one HighSchool, and a MOUSignature per weight.

    Returns (mou, highschool, {weight: MOUSignature}).
    """
    creator = CustomUser.objects.create(
        username=f'creator-{"-".join(str(w) for w in weights)}',
        email=f'creator-{"-".join(str(w) for w in weights)}@example.com',
    )
    hs = HighSchool.objects.create(
        name=f'Chain Test HS {"-".join(str(w) for w in weights)}',
        code=str(abs(hash(tuple(weights))))[:6].zfill(6),
        status='active',
    )
    position = HSPosition.objects.create(
        name=f'Position {"-".join(str(w) for w in weights)}',
    )
    ay, _ = AcademicYear.objects.get_or_create(name='2025-2026')

    mou = MOU.objects.create(
        title='Chain Test MOU',
        cron='*/5 * * * *',
        academic_year=ay,
        created_by=creator,
        mou_text='',
    )

    sigs = {}
    for weight in weights:
        signator_user = CustomUser.objects.create(
            username=f'signator-{weight}-{hs.pk}',
            email=f'signator-{weight}-{hs.pk}@example.com',
            first_name=f'Signer{weight}',
            last_name='Chain',
        )
        signator_tpl = MOUSignator.objects.create(
            mou=mou,
            created_by=creator,
            weight=weight,
            role_type='highschool_admin',
            role=position.id,
            meta={},
        )
        sigs[weight] = MOUSignature.objects.create(
            highschool=hs,
            signator=signator_user,
            signator_template=signator_tpl,
            status='',
            meta={},
        )

    return mou, hs, sigs


def make_course(stream='', name=None):
    """A minimal certified/active Course, optionally tagged with a stream.

    `stream` should be one of the values the shortcode properties filter on
    ('pathways', 'cccl', 'dual_enrollment') or '' for a plain course that
    belongs to none of those families.
    """
    n = next(_counter)
    cohort, _ = Cohort.objects.get_or_create(
        designator=f'FX{n}', defaults={'name': f'Fixture Cohort {n}'})
    return Course.objects.create(
        cohort=cohort,
        catalog_number=str(100 + n),
        title=name or f'Fixture Course {n}',
        name=name or f'FX {n}',
        credit_hours=3,
        status='Active',
        stream=stream,
    )


def make_certificate(highschool, course=None, status='Teaching', stream=''):
    """A TeacherCourseCertificate for a fresh teacher at `highschool`.

    Builds its own CustomUser/Teacher/TeacherHighSchool so each call is an
    independent teacher -- callers wanting the *same* teacher across multiple
    certificates should build the TeacherHighSchool once and pass it in via a
    lower-level helper, but the common case (two different teachers whose
    certificates both point at the same Course, to prove dedup) is served by
    calling this twice with the same `course`.
    """
    from django.contrib.auth.models import Group
    # TeacherHighSchool.save() adds the teacher's user to the 'instructor'
    # group; the group is normally seeded by init_groups.
    Group.objects.get_or_create(name='instructor')

    n = next(_counter)
    course = course or make_course(stream=stream)
    user = CustomUser.objects.create(
        username=f'fx-teacher-{n}@example.com',
        email=f'fx-teacher-{n}@example.com',
        first_name=f'Fixture{n}', last_name='Teacher',
    )
    teacher = Teacher.objects.create(user=user)
    ths = TeacherHighSchool.objects.create(teacher=teacher, highschool=highschool)
    return TeacherCourseCertificate.objects.create(
        teacher_highschool=ths, course=course, status=status,
    )


def make_future_course(certificate, academic_year, teaching='yes', submitted=True):
    """A FutureCourse row (the future_sections app's model, not the legacy
    cis.models.future_sections one -- see test_future_course_imports.py) for
    `certificate`, with `section_info.teaching` set so the
    `section_info__teaching='yes'` filter used by pathways/choice/facilitator/
    course_list can be exercised in either direction.
    """
    import importlib.util
    if importlib.util.find_spec('future_sections.future_sections'):
        from future_sections.future_sections.models import FutureCourse
    else:
        from future_sections.models import FutureCourse

    import datetime
    return FutureCourse.objects.create(
        teacher_course=certificate,
        academic_year=academic_year,
        section_info={'teaching': teaching, 'sections': []},
        submitted_on=datetime.date.today() if submitted else None,
    )
