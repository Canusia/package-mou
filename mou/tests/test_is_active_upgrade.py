"""Upgrading from v0.0.7 must not silently stop live email.

`is_active` was decorative before PR #1 -- nothing read it, so mail always
went to real signers -- and `install()` seeds it to "Debug". Promoting it to
the master switch therefore flips every existing tenant to debug-only mail
unless the stored value is migrated forward.
"""
from django.test import SimpleTestCase, TestCase

from cis.models.settings import Setting

from ..migrations._is_active import _is_active_keys, _set_live  # noqa: F401  (existence check)
from ..settings.email_settings import email_settings
from ..settings.helpers import is_active_mode, notification_recipients


class IsActiveModeTests(SimpleTestCase):
    def test_yes_sends_to_intended_recipients(self):
        cfg = {'is_active': 'Yes', 'notify_address': 'debug@example.com'}
        self.assertEqual(
            notification_recipients(['signer@example.com'], cfg),
            ['signer@example.com'],
        )

    def test_debug_redirects_to_notify_address(self):
        cfg = {'is_active': 'Debug', 'notify_address': 'debug@example.com'}
        self.assertEqual(
            notification_recipients(['signer@example.com'], cfg),
            ['debug@example.com'],
        )

    def test_missing_key_is_debug(self):
        self.assertEqual(is_active_mode({}), 'Debug')


class UpgradeMigrationTests(TestCase):
    """The migration has already run against the test database, so an existing
    row is simulated by writing one and re-running the forward function."""

    def _run_forward(self):
        _set_live(Setting)

    def test_seeded_debug_row_becomes_yes(self):
        Setting.objects.update_or_create(
            key=email_settings.key,
            defaults={'value': {'is_active': 'Debug', 'notify_address': 'd@e.com'}},
        )
        self._run_forward()
        value = Setting.objects.get(key=email_settings.key).value
        self.assertEqual(value['is_active'], 'Yes')

    def test_row_missing_the_key_gets_yes(self):
        Setting.objects.update_or_create(
            key=email_settings.key, defaults={'value': {'notify_address': 'd@e.com'}},
        )
        self._run_forward()
        value = Setting.objects.get(key=email_settings.key).value
        self.assertEqual(value['is_active'], 'Yes')

    def test_other_keys_are_untouched(self):
        Setting.objects.update_or_create(
            key=email_settings.key,
            defaults={'value': {'is_active': 'Debug', 'retention_years': 3}},
        )
        self._run_forward()
        value = Setting.objects.get(key=email_settings.key).value
        self.assertEqual(value['retention_years'], 3)

    def test_no_row_is_a_no_op(self):
        Setting.objects.filter(key=email_settings.key).delete()
        self._run_forward()  # must not raise
        self.assertFalse(Setting.objects.filter(key=email_settings.key).exists())
