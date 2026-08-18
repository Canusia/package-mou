# MOU package install / wire-up

Steps to wire this app into a MyCE host project. Mirrors the
`invoice` / `instructor_app` submodule patterns.

## 1. Register the app

In `myce/settings.py` `INSTALLED_APPS`, use the conditional pattern so
the in-tree editable submodule (`mou.mou.apps.DevMOUConfig`) is picked
up when present and the pip-installed package (`mou.apps.MOUConfig`) is
used otherwise:

```python
'mou.mou.apps.DevMOUConfig'
if importlib.util.find_spec('mou.mou')
else 'mou.apps.MOUConfig',
```

## 2. Add the URL routes

In `myce/urls.py`:

```python
_mou = 'mou.mou' if importlib.util.find_spec('mou.mou') else 'mou'

urlpatterns += [
    path('mou/', include(f'{_mou}.urls.mou')),
    path('ce/highschools/mous/', include(f'{_mou}.urls.ce')),
    path('highschool_admin/mous/', include(f'{_mou}.urls.highschool_admin')),  # namespace: mou_hs
]
```

The CE prefix **must be `ce/highschools/mous/`** — `mou/views.py` and
`templates/mou/mou.html` hardcode that path for the DataTable AJAX URLs
(`/ce/highschools/mous/api/mou_signators?…`,
`/ce/highschools/mous/api/mou_signatures?…`) and the breadcrumb. Mounting
elsewhere will produce 404s on the MOU detail page.

## Host URL wiring

This package ships three URLconfs and registers none of them; the host
project includes the ones it wants. `mou/urls/__init__.py` is
intentionally empty. Without the `mou.urls.highschool_admin` line above,
the HS-admin "Signed MOUs" page is unreachable, and the
`hs_admin_can_view_signed_mous` setting has no effect. This is true on
every tenant today — `myce/urls.py` currently includes only
`mou.urls.ce` and `mou.urls.mou`.

## 3. Add the staticfiles dir

In `myce/settings.py` `STATICFILES_DIRS`, mirror the conditional from
step 1:

```python
os.path.join(get_package_path("mou.mou"), 'staticfiles')
if importlib.util.find_spec('mou.mou')
else os.path.join(get_package_path("mou"), 'staticfiles') if get_package_path("mou") else None,
```

## 4. `send_mou_emails` cron entry

No manual step required. The mou app self-registers a `CronTab` row
(`command='send_mou_emails'`, `cron='*/5 * * * *'`) on `post_migrate`,
which the host project's existing `cis/management/commands/cron_jobs.py`
picks up automatically — that command already iterates
`CronTab.objects.all()` and dispatches each entry whose schedule fires
inside the current cron window.

You can change the polling cadence by editing the row in the admin or
shell. Per-MOU send schedules are independent (controlled by
`MOU.cron`); this row just determines how often the dispatcher checks
for MOUs that are due.
