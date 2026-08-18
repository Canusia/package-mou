"""URLconf for the HS-admin tests.

The package cannot register its own URLs -- a host project includes them -- so
these tests must not depend on whether a given tenant has wired `mou_hs` up.
The include path is resolved at runtime because this package imports as `mou`
when pip-installed and `mou.mou` as an in-tree submodule.

The signed-mous page extends `cis/logged-base.html`, which unconditionally
resolves `logged_home`, `logout`, and `cis:footer` -- names normally supplied
by the host's root URLconf (`myce/urls.py`), not by `cis` itself registering
them. `cis` is already a hard dependency of this package (its models/views are
imported directly throughout mou), so this test URLconf defines those two
top-level names from `cis.views.home` and includes `cis.urls` for the `cis`
namespace, instead of depending on any host-specific urls module.

The page also renders `MOUSignature.as_pdf_url`, which reverses
`mou:signature_as_PDF` -- this package's own `mou.urls.mou`, included here
under its own `app_name='mou'` namespace.
"""
import importlib.util

from django.urls import include, path

from cis.views.home import logged_home, logout_view

_PKG = 'mou.mou' if importlib.util.find_spec('mou.mou') else 'mou'

urlpatterns = [
    path('logged_home/', logged_home, name='logged_home'),
    path('logout/', logout_view, name='logout'),
    path('ce/', include('cis.urls')),
    path('mou/', include(f'{_PKG}.urls.mou')),
    path('highschool_admin/mous/', include(f'{_PKG}.urls.highschool_admin')),
]
