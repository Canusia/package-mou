"""High-school admin portal: retrieve signed MOUs for the admin's schools."""
from collections import OrderedDict

from django.contrib.auth.decorators import user_passes_test
from django.http import Http404
from django.shortcuts import render

from cis.menu import draw_menu
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSAdministrator, HSAdministratorPosition
from cis.utils import user_has_highschool_admin_role

from .models import MOUSignature
from .settings.helpers import (
    hs_admin_can_view_signed_mous,
    retention_years,
    signature_within_retention,
)


def _hs_admin_menu():
    # Same source as the rest of the HS portal (Settings → Misc → Menu).
    try:
        from highschool_admin.views.utils import get_hsadmin_menu
        return get_hsadmin_menu()
    except Exception:
        from cis.menu import HS_ADMIN_MENU
        return HS_ADMIN_MENU


def _schools_for_user(user):
    try:
        admin = HSAdministrator.objects.get(user=user)
    except HSAdministrator.DoesNotExist:
        return HighSchool.objects.none()
    return HighSchool.objects.filter(
        id__in=HSAdministratorPosition.objects.filter(
            hsadmin=admin,
            status__iexact='active',
        ).values_list('highschool_id', flat=True)
    )


@user_passes_test(user_has_highschool_admin_role, login_url='/')
def signed_mous(request):
    if not hs_admin_can_view_signed_mous():
        raise Http404()

    schools = _schools_for_user(request.user)
    years = retention_years()
    signatures = MOUSignature.objects.filter(
        highschool__in=schools,
        status='signed',
    ).select_related(
        'highschool',
        'signator_template__mou',
        'signator_template__mou__academic_year',
    ).order_by('-created_on')

    # One row per school × MOU; any signed signature's PDF includes all
    # signatures collected so far for that school.
    grouped = OrderedDict()
    for sig in signatures:
        if not signature_within_retention(sig, years):
            continue
        key = (sig.signator_template.mou_id, sig.highschool_id)
        if key not in grouped:
            grouped[key] = sig

    menu = draw_menu(_hs_admin_menu(), 'mous', '', 'highschool_admin')
    return render(request, 'mou/hs_admin/signed_mous.html', {
        'menu': menu,
        'page_title': 'Signed MOUs',
        'records': list(grouped.values()),
        'retention_years': years,
    })
