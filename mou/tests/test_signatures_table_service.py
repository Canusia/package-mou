import json

from django.test import SimpleTestCase

try:
    from mou.mou.services.signatures_table import build_config
except ImportError:
    from mou.services.signatures_table import build_config


class BuildConfigByAcademicYearTests(SimpleTestCase):
    def test_returns_table_id_and_column_headers(self):
        cfg = build_config(
            variant='by_academic_year',
            api_url='/ce/highschools/mous/api/mou_signatures?format=datatables&academic_year_id=42',
        )

        self.assertEqual(cfg['table_id'], 'tbl_mou_signatures_by_year')
        # 9 visible columns: select, MOU title, academic year, highschool,
        # signator, role, status, last updated, actions.
        self.assertEqual(len(cfg['column_headers']), 9)
        for header in cfg['column_headers']:
            self.assertTrue(header.startswith('<th'))

    def test_opts_json_carries_api_url_and_action_scope(self):
        cfg = build_config(
            variant='by_academic_year',
            api_url='/x?academic_year_id=42',
        )

        opts = json.loads(cfg['opts_json'])
        self.assertEqual(opts['apiUrl'], '/x?academic_year_id=42')
        self.assertEqual(opts['actionScope'], 'by_academic_year')
        self.assertIn('select', opts['columns'])
        self.assertIn('signator', opts['columns'])
        self.assertIn('status', opts['columns'])

    def test_unknown_variant_raises(self):
        with self.assertRaises(KeyError):
            build_config(variant='nope', api_url='/x')
