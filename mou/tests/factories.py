"""Shared test object graphs for mou/tests/.

Copied from the setUp() in test_request_changes.py, which already proves
this graph works end-to-end (creation, signing, notifications). Extended to
build a chain of signers at arbitrary weights for a single school.
"""
from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition

from ..models import MOU, MOUSignator, MOUSignature


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
