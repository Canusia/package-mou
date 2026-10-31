# Changelog

Releases are tagged on `Canusia/package-mou` and consumed by each tenant through the
`git+https://…@<tag>` pin in `webapp/requirements.txt`.

## Unreleased

### Fixed

* **Tenants with an in-repo `cis`, or no campus, can install and run the
  package again (#2).** `myce_cis` moved from the install requirements to the
  optional `campus` extra (`myce_mou[campus]`) in both `pyproject.toml` and
  `setup.cfg`. Every package-cis / host-only import now goes through
  `mou/compat.py`, which checks with `importlib.util.find_spec`: without
  `cis.highschool_scope` the Add High School(s) picker and modal list every
  Active school (status shown is the school's own), and adding schools there
  creates their signatures; without `cis.services.tenant_services` there are
  no list-shortcode overrides; without `myce.component_registry` the
  detail-page actions use a vendored `ActionRegistry` (`mou/_actions.py`).
* **The modal's campus status no longer assumes `HighSchoolCampus` exists.**
  It is used only when cis has that model and the campus is real (has a pk);
  otherwise the school's own status is shown. Hosts with a stand-in
  `cis.highschool_scope` (embry) can drop their non-model `HighSchoolCampus`
  shim once they run this release.
* **The Duplicate/Delete MOU menu works on hosts without
  `action_registry.js`.** The package ships `mou/js/action_registry.js` and
  `mou.html` loads it only when `window.ActionRegistry` is missing.
* **Signatures are seeded by Add High School(s), not by finalizing.** Single-campus
  deployments with no campus, and a cis without campus scoping, are offered (and so
  seed) every Active school; multi-campus with no campus is offered none.
  `MOU.initialize_signatures()` follows the same rule but is unused: its only call
  site has been commented out since the package began, so finalizing seeds nothing.

### Security

* **CE-only MOU endpoints.** `do_bulk_action` (add/delete signators and
  signatures, change status, copy/send signing links, add schools) and the
  three API viewsets (`api/mous`, `api/mou_signators`, `api/mou_signatures`)
  now require the CE role; before, any logged-in user (a student, another
  school's HS admin) could list every signature id, and so every signing URL,
  or delete signatures. In multi-campus mode they only see and act on MOUs of
  the current campus's academic years (plus campus-less years). The public
  `/mou/sign_mou/<uuid>` page is unchanged.

### Changed

* `requires-python` is now `>=3.11` (pyproject and setup.cfg); the tests use
  `tomllib`. Tenant images run 3.12.

## v0.0.10 — 2026-10-02

Reconstructed from git: tag `v0.0.10` peels to e4631ea, one commit after the
`chore(release): v0.0.10` metadata bump (64462ee).

### Added

* **Campus-scoped school pickers.** The Add High School(s) picker offers only
  schools with an Active `HighSchoolCampus` link to the current campus; a
  posted id for another campus's school fails validation (0001411). Required
  `myce_cis>=0.1.7a` (now optional, see Unreleased).

### Fixed

* **Signature seeding is campus-scoped**, and the Add High School(s) modal shows
  each school's status on the current campus (e4631ea).

## v0.0.9 — 2026-09-28

### Fixed

* **`install()` no longer overwrites a customised setting** (package-cis #51).
  Defaults are seeded through `Setting.install_defaults()` (package-cis
  v0.0.39+), which only adds missing keys (f1d9284).

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
