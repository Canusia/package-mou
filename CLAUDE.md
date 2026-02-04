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
- `{{course_list}}`, `{{facilitator_course_list}}`
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

## Configuration

Via `email_settings` settings form:
- College administrators (weights 3 & 4)
- Teacher certificate status filter
- Email templates for pending notifications and confirmations
- Variables: `{{highschool_name}}`, `{{role}}`, `{{signator_firstname}}`, `{{signature_url}}`

## Reports
- `signature_link_export` - CSV of pending signatures with URLs
- `mou_pdf_export` - ZIP of signed MOUs as PDFs

## Integration

- Links to `cis.AcademicYear`, `cis.HighSchool`, `cis.CustomUser`
- Queries `cis.TeacherCourseCertificate` for teacher lists
- Queries `cis.FutureCourse`/`FutureSection` for course lists
- PDF generation via `pdfkit`
