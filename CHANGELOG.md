# Changelog

Releases are tagged on `Canusia/package-mou` and consumed by each tenant through the
`git+https://…@<tag>` pin in `webapp/requirements.txt`.

## v0.0.8 — 2026-08-19

### Added

* **Tenant overrides for what the list shortcodes select.** All nine list
  shortcodes (`{{teacher_list}}`, `{{course_list}}`, `{{future_course_list}}`, …)
  hardcoded one deployment's notion of which records belong in an MOU — one of
  them cites a specific tenant's workbook in its own docstring. Each now
  consults an optional `services/mou.py` override, receiving the package's
  default queryset so a tenant can refine rather than restate it. Defining
  nothing keeps current behaviour exactly. See readme section 6.

### Fixed

* **Upgrading no longer silently stops live email.** `is_active` was decorative before
  this release and `install()` seeds it to `Debug`, so promoting it to the master switch
  redirected every existing tenant's MOU mail to `notify_address`. A migration sets
  existing rows to `Yes`, preserving prior behaviour; new installs still default to
  `Debug`. The `send_mou_emails` summary now counts sends that actually happened, not
  post-send status.
* **An open change request no longer lets a later signer sign out of order.**
  `MOU.current_unsigned_signatures` excluded `signed` but not `changes_requested`, so the
  search for a school's lowest outstanding signer skipped past a blocked step: a later
  signer was marked Next Up and emailed a signing link while an earlier signer's change
  request was still open. This contradicted `MOUSignature.is_next_in_chain()`.
* **Signing order is enforced server-side.** `sign_mou`'s POST handler checked nothing;
  ordering lived only in the template, so an emailed signing URL could be replayed to sign
  out of order or overwrite an existing signature.
* **"Get Signature Link" no longer reports a send that did not happen.** Opening the modal
  stamped `meta['notified_on']`, which the signatures table renders as "Sent &lt;date&gt;"
  even though no email was sent.
* **Signature shortcodes survive a stale settings row.** `signature_N` is generated from
  the `max_signator_weight` setting while `AVAILABLE_SHORTCODES` is built at import from a
  constant, so any tenant whose saved `available_shortcodes` predated a chain-length change
  lost those signature blocks silently. Signature slots are now exempt from the choice
  gate.
* **Switching an existing signator to College Admin clears the stale `HSPosition` UUID**
  left in `role`, which previously could point at a role type the signator no longer holds.
* **The vacant-role notification email renders as formatted HTML again, not literal
  markup.** `cis/email.html` renders its `{{message}}` without `|safe`, and the vacant-role
  body was built as a plain `str`, so Django's autoescaping ran over the entire body —
  including the email's own `<p>`/`<ul>`/`<li>` tags, which CE staff saw as literal source
  text instead of a formatted list. The body is now built with `format_html` /
  `format_html_join`, which escapes each interpolated value exactly once and returns a
  `SafeString`, so the outer template no longer re-escapes the markup.
* **The packaged HS-admin MOU tests no longer depend on host URL wiring.** The package
  ships `mou/urls/highschool_admin.py` but cannot register it itself; the required
  `include()` is now documented in the readme so hosts wire it explicitly.

### Changed

* **Four course shortcodes now read a different table.** `{{pathways_course_list}}`,
  `{{choice_course_list}}`, `{{facilitator_course_list}}` and `{{course_list}}` imported
  `FutureCourse` from the legacy `cis.models.future_sections` module (`cis_futurecourse`
  table); they now import it from the `future_sections` app (`future_sections_futurecourse`
  table), matching what `{{future_course_list}}` already read and what the host repo's
  CLAUDE.md requires. **This is not a same-table refactor.** On any tenant that still has
  rows in the legacy `cis_futurecourse` table, these four shortcodes will render different
  courses after upgrading — and because `MOUSignature.mou_text` is computed live on every
  render, with no snapshot taken at signing time, this changes the rendered body of
  agreements that are already signed, not just new ones. The markup also changes: the
  `future_sections` app's model exposes `section_display_html` (admin-configurable,
  pre-formatted section lines), which the legacy model does not have. **Before upgrading,
  compare row counts between `cis_futurecourse` and `future_sections_futurecourse` for your
  tenant** to know whether you're affected.
* **Dropped the two default send-window settings.** `default_send_after_mmdd` and
  `default_send_until_mmdd` prefilled the "Schedule to Send Starting On / Until"
  boxes when finalizing an MOU. They stamped the *current* year onto the stored
  month/day, so an MOU finalized late in the year prefilled a window that had
  already closed — and because the prefill only fired on a blank field, saving the
  form for any unrelated reason wrote that stale window onto the record silently.
  A send window is per-agreement; it is now always chosen deliberately. The
  per-MOU fields (`MOU.send_on_after` / `MOU.send_until`) are unchanged, and no
  existing schedule is affected.
* **Relabelled `default_cron`** to "Default reminder schedule for new MOUs", with
  help text stating that it only prefills an unscheduled MOU and never reschedules
  one that is already sending. The old label read like a live control over
  reminder timing; it is not — `send_mou_emails` reads `MOU.cron`.

* **Version metadata now tracks the tag.** `setup.cfg` read `0.1` and `pyproject.toml` read
  `0.0.7` — disagreeing with each other and with reality. pip keys upgrades off the version
  string, so a tenant bumping its `git+…@tag` pin without this fix would have kept the old
  code with no error, while newly-added migrations may already have been applied, leaving
  the schema ahead of the code.
