// Vendored copy of the host's staticfiles/js/action_registry.js (review I-3).
// mou/templates/mou/mou.html loads it only when window.ActionRegistry is
// missing (embry, rmu). Keep the code below identical to the original;
// mou/tests/test_vendored_registry_drift.py compares them when the host has one.
/**
 * ActionRegistry — client-side dispatch for server-side ActionRegistry actions.
 *
 * Entry points:
 *   ActionRegistry.doAction(url, action, recordId)   — detail pages
 *   ActionRegistry.doBulkAction(url, action, dt)      — index pages (DataTables)
 *
 * Server response envelope:
 *   { outcome: 'alert',  status, title, message }
 *   { outcome: 'modal',  html }
 *   { outcome: 'call',   fn, args }
 *   { outcome: 'open',   url }                        — new browser tab
 *   { outcome: 'redirect', url }                      — same tab; the target page is
 *                                                       responsible for offering a way back
 *   { outcome: 'poll',   poll_url, title, message }  — polls GET poll_url every 2s until SUCCEEDED/FAILED
 */
var ActionRegistry = (function () {
    'use strict';

    var MODAL_ID = 'modal-bulk_actions';
    var MODAL_CONTENT_ID = 'bulk_modal_content';

    function init() {
        var modal = document.getElementById(MODAL_ID);
        var content = document.getElementById(MODAL_CONTENT_ID);
        if (!modal || !content) {
            throw new Error('ActionRegistry.init: #' + MODAL_ID + ' or #' + MODAL_CONTENT_ID + ' not found in DOM.');
        }
        $(document).on('submit', 'form.frm_ajax', function (event) {
            // Pages that also load cis's ajax_form.js (e.g. the instructor
            // class page) bind their own frm_ajax handler first; it has
            // already posted the form, so posting it again here would save
            // twice.
            if (event.isDefaultPrevented()) { return; }
            event.preventDefault();
            _handleFormSubmit($(this));
        });
    }

    function doAction(url, action, recordId) {
        var data = { action: action, 'ids[]': [recordId] };
        _post(url, data);
    }

    function doBulkAction(url, action, dt) {
        if (!dt.rows('.selected').any()) {
            alert('Please select a row and try again.');
            return;
        }
        var ids = [];
        dt.rows({ selected: true }).every(function () {
            ids.push(this.id());
        });
        _post(url, { action: action, 'ids[]': ids });
    }

    function _post(url, data) {
        $.blockUI();
        $.ajax({
            type: 'POST',
            url: url,
            data: data,
            headers: { 'X-CSRFToken': _csrfToken() },
            success: function (response) {
                if (response.outcome !== 'poll') { $.unblockUI(); }
                _handleResponse(response);
            },
            error: function (xhr) {
                $.unblockUI();
                var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'An unexpected error occurred.';
                swal({ title: 'Error', text: msg, icon: 'error' });
            }
        });
    }

    function _handleResponse(response) {
        var outcome = response.outcome;
        if (outcome === undefined && response.message !== undefined) {
            _handleAjaxFormResponse(response);
        } else if (outcome === 'alert') {
            var span = document.createElement('span');
            span.innerHTML = response.message || '';
            swal({ title: response.title || '', content: span, icon: response.status || 'info' });
        } else if (outcome === 'modal') {
            $('#' + MODAL_CONTENT_ID).html(response.html);
            $('#' + MODAL_ID).modal('show');
        } else if (outcome === 'call') {
            var fn = window[response.fn];
            if (typeof fn !== 'function') {
                throw new Error('ActionRegistry: "' + response.fn + '" is not defined on window.');
            }
            fn(response.args || {});
        } else if (outcome === 'open') {
            window.open(response.url, '_blank');
        } else if (outcome === 'redirect') {
            // Same-tab navigation. Use assign(), not replace(), so the
            // browser's own Back button still returns to the record the
            // action was launched from.
            window.location.assign(response.url);
        } else if (outcome === 'poll') {
            _startPolling(response);
        } else {
            throw new Error('ActionRegistry: unknown outcome "' + outcome + '".');
        }
    }

    // frm_ajax views written for ajax_form.js reply {status, message, action}
    // with no outcome (e.g. the HS admin roster verification form). Answer
    // them the way ajax_form.js does -- confirm, then reload/redirect/refresh
    // -- so the user sees that the submission went through.
    function _handleAjaxFormResponse(response) {
        var span = document.createElement('span');
        span.textContent = response.message;
        swal({ title: 'Success', content: span, icon: 'success' }).then(function () {
            if (response.action === 'reload') {
                location.reload();
            } else if (response.action === 'redirect' && response.redirect_url) {
                window.location.assign(response.redirect_url);
            } else if (response.action === 'refresh_table' && response.table_id) {
                $('#' + response.table_id).DataTable().ajax.reload();
            }
        });
    }

    function _startPolling(response) {
        $.blockUI({ message: '<h4><i class="fa fa-spinner fa-spin"></i> ' + (response.message || 'Working…') + '</h4>' });
        _poll(response.poll_url, response.title || 'Done');
    }

    function _poll(url, title) {
        setTimeout(function () {
            $.ajax({
                type: 'GET',
                url: url,
                success: function (data) {
                    if (data.status === 'SUCCEEDED') {
                        $.unblockUI();
                        var counts = data.counts || {};
                        var lines = [
                            'Sections created: '  + (counts.section_created  || 0),
                            'Sections updated: '  + (counts.section_updated  || 0),
                            'Sections skipped: '  + (counts.section_skipped  || 0),
                            'Courses created: '   + (counts.course_created   || 0),
                            'Teachers created: '  + (counts.teacher_created  || 0),
                            'Certs created: '     + (counts.cert_created     || 0),
                        ];
                        if (counts.errors && counts.errors.length) {
                            lines.push('Errors: ' + counts.errors.length);
                        }
                        var span = document.createElement('span');
                        span.innerHTML = lines.join('<br>');
                        if (counts.error_log_url && /^(https:\/\/|\/)/.test(counts.error_log_url)) {
                            span.appendChild(document.createElement('br'));
                            var logLink = document.createElement('a');
                            logLink.href = counts.error_log_url;
                            logLink.target = '_blank';
                            logLink.rel = 'noopener';
                            logLink.textContent = 'Download error log (CSV)';
                            span.appendChild(logLink);
                        }
                        swal({ title: title, content: span, icon: 'success' });
                    } else if (data.status === 'FAILED') {
                        $.unblockUI();
                        swal({ title: 'Import Failed', text: data.error || 'An error occurred during import.', icon: 'error' });
                    } else {
                        _poll(url, title);
                    }
                },
                error: function () {
                    $.unblockUI();
                    swal({ title: 'Error', text: 'Lost contact with the server while polling.', icon: 'error' });
                }
            });
        }, 2000);
    }

    function _handleFormSubmit($form) {
        var $blocked = $form.parent();
        $blocked.block();

        $form.find('input, select, textarea').removeClass('is-invalid');
        $form.find('.invalid-feedback').remove();

        $.ajax({
            type: 'POST',
            url: $form.attr('action'),
            data: $form.serialize(),
            success: function (response) {
                $blocked.unblock();
                $('#' + MODAL_ID).modal('hide');
                _handleResponse(response);
            },
            error: function (xhr) {
                $blocked.unblock();
                _handleFormError(xhr);
            }
        });
    }

    function _handleFormError(xhr) {
        var data = xhr.responseJSON || {};
        var errors = {};
        // A JSON string (form.errors.as_json()) or, from views written for
        // ajax_form.js, an object (form.errors.get_json_data()).
        if (typeof data.errors === 'string') {
            try { errors = JSON.parse(data.errors); } catch (e) {}
        } else if (data.errors) {
            errors = data.errors;
        }
        var first = true;
        for (var name in errors) {
            for (var i in errors[name]) {
                var $input = $('[name="' + name + '"]');
                var msg = errors[name][i].message || errors[name][i];
                $input.addClass('is-invalid');
                $input.after('<p class="invalid-feedback"><strong>' + msg + '</strong></p>');
                if (first) { $input.focus(); first = false; }
            }
        }
        var span = document.createElement('span');
        span.innerHTML = data.message || 'Please correct the errors and try again.';
        swal({ title: data.message || 'Error', content: span, icon: 'warning' });
    }

    function _csrfToken() {
        // Prefer the session token rendered into the page (window.CSRF_TOKEN);
        // it is always correct for this session regardless of cookie name.
        if (window.CSRF_TOKEN) { return window.CSRF_TOKEN; }
        // Prefer the hidden input rendered by {% csrf_token %} — it is
        // independent of CSRF_COOKIE_NAME, which is tenant-prefixed in
        // local dev (e.g. ewu_csrftoken) to keep concurrent tenants on
        // 127.0.0.1 from clobbering each other's cookies.
        var input = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (input && input.value) { return input.value; }
        var match = document.cookie.match(/(?:^|;\s*)[^=;\s]*csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    // Shared bulk-completion callback for `{outcome:'call', fn:'onBulkActionComplete'}`
    // responses. Several apps' bulk actions (e.g. cis student views, cis
    // actions/term.py) return this callback name, and action_registry.js is the
    // only file loaded on every page (see logged-base.html), so this must live
    // here rather than in any page-specific script. Moved here verbatim from
    // cis/staticfiles/js/courses.js, where it was defined but not globally
    // available, causing "onBulkActionComplete is not defined on window" on
    // any non-course page (e.g. /ce/students/).
    function onBulkActionComplete(args) {
        if (window.jQuery && $.fn.dataTable) {
            $($.fn.dataTable.tables(true)).each(function () {
                var dt = $(this).DataTable();
                dt.rows({ selected: true }).deselect();
                dt.ajax.reload(null, false);
            });
        }
        if (args && args.message) {
            // textContent, not innerHTML: every server response that names this
            // callback passes a plain sentence or a count summary (audited across
            // cis/views/student.py, cis/actions/*.py -- no message contains markup),
            // while other messages in this codebase do interpolate user-supplied
            // values such as names and email addresses. Rendering as text keeps a
            // future caller from turning that into stored XSS.
            var span = document.createElement('span');
            span.textContent = args.message;
            swal({ title: args.title || 'Done', content: span, icon: args.status || 'success' });
        }
    }
    window.onBulkActionComplete = onBulkActionComplete;

    return { init: init, doAction: doAction, doBulkAction: doBulkAction };
}());
