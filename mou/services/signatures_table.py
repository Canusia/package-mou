"""Shared config builder for the MOUSignature DataTable.

Mirrors cis/services/registrations_table.py — header HTML and named
profiles live here, JS column renderers + bulk-action registry live in
webapp/mou/mou/staticfiles/js/signatures_table.js. Column keys are shared.
"""
import json


# <th> markup paired with each JS column key. Header data-data attributes
# are server-side-only so they're maintained here.
COLUMN_HEADER_HTML = {
    'select':        '<th></th>',
    'mou_title':     '<th data-data="signator_template.mou.title" data-name="signator_template.mou.title">MOU</th>',
    'academic_year': '<th data-data="signator_template.mou.academic_year.name" data-name="signator_template.mou.academic_year.name">Academic Year</th>',
    'highschool':    '<th data-data="highschool.name" data-name="highschool.name">High School</th>',
    'signator':      '<th data-data="signator.last_name" data-name="signator.last_name">Signator</th>',
    'role':          '<th data-data="role" data-name="role">Role</th>',
    'status':        '<th data-data="status" data-name="status">Status</th>',
    'created_on':    '<th data-data="created_on" data-name="created_on">Created On</th>',
    'actions':       '<th data-data="id" data-name="id"><span class="sr-only">Actions</span></th>',
}


_PROFILES = {
    'by_academic_year': {
        'table_id':     'tbl_mou_signatures_by_year',
        'columns':      ['select', 'mou_title', 'academic_year', 'highschool',
                         'signator', 'role', 'status', 'created_on', 'actions'],
        'action_scope': 'by_academic_year',
        'default_order': [7, 'desc'],   # created_on
    },
}


def build_config(*, variant, api_url):
    """Build the signatures-table context dict for a given call site.

    KeyError is raised for unknown variants or column keys (fail-fast).
    """
    p = _PROFILES[variant]
    columns = p['columns']

    return {
        'table_id':       p['table_id'],
        'column_headers': [COLUMN_HEADER_HTML[k] for k in columns],
        'opts_json':      json.dumps({
            'apiUrl':       api_url,
            'columns':      columns,
            'actionScope':  p['action_scope'],
            'defaultOrder': p.get('default_order'),
        }),
    }
