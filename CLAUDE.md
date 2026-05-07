# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Manages Memorandums of Understanding with digital signature collection from school and district administrators. Supports multi-stage signature workflows, scheduled email distribution, and PDF generation.

## Key Components

### Models (`models.py`)
- **MOU** - Document with title, academic year, template text, CRON schedule
- **MOUSignator** - Signature template defining who signs and order (weight 1-4)
- **MOUSignature** - Actual signature records per school/signer combination
- **MOUNote** - Internal notes on MOUs

### Signator Roles
- `highschool_admin` - School administrator
- `district_admin` - District administrator
- `college_admin` - College administrator (weights 3-4)

### Signature Status Flow
`''` (not ready) → `'pending'` → `'signed'`

### URL Structure
- `/ce/highschools/mous/` - MOU management interface
- `/ce/highschools/mous/mou/<uuid>` - MOU detail/editor
- `/mou/sign_mou/<uuid>` - Public signing page (no login required)
- `/mou/mou_signature_as_pdf/<uuid>` - PDF download (no login required)

## Template Shortcodes

Use in `mou_text` field:
- `{{highschool_name}}`, `{{highschool_ceeb}}`, `{{academic_year}}`
- `{{teacher_list}}`, `{{choice_teacher_list}}`, `{{pathways_teacher_list}}`
- `{{course_list}}`, `{{choice_course_list}}`, `{{pathways_course_list}}`, `{{facilitator_course_list}}`, `{{future_course_list}}`
- `{{role_<attr>_<Position_Name>}}` — looks up the `HSAdministratorPosition` for this MOU's highschool whose `position.name` matches `<Position_Name>` (case-insensitive, underscores → spaces) and renders the named user attribute. `<attr>` ∈ `first_name`, `last_name`, `email`, `name` (= `"First Last"`). Empty string if no admin holds that position. Examples: `{{role_first_name_Academic_Principal}}`, `{{role_last_name_Dean_of_Guidance}}`, `{{role_email_Principal}}`.
- `{{signature_1}}` through `{{signature_4}}` - Signature boxes by weight

## Signature Workflow

1. Create MOU in draft, add MOUSignators (define signature chain)
2. Add schools via `add_highschools` - creates MOUSignature records
3. Mark MOU as 'ready', set CRON schedule and send window
4. `send_mou_emails` command sends to pending signers
5. Signers click link, fill form (POC info, signature), submit
6. On signature, `next_signator()` activates next signer in chain
7. Confirmation email sent to signer

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
| `is_active` | choice (`Yes`/`No`/`Debug`) | Master toggle. `Debug` routes pending-signature emails to `notify_address` only. |
| `notify_address` | comma-separated emails | Recipients in Debug mode and for roster-status notifications. |
| `teacher_course_status` | multi-select | Teacher cert statuses included in `{{teacher_list}}` and the choice/pathways variants. |
| `college_administrator_1` | user FK | Auto-attached as a weight-3 signator on every MOU. |
| `college_administrator_2` | user FK | Auto-attached as a weight-4 signator on every MOU. |
| `email_subject` / `email_message` | text / HTML | "Pending Signature" email. Supports `{{highschool_name}}`, `{{role}}`, `{{signator_firstname}}`, `{{signature_lastname}}`, `{{mou_title}}`, `{{signature_url}}`. |
| `signed_email_subject` / `signed_email_message` | text / HTML | "Signature Received" email. Supports the same variables plus `{{mou_download_link}}`. |
| `available_shortcodes` | multi-select | Allowlist of shortcodes substituted in `mou_text`. Unchecked shortcodes render as empty strings. The `role_lookup` choice covers the entire `{{role_<attr>_<Position>}}` family. |
| `future_course_list_template` | HTML | Django-template HTML used by `{{future_course_list}}`. Receives `courses` (FutureCourse queryset). Leave blank to use the bundled `mou/templates/future_section_courses.html`. |

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
