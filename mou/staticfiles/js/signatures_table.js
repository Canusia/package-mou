/* Shared MOUSignature DataTable wiring.
 *
 * Used by webapp/mou/mou/templates/mou/_signatures_table.html via
 * initSignaturesTable(tableId, opts).
 *
 * Companion: mou.services.signatures_table owns the matching <th> markup
 * and the named profiles. Column keys are shared.
 */
(function () {
  'use strict';

  function bulkActionUrl() {
    return window.MOU_BULK_ACTIONS_URL || '/ce/highschools/mous/mou/do_bulk_action';
  }

  function doBulkAction(action, dt) {
    if (!dt.rows('.selected').any()) {
      alert('Please select a row and try again.');
      return;
    }
    var selected = dt.rows({ selected: true });
    var data = { action: action, ids: [] };
    selected.every(function () { data.ids.push(this.id()); });

    $(dt).block();
    $.ajax({
      type: 'GET',
      url: bulkActionUrl(),
      data: data,
      success: function (response) {
        $('#bulk_modal_content').html(response);
        $('#modal-bulk_actions').modal('show');
      },
    });
  }

  function buildColumns(keys) {
    var defs = {
      select: {
        searchable: false,
        orderable: false,
        render: function () { return ''; },
      },
      mou_title: {
        render: function (_d, _t, row) { return row.signator_template.mou.title; },
      },
      academic_year: {
        render: function (_d, _t, row) {
          var ay = row.signator_template.mou.academic_year;
          return ay ? ay.name : '';
        },
      },
      highschool: {
        render: function (_d, _t, row) {
          return row.highschool ? row.highschool.name : '';
        },
      },
      signator: {
        render: function (_d, _t, row) {
          if (!row.signator) return '<span class="text-muted">—</span>';
          var name = (row.signator.last_name || '') + ', ' + (row.signator.first_name || '');
          var email = row.signator.email
            ? '<br><small class="text-muted">' + row.signator.email + '</small>'
            : '';
          return name + email;
        },
      },
      role: {
        render: function (_d, _t, row) { return row.role || ''; },
      },
      status: {
        render: function (_d, _t, row) {
          var s = (row.status || '').toLowerCase();
          var pretty = row.sexy_status || row.status || '—';
          var cls = 'badge-secondary';
          if (s === 'signed')  cls = 'badge-success';
          if (s === 'next')    cls = 'badge-info';
          if (s === 'pending') cls = 'badge-warning';
          if (s === 'declined' || s === 'failed') cls = 'badge-danger';
          var html = '<span class="badge ' + cls + '">' + pretty + '</span>';
          if (row.notified_on_display) {
            html += '<br><small class="text-muted">Sent ' + row.notified_on_display + '</small>';
          }
          // For signed rows, expose a PDF download link directly under the badge.
          // mou_pdf_url + is_signed are emitted by MOUSignatureSerializer
          // (datatables_always_serialize).
          if (row.is_signed && row.mou_pdf_url) {
            html += '<br><a href="' + row.mou_pdf_url + '" target="_blank" class="small">' +
              '<i class="fas fa-file-pdf"></i>&nbsp;Download PDF</a>';
          }
          return html;
        },
      },
      created_on: {
        render: function (_d, _t, row) { return row.created_on || ''; },
      },
      actions: {
        searchable: false,
        orderable: false,
        render: function (_d, _t, row) {
          var url = (row.signator_template && row.signator_template.mou && row.signator_template.mou.ce_url) || '';
          if (!url) return '';
          return "<a class='btn btn-sm btn-primary' href='" + url + "'>View MOU</a>";
        },
      },
    };
    return keys.map(function (k) {
      if (!(k in defs)) throw new Error('Unknown signatures_table column: ' + k);
      return defs[k];
    });
  }

  // Action registry — each entry is one BULK_ACTIONS row.
  var BULK_ACTIONS = {
    send_link: { label: 'Email Signature Link', icon: 'fa-envelope', action: 'send_signature_link' },
    get_link:  { label: 'Copy Signature Link',  icon: 'fa-link',     action: 'get_signature_link'  },
  };

  // Action scopes — declares which BULK_ACTIONS keys are exposed per call site.
  var ACTION_SCOPES = {
    by_academic_year: ['send_link', 'get_link'],
  };

  function buildButtons(scopeName) {
    var buttons = [
      {
        extend: 'csv',
        className: 'btn btn-sm btn-primary text-white text-light',
        text: '<i class="fas fa-file-csv text-white"></i>&nbsp;CSV',
        titleAttr: 'Export results to CSV',
      },
      {
        extend: 'print',
        className: 'btn btn-sm btn-primary text-white text-light',
        text: '<i class="fas fa-print text-white"></i>&nbsp;Print',
        titleAttr: 'Print',
      },
    ];
    var keys = (scopeName && ACTION_SCOPES[scopeName]) || [];
    keys.forEach(function (k) {
      var spec = BULK_ACTIONS[k];
      if (!spec) return;
      buttons.push({
        className: 'btn btn-sm btn-primary text-white text-light',
        text: '<i class="fas ' + spec.icon + ' text-white"></i>&nbsp;' + spec.label,
        titleAttr: spec.label,
        action: function (e, dt) { doBulkAction(spec.action, dt); },
      });
    });
    return buttons;
  }

  window.initSignaturesTable = function (tableId, opts) {
    var $table = $(tableId);
    if (!$table.length) {
      throw new Error('initSignaturesTable: no element matches ' + tableId);
    }

    var hasSelect = opts.columns.indexOf('select') !== -1;

    var dtConfig = {
      dom: 'B<"float-left mt-3 mb-3"l><"float-right mt-3"f><"row clear">rt<"row"<"col-6"i><"col-6 float-right"p>>',
      buttons: buildButtons(opts.actionScope),
      searchDelay: 1500,
      ajax: opts.apiUrl,
      serverSide: true,
      processing: true,
      stateSave: false,
      language: { loadingRecords: '&nbsp;' },
      lengthMenu: [25, 50, 100],
      order: [opts.defaultOrder || [hasSelect ? 1 : 0, 'desc']],
      rowId: 'id',
      columns: buildColumns(opts.columns),
    };
    if (hasSelect) {
      dtConfig.columnDefs = [{ orderable: false, className: 'select-checkbox', targets: 0 }];
      dtConfig.select = { style: 'os', selector: 'td:first-child' };
    }

    var table = $table.DataTable(dtConfig);

    window.refreshSignaturesTable = function () {
      table.rows({ selected: true }).deselect();
      table.ajax.reload(null, false);
    };

    return table;
  };
})();
