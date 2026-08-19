# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Manages Memorandums of Understanding with digital signature collection from school and district administrators. Supports multi-stage signature workflows, scheduled email distribution, and PDF generation.

## Key Components

### Models (`models.py`)
- **MOU** - Document with title, academic year, template text, CRON schedule. `manager` (CustomUser FK, optional) — primary contact for change-request notifications.
- **MOUSignator** - Signature template defining who signs and order (weight 1..`max_signator_weight`, default 8)
- **MOUSignature** - Actual signature records per school/signer combination
- **MOUNote** - Internal notes on MOUs

### Signator Roles
- `highschool_admin` - School administrator
- `district_admin` - District administrator
- `college_admin` - College administrator (weights 3-4)

### Signature Status Flow
`''` (not ready) → `'next'` (their turn, not yet emailed) → `'pending'` (emailed) → `'signed'`

A signer may instead submit a **change request** from the sign page, which moves the record to `'changes_requested'` and pauses the chain (no `next_signator()` call). An admin then either edits the MOU and uses the existing `change_signature_status` bulk action to flip the row back to `'pending'`, or leaves it as a record of why the school declined.

### URL Structure
- `/ce/highschools/mous/` - MOU management interface
- `/ce/highschools/mous/mou/<uuid>` - MOU detail/editor
- `/ce/highschools/mous/mou/do_bulk_action` - string-dispatch endpoint for the signator / signature / highschool **table** actions (`add_signator`, `edit_mou_signator`, `delete_signator`, `delete_signature`, `add_highschools`, `get_signature_link`, `send_signature_link`, `change_signature_status`) — see `do_bulk_action(request)` in `views.py`
- `/ce/highschools/mous/mou/actions` - `ActionRegistry` dispatch endpoint for the MOU-detail **record** actions (see below)
- `/mou/sign_mou/<uuid>` - Public signing page (no login required)
- `/mou/mou_signature_as_pdf/<uuid>` - PDF download (no login required)

## Detail-Page Actions (ActionRegistry)

The MOU-detail page's **Actions ▾** dropdown uses the shared
`myce.component_registry.ActionRegistry` pattern (same as the student / course /
term detail pages — `cis/templates/cis/students/detail.html` is the reference).
Don't confuse this with the legacy string-dispatch `do_bulk_action` function in
`views.py`, which still handles the signator/signature/highschool DataTable
actions — only the *record-level* MOU actions (duplicate, delete) live in the
registry.

**Wiring:**
- `mou/actions.py` — `mou_actions = ActionRegistry(OrderedDict({'general': …, 'danger': …}))`. Groups are pre-declared to control dropdown order.
- `mou/views.py` — handlers register via `@mou_actions.action('general'|'danger', label=…, icon=…, scope=['detail'], slug=…, confirm=…)`. Currently `duplicate_mou` (`general`, `slug='duplicate_mou'`) and `delete_mou` (`danger`, `slug='delete_mou'`, refuses MOUs whose `status == 'ready'`). Each reads `request.POST.getlist('ids[]')` (first id = the record) and returns an **envelope** dict (see below).
- `mou/views.py` — `mou_action_dispatch(request)` is `@user_passes_test(user_has_cis_role, …)` and just does `return mou_actions.dispatch(request, request.POST.get('action'))`. Wired at `mou_ce:actions` (`mou/urls/ce.py`). `dispatch` itself returns a `400 {'outcome':'alert', …}` for an unknown slug and a `403` if a per-action `permission` callable rejects the user.
- `mou(request, record_id)` view — passes `'detail_actions': mou_actions.for_scope('detail', request.user)` to the template.
- `mou/templates/mou/mou.html` — renders the dropdown by iterating `detail_actions.items` → `group.actions.items`; each item's `onclick` does `{% if action.confirm %}if(!confirm('{{ action.confirm }}'))return false;{% endif %}ActionRegistry.doAction('{% url 'mou_ce:actions' %}', '{{ slug }}', '{{ record.id }}');return false;`. `ActionRegistry.doAction` (from `staticfiles/js/action_registry.js`, loaded by `cis/logged-base.html`) POSTs `{action: slug, 'ids[]': [recordId]}`.

**Response envelope** (what handlers return; consumed by `action_registry.js`):
- `{'outcome': 'alert', 'status': 'success'|'error', 'title': …, 'message': …}` — show a SweetAlert.
- `{'outcome': 'call', 'fn': '<window fn name>', 'args': {…}}` — invoke a JS function on `window`. The MOU handlers use `'fn': 'mouGoTo'` — a small helper in `mou.html` that shows a SweetAlert (from `args.title/message/status`) then sets `location.href = args.url`. (Other outcomes the framework supports: `'modal'` (load HTML into `#bulk_modal_content`), `'open'` (new tab), `'poll'`.)

**Adding a detail-page action:** write a handler in `mou/views.py` decorated with `@mou_actions.action('general'|'danger', label=…, icon=…, scope=['detail'], slug=…, confirm=…)` that returns an envelope dict — the dropdown picks it up automatically; no template or URL change needed. For per-record permission checks pass `permission=<callable taking user>`. For a form-driven action use `method='form'` and return `{'outcome':'modal', 'html': render_crispy_form(...)}` (see `cis/views/student.py` for examples).

## Template Shortcodes

Use in `mou_text` field:
- `{{highschool_name}}`, `{{highschool_ceeb}}`, `{{academic_year}}`
- `{{teacher_list}}`, `{{choice_teacher_list}}`, `{{pathways_teacher_list}}`
- `{{course_list}}`, `{{choice_course_list}}`, `{{pathways_course_list}}`, `{{facilitator_course_list}}`, `{{future_course_list}}`
- `{{role_<attr>_<Position_Name>}}` — looks up the `HSAdministratorPosition` for this MOU's highschool whose `position.name` matches `<Position_Name>` (case-insensitive, underscores → spaces) and renders the named user attribute. `<attr>` ∈ `first_name`, `last_name`, `email`, `name` (= `"First Last"`). Empty string if no admin holds that position. Examples: `{{role_first_name_Academic_Principal}}`, `{{role_last_name_Dean_of_Guidance}}`, `{{role_email_Principal}}`.
- `{{signature_1}}` … `{{signature_N}}` - Signature boxes by weight, where N is `max_signator_weight` (default 8). Exempt from the `available_shortcodes` gate, so raising the chain length never blanks them on a tenant whose saved list predates the change.

## Signature Workflow

1. Create MOU in draft, add MOUSignators (define signature chain)
2. Add schools via `add_highschools` - creates MOUSignature records
3. Mark MOU as 'ready', set CRON schedule and send window
4. `send_mou_emails` command sends to pending signers
5. Signers click link, fill form (POC info, signature), submit
6. On signature, `next_signator()` activates next signer in chain
7. Confirmation email sent to signer

## Change Request Flow

1. Signer opens public sign page.
2. Instead of signing, clicks **Request Changes Instead**, enters a comment, submits.
3. View `sign_mou` (`mou/views.py`) routes POSTs with `action=request_changes` through `MOURequestChangesForm` (`mou/forms.py`).
4. Form sets `MOUSignature.status='changes_requested'`, stores `meta.change_request_comment` + `meta.change_requested_on`, creates an audit `MOUNote` (`meta.type='change_request'`), and calls `signature.send_change_request_notification()`.
5. Email is sent to `MOU.manager.email` if set; otherwise to the comma-separated `notify_address` setting.
6. To re-open for signing, an admin uses the existing `change_signature_status` bulk action to flip the row back to `pending`. The standard pending-notification email then re-invites the signer.

## Commands

```bash
python manage.py send_mou_emails  # Process scheduled MOUs (run via cron)
```

`send_mou_emails` is auto-registered to run every 5 minutes via the host
`CronTab` table. The mou app's `post_migrate` signal inserts a row
(`command='send_mou_emails'`, `cron='*/5 * * * *'`) on first migrate; the
host's `cis/management/commands/cron_jobs.py` iterates `CronTab` and
dispatches it. No manual edit to `cron_jobs.py` is required. Edit the row
(via Django admin or shell) to change the polling cadence; per-MOU send
timing is independent and controlled by `MOU.cron`.

## Configuration

Configurator class: `mou.settings.email_settings.email_settings`. Stored
under `cis.Setting(key='mou.settings.email_settings')` as a JSON value.
Edit via the standard MyCE Settings UI (`/ce/settings/`, look for
"MOU Notifications").

### Fields

| Field | Type | Purpose |
|---|---|---|
| `is_active` | choice (`Yes`/`No`/`Debug`) | Master toggle for **all** MOU email. `Debug` routes to `notify_address` only; `No` sends nothing. Decorative before v0.0.8 — migration `0006` sets existing tenants to `Yes` so upgrading does not silently redirect live mail. |
| `notify_address` | comma-separated emails | Recipients in Debug mode and for roster-status notifications. |
| `teacher_course_status` | multi-select | Teacher cert statuses included in `{{teacher_list}}` and the choice/pathways variants. |
| `college_administrator_1` | user FK | Auto-attached as a weight-3 signator on every MOU. |
| `college_administrator_2` | user FK | Auto-attached as a weight-4 signator on every MOU. |
| `email_subject` / `email_message` | text / HTML | "Pending Signature" email. Supports `{{highschool_name}}`, `{{role}}`, `{{signator_firstname}}`, `{{signature_lastname}}`, `{{mou_title}}`, `{{signature_url}}`. |
| `signed_email_subject` / `signed_email_message` | text / HTML | "Signature Received" email. Supports the same variables plus `{{mou_download_link}}`. |
| `change_request_email_subject` / `change_request_email_message` | text / HTML | "Change Requested" email sent to `MOU.manager` (fallback: `notify_address`) when a signer submits a change request. Supports `{{highschool_name}}`, `{{signator_firstname}}`, `{{signator_lastname}}`, `{{mou_title}}`, `{{comment}}`, `{{mou_url}}`, `{{signature_url}}`. |
| `available_shortcodes` | multi-select | Allowlist of shortcodes substituted in `mou_text`. Unchecked shortcodes render as empty strings. The `role_lookup` choice covers the entire `{{role_<attr>_<Position>}}` family. |
| `future_course_list_template` | HTML | Django-template HTML used by `{{future_course_list}}`. Receives `courses` (FutureCourse queryset). Leave blank to use the bundled `mou/templates/future_section_courses.html`. |
| `default_cron` | text | Prefills the schedule box when finalizing an MOU that has none. Read only in `MOUEditorForm.__init__`; never consulted by `send_mou_emails`, which uses `MOU.cron`. |
| `max_signator_weight` | int (default 8) | Length of the signing chain, and how many `{{signature_N}}` shortcodes render. |
| `allow_college_admin_any_weight` | choice (`Yes`/`No`) | `No` restricts college signators to weights 3-4. |
| `vacant_role_policy` | choice | `skip_silent` / `skip_and_notify` / `hold_school` — what happens when adding a school where nobody holds a title in the signing order. |
| `allow_change_requests` | choice (`Yes`/`No`) | Shows the "request changes" control on the sign page. |
| `pdf_download` | choice | `before_and_after` / `after_only` / `never` on the signing page. |
| `hs_admin_can_view_signed_mous` | choice (`Yes`/`No`) | Shows the HS-admin Signed MOUs page. **No effect unless the host includes `mou.urls.highschool_admin`.** |
| `retention_years` | int (default 6) | Hides signed agreements older than this from the HS-admin list; `0` = never hide. |
| `reminder_email_subject` / `reminder_email_message` | text / HTML | Used from the second send onward; blank reuses the main pending-signature copy. |
| `heads_up_email` / `heads_up_include_college` | choice (`Yes`/`No`) | One-time FYI to later signers when a school's first request goes out, without a signing link. |
| `heads_up_email_subject` / `heads_up_email_message` | text / HTML | Heads-up wording. Both must be non-empty or nothing is sent. |

### How to configure

1. Run `python manage.py register_settings` once after install (or after pulling new fields). This scans each app's `CONFIGURATORS` list and creates a `SettingRecord` for `email_settings` if it doesn't exist yet. First registration calls `email_settings.install()`, which seeds defaults — including `available_shortcodes` populated with all 15 shortcode keys (so existing MOUs render unchanged).
2. Open `/ce/settings/` in the CE portal. Find the **MOU Notifications** category and click into it.
3. Edit any of the fields above and **Save**. Values are persisted into `cis.Setting.value` (JSONField); change history is tracked via `django-simple-history` and visible in the Change Log tab on the Setting detail page.
4. To customize the `{{future_course_list}}` rendering: copy the contents of `mou/templates/future_section_courses.html` into the **`{{future_course_list}}` HTML Template** textarea as a starting point, then edit. The HTML is validated as a Django template at save time (`validate_html_short_code`) so syntax errors are caught early. The `courses` variable is the FutureCourse queryset (filtered by the MOU's highschool + academic year, `submitted_on__isnull=False`).
5. To restrict which shortcodes admins can use in `mou_text`: uncheck the unwanted entries under **Available Shortcodes**. Disallowed shortcodes render as empty strings; existing `mou_text` is not validated retroactively, so a previously authored shortcode silently disappears at render time.

### Reading the setting from code

```python
from mou.settings.email_settings import email_settings, AVAILABLE_SHORTCODES

cfg = email_settings.from_db()  # → dict, or {} if not yet saved
allowed = cfg.get('available_shortcodes')  # may be None on fresh install
```

`AVAILABLE_SHORTCODES` is the canonical list (key, label) pairs. It's the single source of truth for both the form choices and the runtime gate in `MOUSignature.mou_text`.

## Reports
- `signature_link_export` - CSV of pending signatures with URLs
- `mou_pdf_export` - ZIP of signed MOUs as PDFs

## Integration

- Links to `cis.AcademicYear`, `cis.HighSchool`, `cis.CustomUser`
- Queries `cis.TeacherCourseCertificate` for teacher lists
- Queries `future_sections.FutureCourse` for course lists (use the conditional `future_sections.future_sections.models` import where the editable submodule is in use; **do not import from `cis.models.future_sections`** — that module is being phased out)
- PDF generation via `pdfkit`
