"""Seams onto package-cis / host modules that not every tenant has (package-mou#2).

Tenants that keep ``cis`` in their own repo (embry, stockton, rmu, …) have no
``cis.highschool_scope``, ``cis.campus_context``, ``HighSchoolCampus`` or
``cis.services.tenant_services``, and some hosts have no
``myce.component_registry``. Every such import goes through here.

Presence is tested with ``importlib.util.find_spec``, not ``try/except
ImportError``, so a real import error inside a multi-campus ``cis`` still
surfaces instead of silently switching the package to pre-campus behaviour.

Without campus support the package behaves as it did before campus scoping:
pickers and signature seeding use every school whose own status is Active.
"""
import importlib.util

from django.db.models import F, OuterRef, Subquery
from django.db.models.functions import Coalesce


def has_module(name):
    """True when ``name`` is importable; False when it or a parent is missing.

    ``find_spec('a.b')`` imports ``a`` and raises ModuleNotFoundError when ``a``
    itself is absent (e.g. an in-repo cis with no ``cis.services`` package).
    Only that case means "missing"; any other error propagates.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError as exc:
        if exc.name and (name == exc.name or name.startswith(exc.name + '.')):
            return False
        raise


# package-cis >= 0.1.7a (the optional ``campus`` extra) ships
# cis.highschool_scope, cis.campus_context and HighSchoolCampus together, but a
# host may ship a stand-in highschool_scope without the link model (embry), so
# with_campus_status() checks for the model itself. A package-cis between
# 0.1.0a and 0.1.6a has campus_context but no highschool_scope, so
# is_multi_campus() reads False there even with MULTI_CAMPUS=True; no tenant is
# in that window (all pins are >= 0.1.29a) and v0.0.10 required >= 0.1.7a.
HAS_CAMPUS = has_module('cis.highschool_scope')
HAS_TENANT_SERVICES = has_module('cis.services.tenant_services')
HAS_COMPONENT_REGISTRY = has_module('myce.component_registry')


def _legacy_active_highschools():
    from cis.models.highschool import HighSchool
    return HighSchool.objects.filter(status__iexact='active')


def is_multi_campus():
    if not HAS_CAMPUS:
        return False
    from cis.campus_context import is_multi_campus as _is_multi_campus
    return _is_multi_campus()


def current_campus_or_none():
    if not HAS_CAMPUS:
        return None
    from cis.campus_context import current_campus_or_none as _current
    return _current()


def campus_highschools(campus=None):
    """Schools with an Active link to ``campus``; pre-campus: Active schools.

    With campus support and no campus, cis decides: single-campus keeps the
    Active schools, multi-campus returns none.
    """
    if not HAS_CAMPUS:
        return _legacy_active_highschools()
    from cis.highschool_scope import campus_highschools as _campus_highschools
    return _campus_highschools(campus)


def picker_queryset(campus=None):
    """The schools the Add High School(s) picker offers, by name."""
    if not HAS_CAMPUS:
        return _legacy_active_highschools().order_by('name')
    from cis.highschool_scope import picker_queryset as _picker_queryset
    return _picker_queryset(campus)


def _highschool_campus_model():
    """The ``cis.HighSchoolCampus`` model, or None when this cis has none.

    Decided on its own, not from ``HAS_CAMPUS``: a host may ship a stand-in
    ``cis.highschool_scope`` (embry) without the link model, or with a
    non-model shim, which ``apps.get_model`` does not return.
    """
    from django.apps import apps
    try:
        return apps.get_model('cis', 'HighSchoolCampus')
    except LookupError:
        return None


def with_campus_status(qs, campus):
    """Annotate ``campus_status``: the school's link status on ``campus``,
    falling back to its own status. The fallback applies whenever there is no
    link table (no ``HighSchoolCampus`` model) or no real campus (None, or a
    stand-in with no pk), whatever ``HAS_CAMPUS`` says."""
    link = _highschool_campus_model()
    if link is None or getattr(campus, 'pk', None) is None:
        return qs.annotate(campus_status=F('status'))
    return qs.annotate(campus_status=Coalesce(
        Subquery(link.objects.filter(
            highschool=OuterRef('pk'), campus=campus).values('status')[:1]),
        F('status')))


def get_tenant_override(app, name):
    """The tenant's ``services/<app>.py`` override, or None when cis has no
    tenant-services seam."""
    if not HAS_TENANT_SERVICES:
        return None
    from cis.services.tenant_services import get_tenant_override as _get
    return _get(app, name)
