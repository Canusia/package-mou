# MyCE — MOUs

A pip-installable Django app (`myce_mou` / `Canusia/package-mou`) for managing
Memorandums of Understanding with multi-stage digital signature collection,
scheduled email distribution, and PDF generation. Used by the MyCE (My
Concurrent Enrollment) platform; depends on the host project's `cis` app
(users, schools, districts, academic years, teacher certs, `future_sections`)
and on `myce.component_registry` for the CE-portal detail-page action dropdown.

## Editable-submodule pattern

Like the other MyCE feature packages, this app supports an in-tree editable
override: the host `settings.py` checks for a nested `mou.mou` package and uses
its `DevMOUConfig` if present, otherwise falls back to the installed package's
`MOUConfig`. Both configs resolve to the app label `mou` either way, so
signals, migrations, and `register_*` management commands behave identically in
both modes. When working in-tree, the `submod-migration-deps` and
`submod-package-manifest` skills apply before tagging a release.

## Setup

In the host project's `settings.py`:

- Add the app to `INSTALLED_APPS` (the editable-submodule shim does this
  conditionally; a plain install uses `'mou.apps.MOUConfig'`).
- Add the static dir: `os.path.join(get_package_path("mou"), 'staticfiles')`
  in `STATICFILES_DIRS` (skip if the editable `mou.mou` copy is in use and its
  dir is already covered).

In `myce/urls.py`:

- `path('ce/highschools/mous/', include('mou.urls.ce'))` — CE portal (`mou_ce`
  namespace).
- `path('mou/', include('mou.urls.mou'))` — the public (no-login) signing / PDF
  endpoints.

In **Settings → Misc → Menu**, add:

```json
{ "label": "MOUs", "name": "mous", "url": "mou_ce:all" }
```

After install (and after pulling new fields), run `python manage.py
register_settings` once — see [Configuration](#configuration).

## Key models (`models.py`)

- **MOU** — the document: `title`, `academic_year`, `mou_text` (template body,
  see [Template shortcodes](#template-shortcodes)), `cron` (per-MOU send
  schedule), `send_on_after` / `send_until` (send window), `status` (`draft` →
  `ready`), `meta` (POC / source-of-funds / tuition-manager fields).
  `MOU.duplicate(created_by)` clones an MOU and its signator chain into a fresh
  `draft` copy (titled `"Copy of …"`); it does **not** copy `MOUSignature` rows
  or attached highschools.
- **MOUSignator** — a signature-template row: who signs and in what order
  (`weight` 1–4), `role_type` (`highschool_admin` / `district_admin` /
  `college_admin`) and `role` (the position UUID).
- **MOUSignature** — the actual per-school/per-signer record. Status flow: `''`
  (not ready) → `'pending'` → `'signed'`. Renders the signed image into the
  document via the `{{signature_<weight>}}` shortcodes; shows *"Not yet signed"*
  until signed.
- **MOUNote** — internal notes on an MOU.

## Signature workflow

1. Create an MOU in `draft`; add `MOUSignator` rows (the signature chain). The
   configured `college_administrator_1` / `college_administrator_2` users are
   auto-attached as weight-3 / weight-4 signators when highschools are added.
2. Add schools (the `add_highschools` action) — creates `MOUSignature` rows for
   each school × signator.
3. Mark the MOU `ready` and set `cron` + the send window.
4. `send_mou_emails` (auto-registered to run every 5 min via the host
   `CronTab`) emails pending signers when an MOU's schedule fires inside the
   current poll window.
5. A signer opens their link (`/mou/sign_mou/<uuid>`, no login), fills the POC /
   signature form, submits.
6. On signing, `next_signator()` activates the next signer in the chain; a
   confirmation email goes to the signer.

## URLs

CE portal (`mou_ce`):

- `/ce/highschools/mous/` — MOU list.
- `/ce/highschools/mous/mou/<uuid>` — MOU detail / editor (template editor,
  signator table, signature table, the **Actions ▾** dropdown — see
  [Detail-page actions](#detail-page-actions)).
- `/ce/highschools/mous/mou/do_bulk_action` — string-dispatch endpoint for the
  signator / signature / highschool table actions (`add_signator`,
  `delete_signature`, `add_highschools`, `get_signature_link`,
  `send_signature_link`, `change_signature_status`, …).
- `/ce/highschools/mous/mou/actions` — `ActionRegistry` dispatch endpoint for
  the detail-page Actions dropdown (`duplicate_mou`, `delete_mou`).
- `/ce/highschools/mous/api/…` — DRF viewsets for the DataTables.

Public (`mou`):

- `/mou/sign_mou/<uuid>` — signing page (no login).
- `/mou/mou_signature_as_pdf/<uuid>` — signed-MOU PDF (no login).

## Detail-page actions

The CE MOU-detail page exposes record-level actions through the project's
`myce.component_registry.ActionRegistry` pattern — the same one used by the
student / course / term detail pages:

- `mou/actions.py` defines `mou_actions = ActionRegistry({'general': …,
  'danger': …})` (groups pre-declared to control dropdown order).
- Handlers register themselves with `@mou_actions.action('general'|'danger',
  label=…, icon=…, scope=['detail'], slug=…, confirm=…)` decorators in
  `mou/views.py` — currently `duplicate_mou` (group `general`) and `delete_mou`
  (group `danger`; refuses MOUs whose `status == 'ready'`).
- `mou_action_dispatch(request)` (wired at `mou_ce:actions`) calls
  `mou_actions.dispatch(request, request.POST.get('action'))`.
- The `mou` view passes `detail_actions = mou_actions.for_scope('detail',
  request.user)`; `mou.html` renders the **Actions ▾** dropdown from it, each
  item calling `ActionRegistry.doAction('{% url 'mou_ce:actions' %}', slug,
  record.id)` (the client helper in `staticfiles/js/action_registry.js`, loaded
  by `cis/logged-base.html`).
- Handlers return the standard envelope — `{'outcome': 'alert', …}` for
  messages/errors, or `{'outcome': 'call', 'fn': 'mouGoTo', 'args': {…}}` to
  navigate (`mouGoTo` is a small helper in `mou.html` that shows a SweetAlert
  then sets `location.href`).

To add a new detail-page action: write a handler in `mou/views.py` decorated
with `@mou_actions.action('general'|'danger', …, scope=['detail'])` returning an
envelope dict — that's it; the dropdown picks it up automatically.

## Template shortcodes

Use these in the `mou_text` field (allow-listed via **Available Shortcodes** in
the settings, see [Configuration](#configuration) — unchecked ones render as an
empty string):

- `{{highschool_name}}`, `{{highschool_ceeb}}`, `{{highschool_address1}}`,
  `{{highschool_city}}`, `{{highschool_state}}`, `{{highschool_zip}}`,
  `{{academic_year}}`
- `{{teacher_list}}`, `{{choice_teacher_list}}`, `{{pathways_teacher_list}}`
- `{{pathways_course_list}}`, `{{choice_course_list}}`,
  `{{facilitator_course_list}}`, `{{course_list}}`, `{{future_course_list}}`
- `{{role_<attr>_<Position_Name>}}` — looks up the `HSAdministratorPosition` for
  this MOU's highschool whose position name matches `<Position_Name>`
  (case-insensitive, underscores → spaces) and renders the named user
  attribute. `<attr>` ∈ `first_name` / `last_name` / `email` / `name`. Empty
  string if no admin holds that position. The single `role_lookup` allow-list
  entry enables the whole family. Examples:
  `{{role_first_name_Academic_Principal}}`, `{{role_email_Principal}}`.
- `{{signature_1}}` … `{{signature_4}}` — the signature box for each weight;
  renders the signed image once signed, otherwise *"Not yet signed"*.

## Configuration

Configurator: `mou.settings.email_settings.email_settings` — stored under
`cis.Setting(key='mou.settings.email_settings')` as a JSON value, edited via the
standard MyCE Settings UI (`/ce/settings/` → **MOU Notifications**).
`AVAILABLE_SHORTCODES` in that module is the single source of truth for the
shortcode allow-list (used both for the form choices and the runtime gate in
`MOUSignature.mou_text`).

Fields:

| Field | Type | Purpose |
|---|---|---|
| `is_active` | `Yes` / `No` / `Debug` | Master toggle. `Debug` routes pending-signature emails to `notify_address` only. |
| `notify_address` | comma-separated emails | Recipients in Debug mode and for roster-status notifications. |
| `teacher_course_status` | multi-select | Teacher-cert statuses included in `{{teacher_list}}` and the choice/pathways variants. |
| `available_shortcodes` | multi-select | Allow-list of shortcodes substituted in `mou_text`; `role_lookup` covers the whole `{{role_*}}` family. Unchecked → empty string. |
| `custom_css` | CSS text | CSS injected into the rendered MOU document / sign page / PDF. |
| `future_course_list_template` | Django-template HTML | Markup for `{{future_course_list}}`; receives `courses` (a FutureCourse queryset). Blank → the bundled `mou/templates/future_section_courses.html`. Validated as a Django template at save time. |
| `college_administrator_1` / `college_administrator_2` | user FKs | Auto-attached as weight-3 / weight-4 signators on every MOU. |
| `email_subject` / `email_message` | text / HTML | "Pending Signature" email. Supports `{{highschool_name}}`, `{{role}}`, `{{signator_firstname}}`, `{{signature_lastname}}`, `{{mou_title}}`, `{{signature_url}}`. |
| `signed_email_subject` / `signed_email_message` | text / HTML | "Signature Received" email. Same variables plus `{{mou_download_link}}`. |

How to configure:

1. Run `python manage.py register_settings` once after install / after pulling
   new fields. The first registration calls `email_settings.install()`, which
   seeds defaults — including `available_shortcodes` populated with *every*
   shortcode key, so existing MOUs render unchanged.
2. Open `/ce/settings/` → **MOU Notifications** → edit → **Save**. Values
   persist into `cis.Setting.value` (JSONField); change history is tracked via
   `django-simple-history` (Change Log tab on the Setting detail page).
3. To customize `{{future_course_list}}`: copy
   `mou/templates/future_section_courses.html` into the **Template** textarea as
   a starting point and edit. `courses` is the FutureCourse queryset filtered by
   the MOU's highschool + academic year, `submitted_on__isnull=False`.
4. To restrict which shortcodes admins may use: uncheck the unwanted entries
   under **Available Shortcodes**. Existing `mou_text` is not re-validated, so a
   previously authored disallowed shortcode silently renders empty.

Reading the setting from code:

```python
from mou.settings.email_settings import email_settings, AVAILABLE_SHORTCODES
cfg = email_settings.from_db()              # → dict, or {} if not yet saved
allowed = cfg.get('available_shortcodes')   # may be None on a fresh install
```

## Commands

- `python manage.py send_mou_emails` — processes scheduled MOUs (sends to
  pending signers / confirmation emails). Auto-registered to run every 5 min via
  a `cis.CronTab` row inserted by this app's `post_migrate` signal; the host's
  `cis/management/commands/cron_jobs.py` dispatches it. Edit the `CronTab` row to
  change the polling cadence; per-MOU send timing is controlled by `MOU.cron`
  independently.

## Reports

- `signature_link_export` — CSV of pending signatures with their signing URLs.
- `mou_pdf_export` — ZIP of signed MOUs as PDFs.

PDF generation uses `pdfkit` (wkhtmltopdf).

## Tests

`python manage.py test mou.mou.tests` (run inside the app's container; the
package imports as `mou.mou` in editable mode, `mou` when installed — the tests
use a `try/except ImportError` shim for both).
