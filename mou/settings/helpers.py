"""Runtime helpers for MOU notification / policy settings.

Callers should use these instead of reading individual keys off
``email_settings.from_db()`` so missing keys (fresh installs, old JSON)
fall back to the same defaults the settings form seeds.
"""
from datetime import datetime, timedelta

from django.conf import settings as django_settings
from django.utils import timezone

DEFAULT_MAX_SIGNATOR_WEIGHT = 8
DEFAULT_VACANT_ROLE_POLICY = 'skip_silent'
DEFAULT_PDF_DOWNLOAD = 'after_only'
DEFAULT_RETENTION_YEARS = 6


def mou_cfg():
    from .email_settings import email_settings
    return email_settings.from_db() or {}


def get_max_signator_weight(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    try:
        n = int(cfg.get('max_signator_weight') or DEFAULT_MAX_SIGNATOR_WEIGHT)
    except (TypeError, ValueError):
        n = DEFAULT_MAX_SIGNATOR_WEIGHT
    return max(1, min(n, 20))


def college_admin_any_weight_allowed(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    return (cfg.get('allow_college_admin_any_weight') or 'Yes') != 'No'


def vacant_role_policy(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    value = cfg.get('vacant_role_policy') or DEFAULT_VACANT_ROLE_POLICY
    if value not in ('skip_silent', 'skip_and_notify', 'hold_school'):
        return DEFAULT_VACANT_ROLE_POLICY
    return value


def pdf_download_mode(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    value = cfg.get('pdf_download') or DEFAULT_PDF_DOWNLOAD
    if value not in ('before_and_after', 'after_only', 'never'):
        return DEFAULT_PDF_DOWNLOAD
    return value


def allow_change_requests(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    return (cfg.get('allow_change_requests') or 'Yes') != 'No'


def hs_admin_can_view_signed_mous(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    return (cfg.get('hs_admin_can_view_signed_mous') or 'No') == 'Yes'


def heads_up_email_enabled(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    return (cfg.get('heads_up_email') or 'No') == 'Yes'


def heads_up_include_college(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    return (cfg.get('heads_up_include_college') or 'No') == 'Yes'


def retention_years(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    try:
        n = int(cfg.get('retention_years') or DEFAULT_RETENTION_YEARS)
    except (TypeError, ValueError):
        n = DEFAULT_RETENTION_YEARS
    return max(0, n)


def is_active_mode(cfg=None):
    """Yes / Debug / No. Missing key is Debug so we never accidentally live-send."""
    cfg = cfg if cfg is not None else mou_cfg()
    value = cfg.get('is_active') or 'Debug'
    if value not in ('Yes', 'No', 'Debug'):
        return 'Debug'
    return value


def notification_recipients(intended_to, cfg=None):
    """Who should actually receive this MOU email.

    ``is_active`` is the master switch (workbook section 10). Django DEBUG
    still redirects live Yes-mode mail to notify_address as extra local safety.
    Returns None when nothing should be sent.
    """
    cfg = cfg if cfg is not None else mou_cfg()
    mode = is_active_mode(cfg)
    if mode == 'No':
        return None

    debug_to = [
        addr.strip()
        for addr in (cfg.get('notify_address') or '').split(',')
        if addr.strip()
    ]

    if mode == 'Debug' or getattr(django_settings, 'DEBUG', False):
        return debug_to or None

    if not intended_to:
        return None
    if isinstance(intended_to, str):
        intended_to = [intended_to]
    return [addr for addr in intended_to if addr]


def notify_address_list(cfg=None):
    cfg = cfg if cfg is not None else mou_cfg()
    return [
        addr.strip()
        for addr in (cfg.get('notify_address') or '').split(',')
        if addr.strip()
    ]


def signature_within_retention(signature, years=None):
    """True if this signed row should still be listed in the HS portal."""
    years = retention_years() if years is None else years
    if not years:
        return True
    cutoff = timezone.now() - timedelta(days=int(years) * 365)

    raw = (signature.meta or {}).get('signed_on')
    signed = None
    if raw:
        try:
            signed = datetime.strptime(raw, '%m/%d/%Y %I:%M %p')
            if timezone.is_naive(signed):
                signed = timezone.make_aware(signed, timezone.get_current_timezone())
        except (TypeError, ValueError):
            signed = None
    if signed is None:
        signed = signature.created_on
    if signed is None:
        return True
    return signed >= cutoff
