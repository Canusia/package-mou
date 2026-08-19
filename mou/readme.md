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

## 5. Settings added by the flexible signature workflow

All of these live in the single `mou` settings record (CE → Settings → MOU) and
are read at use time, so a change takes effect on the next action — no restart,
no redeploy. Defaults are what `install()` seeds on a fresh tenant.

### Sending

| Setting | Default | What it does |
|---|---|---|
| **Enabled** (`is_active`) | `Debug` | The master switch for every MOU email. `Yes` mails the real signers. `Debug` sends them to the notification list instead. `No` sends nothing. |
| **Notification list** (`notify_address`) | *(empty)* | Comma-separated staff addresses. Receives everything while Enabled is `Debug`, plus vacant-title reports and any MOU with no manager. |
| **Default reminder schedule for new MOUs** (`default_cron`) | *(empty)* | Prefills the schedule box when finalizing an MOU that has none. Never changes an MOU that is already scheduled. |

> **`is_active` is load-bearing as of v0.0.8.** Earlier releases stored it but
> never read it, so mail always went to real signers. Migration
> `0006_is_active_preserve_live_sending` sets existing tenants to `Yes` so
> upgrading does not silently redirect live mail. New installs still default to
> `Debug`.

### The signing chain

| Setting | Default | What it does |
|---|---|---|
| **Maximum number of signers** (`max_signator_weight`) | `8` | How many steps the signing order can have, and how many `{{signature_N}}` shortcodes render. |
| **College staff can sign at any step** (`allow_college_admin_any_weight`) | `Yes` | `No` restricts college signators to steps 3 and 4. |
| **If a required title is empty** (`vacant_role_policy`) | `Skip empty titles (no email)` | What to do when adding a school where nobody holds one of the titles in the signing order. See below. |
| **Let signers request changes** (`allow_change_requests`) | `Yes` | Shows the "request changes" control on the signing page. A change request parks that school's chain until CE resolves it. |

**`vacant_role_policy` in detail.** Applies only when you add schools to an MOU.

* **Skip empty titles (no email)** — the school is added with signature rows for
  the roles that resolved; the empty step gets no row at all. The on-screen
  result still lists what was skipped.
* **Skip empty titles and email the notification list** — same, plus one summary
  email to the MOU manager and the notification list. Subject to `is_active`,
  so nothing is sent when that is `No`.
* **Do not add the school until every title is filled** — the school is skipped
  entirely, including roles that did resolve. Per school, not per batch: other
  schools in the same submission are still added.

Both skip options leave a permanent gap — the missing step never joins the chain,
and the MOU can be signed to completion without it. Re-adding the school after
the title is filled creates only the missing rows.

### Reminders and heads-up mail

| Setting | Default | What it does |
|---|---|---|
| **Reminder Email Subject / Reminder Email** (`reminder_email_subject`, `reminder_email_message`) | *(empty)* | Used from the second send onward. The first request always uses the main email copy; leave these blank to reuse it for reminders too. |
| **Send a heads-up to later signers** (`heads_up_email`) | `No` | When a school's first signing request goes out, notify the later signers once, without a signing link. |
| **Include college staff in the heads-up** (`heads_up_include_college`) | `No` | Whether college signators are included in that heads-up. |
| **Heads-up email subject / Heads-up email** (`heads_up_email_subject`, `heads_up_email_message`) | *(seeded copy)* | The heads-up wording. Both must be non-empty or no heads-up is sent. |

### The signing page and the HS-admin view

| Setting | Default | What it does |
|---|---|---|
| **Let people download a PDF while signing** (`pdf_download`) | `Only after they have signed` | Also allows before-and-after, or never. |
| **High school admins can view signed agreements** (`hs_admin_can_view_signed_mous`) | `No` | Shows the HS-admin "Signed MOUs" page. **Requires the `mou.urls.highschool_admin` route from step 2** — without it the setting has no effect and the page 404s. |
| **How long signed agreements stay listed (years)** (`retention_years`) | `6` | Hides signed agreements older than this from the HS-admin list. `0` means never hide. |
| **Available shortcodes** (`available_shortcodes`) | *(all)* | Which shortcodes may be used in MOU body text. `{{signature_N}}` is exempt — signature blocks always render, so raising the signer count never blanks them on a tenant whose saved list predates the change. |

