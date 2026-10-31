"""The vendored registries must stay identical to the host originals they
copy (review M-2). Skipped on hosts that have no original (embry, rmu), which
is where the copies are used."""
import ast
import importlib.util
import os

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _code_after_docstring(source):
    """Source with a leading module docstring removed."""
    tree = ast.parse(source)
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], 'value', None), ast.Constant) and isinstance(
            body[0].value.value, str):
        lines = source.splitlines(keepends=True)
        return ''.join(lines[body[0].end_lineno:]).lstrip('\n')
    return source


class VendoredPythonRegistryTests(SimpleTestCase):
    def test_matches_myce_component_registry(self):
        spec = importlib.util.find_spec('myce.component_registry') \
            if importlib.util.find_spec('myce') else None
        if spec is None or not spec.origin:
            self.skipTest('host has no myce.component_registry')
        with open(spec.origin) as fh:
            host = _code_after_docstring(fh.read())
        with open(os.path.join(PKG, '_actions.py')) as fh:
            vendored = _code_after_docstring(fh.read())
        self.assertEqual(
            vendored, host,
            'mou/_actions.py drifted from myce/component_registry; re-copy it')


class VendoredJsRegistryTests(SimpleTestCase):
    def test_matches_host_action_registry_js(self):
        host_path = finders.find('js/action_registry.js')
        if not host_path:
            self.skipTest('host ships no js/action_registry.js')
        with open(host_path) as fh:
            host = fh.read()
        with open(os.path.join(PKG, 'staticfiles', 'mou', 'js',
                               'action_registry.js')) as fh:
            lines = fh.read().splitlines(keepends=True)
        while lines and lines[0].startswith('//'):
            lines.pop(0)  # the vendoring header
        self.assertEqual(
            ''.join(lines), host,
            'mou/staticfiles/mou/js/action_registry.js drifted from the host '
            'js/action_registry.js; re-copy it')
