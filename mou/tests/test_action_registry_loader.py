"""mou.html loads the vendored client registry only when the host has none
(review I-3). Hosts without ``action_registry.js`` in ``cis/logged-base.html``
(embry, rmu) otherwise get a dead Duplicate/Delete menu."""
import os
import re

from django.test import SimpleTestCase

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PKG, *parts)) as fh:
        return fh.read()


class GuardedLoaderTests(SimpleTestCase):
    def test_vendored_js_ships(self):
        js = _read('staticfiles', 'mou', 'js', 'action_registry.js')
        self.assertIn('var ActionRegistry =', js)
        self.assertIn('function doAction(', js)

    def test_template_loads_it_only_when_missing(self):
        html = _read('templates', 'mou', 'mou.html')
        self.assertIn("{% static 'mou/js/action_registry.js' %}", html)
        # Decided after the host's own end-of-body scripts have run, and
        # skipped when the host already defines the global.
        loader = re.search(
            r"DOMContentLoaded.*?if \(window\.ActionRegistry\) \{ return; \}"
            r".*?mou/js/action_registry\.js", html, re.S)
        self.assertIsNotNone(loader, 'guarded loader missing from mou.html')

    def test_manifest_ships_staticfiles(self):
        manifest = os.path.join(os.path.dirname(PKG), 'MANIFEST.in')
        if not os.path.exists(manifest):
            self.skipTest('MANIFEST.in not shipped')
        with open(manifest) as fh:
            self.assertIn('recursive-include mou/staticfiles *', fh.read())
