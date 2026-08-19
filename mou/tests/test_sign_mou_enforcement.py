"""Signing order is a server-side rule, not a template one.

sign_mou's POST handler called form.save() without checking status or chain
position, so an old signing URL could be replayed to sign out of order or to
overwrite an existing signature.

request_changes shares the chain-position half of that gate
(may_be_asked_to_sign()): replaying a request_changes POST against a signed
row or an out-of-order row (earlier signer still outstanding, whether or not
this row was formally invited) must not act on it. Unlike signing, a
never-formally-invited row that IS next in chain (no earlier signer at its
school) legitimately CAN request changes -- and send_signature_link, which
shares the same chain-position predicate, legitimately CAN send that row its
first invite. Signing alone keeps the extra is_ready_to_be_signed()
(status == 'pending') requirement.
"""
import importlib.util

from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.settings import Setting

from ..models import MOUSignature
from .factories import make_mou_with_chain

_PKG = 'mou.mou' if importlib.util.find_spec('mou.mou') else 'mou'


def _write_cfg(value):
    # Both settings-key spellings this package can be installed under.
    for key in ('mou.settings.email_settings', 'mou.mou.settings.email_settings'):
        Setting.objects.update_or_create(key=key, defaults={'value': value})


@override_settings(DEBUG=False, ROOT_URLCONF=f'{_PKG}.tests.urls_hs')
class SignMouEnforcementTests(TestCase):
    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1, 2])
        self.client = Client()
        # is_active='Yes' (and DEBUG=False above) so send_signature_link's
        # tests exercise a real send instead of bailing out on
        # notification_recipients() -- Debug mode / DEBUG=True would
        # otherwise redirect to an empty notify_address and never stamp
        # notified_on, regardless of the chain-position gate under test.
        _write_cfg({
            'is_active': 'Yes',
            'email_subject': 'Please sign',
            'email_message': 'Please sign, {{signator_firstname}}.',
        })
        # do_bulk_action (used by the send_signature_link tests) sits behind
        # LoginRequiredMiddleware / user_has_cis_role, unlike the public
        # sign_mou page (login_required=False). A CE user is needed to reach
        # it at all.
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.ce_user = CustomUser.objects.create_user(
            username='ce@example.com', email='ce@example.com',
            password='x', is_staff=True,
        )
        self.ce_user.groups.add(ce_group)

        # django_login_history's post_login signal handler geolocates
        # REMOTE_ADDR, which force_login's synthetic request doesn't set --
        # disconnect it for the login only, same workaround as
        # test_duplicate.py's MOUActionRegistryTests.
        from django.contrib.auth.signals import user_logged_in
        from django_login_history.models import post_login
        user_logged_in.disconnect(post_login)
        try:
            self.client.force_login(self.ce_user)
        finally:
            user_logged_in.connect(post_login)

    def _post_signature(self, sig):
        # MOUSignatureForm's other required fields are stripped when
        # complete_extra_form == 'No' (the factory's default), and
        # name/email/position are disabled fields populated from initial.
        # The remaining required fields are 'signature' and 'confirm_term'.
        return self.client.post(
            reverse('mou:sign', kwargs={'signature_id': sig.id}),
            {'signature': 'data:image/png;base64,AAAA', 'confirm_term': 'on'},
        )

    def test_later_signer_cannot_sign_before_the_earlier_one(self):
        self.sigs[2].status = MOUSignature.STATUS_PENDING
        self.sigs[2].save(update_fields=['status'])
        self._post_signature(self.sigs[2])
        self.sigs[2].refresh_from_db()
        self.assertNotEqual(self.sigs[2].status, 'signed')
        self.assertNotIn('signature', self.sigs[2].meta or {})

    def test_not_yet_invited_signer_cannot_sign(self):
        self.sigs[1].status = ''
        self.sigs[1].save(update_fields=['status'])
        self._post_signature(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertNotEqual(self.sigs[1].status, 'signed')

    def test_already_signed_row_cannot_be_overwritten(self):
        self.sigs[1].status = 'signed'
        self.sigs[1].meta = {'signature': 'ORIGINAL'}
        self.sigs[1].save(update_fields=['status', 'meta'])
        self._post_signature(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertEqual(self.sigs[1].meta['signature'], 'ORIGINAL')

    def test_changes_requested_row_cannot_be_signed(self):
        self.sigs[1].status = MOUSignature.STATUS_CHANGES_REQUESTED
        self.sigs[1].save(update_fields=['status'])
        self._post_signature(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertNotEqual(self.sigs[1].status, 'signed')

    def test_the_legitimate_signer_still_succeeds(self):
        self.sigs[1].status = MOUSignature.STATUS_PENDING
        self.sigs[1].save(update_fields=['status'])
        self._post_signature(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertEqual(self.sigs[1].status, 'signed')

    def _post_request_changes(self, sig):
        return self.client.post(
            reverse('mou:sign', kwargs={'signature_id': sig.id}),
            {'action': 'request_changes', 'change_request_comment': 'Please fix section 3.'},
        )

    def test_request_changes_cannot_unsign_a_signed_row(self):
        self.sigs[1].status = 'signed'
        self.sigs[1].meta = {'signature': 'ORIGINAL'}
        self.sigs[1].save(update_fields=['status', 'meta'])
        self._post_request_changes(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertEqual(self.sigs[1].status, 'signed')
        self.assertNotIn('change_request_comment', self.sigs[1].meta or {})

    def test_request_changes_cannot_be_issued_by_a_later_signer_out_of_order(self):
        # sigs[2] is weight 2; weight-1 signer (sigs[1]) has not signed yet,
        # so sigs[2] is not next in chain even though it is 'pending'.
        self.sigs[2].status = MOUSignature.STATUS_PENDING
        self.sigs[2].save(update_fields=['status'])
        self._post_request_changes(self.sigs[2])
        self.sigs[2].refresh_from_db()
        self.assertNotEqual(self.sigs[2].status, MOUSignature.STATUS_CHANGES_REQUESTED)

    def test_request_changes_blocked_when_an_earlier_signer_still_outstanding_even_if_blank(self):
        # sigs[2] is weight 2 and was never invited ('' status), but the
        # weight-1 signer (sigs[1]) hasn't signed either, so sigs[2] is not
        # next in chain -- it must still be blocked, blank status or not.
        self.sigs[2].status = ''
        self.sigs[2].save(update_fields=['status'])
        self._post_request_changes(self.sigs[2])
        self.sigs[2].refresh_from_db()
        self.assertNotEqual(self.sigs[2].status, MOUSignature.STATUS_CHANGES_REQUESTED)

    def test_a_never_formally_invited_signer_next_in_chain_can_request_changes(self):
        # sigs[1] is weight 1 (no earlier signer at this school), so it is
        # next in chain even though it was never formally promoted to
        # next/pending. It is genuinely this signer's turn, so -- unlike
        # signing -- a change request from this row is legitimate.
        self.sigs[1].status = ''
        self.sigs[1].save(update_fields=['status'])
        self._post_request_changes(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertEqual(self.sigs[1].status, MOUSignature.STATUS_CHANGES_REQUESTED)

    def test_the_legitimate_current_signer_can_still_request_changes(self):
        self.sigs[1].status = MOUSignature.STATUS_PENDING
        self.sigs[1].save(update_fields=['status'])
        self._post_request_changes(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertEqual(self.sigs[1].status, MOUSignature.STATUS_CHANGES_REQUESTED)
        self.assertEqual(
            self.sigs[1].meta.get('change_request_comment'),
            'Please fix section 3.',
        )

    def _send_signature_link(self, sig):
        resp = self.client.get(
            reverse('mou_ce:bulk_action'),
            {'action': 'send_signature_link', 'ids[]': [str(sig.id)]},
        )
        sig.refresh_from_db()
        return resp

    def test_send_signature_link_rejects_a_row_the_gate_would_reject(self):
        """A row the sign gate rejects must not be sent a link -- pending
        but out of chain order here."""
        self.sigs[2].status = MOUSignature.STATUS_PENDING
        self.sigs[2].save(update_fields=['status'])
        self.assertFalse(self.sigs[2].may_be_asked_to_sign())

        self._send_signature_link(self.sigs[2])
        # send_notification() would bump notification_count / notified_on.
        self.assertNotIn('notified_on', self.sigs[2].meta or {})

    def test_send_signature_link_sends_the_first_invite_to_a_never_invited_row(self):
        """Regression guard: sending is broader than signing. A blank-status
        row that IS next in chain (sigs[1], weight 1, nothing earlier) must
        still receive the first-ever send -- this is send_signature_link's
        main use, kicking a school's chain off before cron / initialize_
        signature_status has promoted anyone to Next Up."""
        self.sigs[1].status = ''
        self.sigs[1].save(update_fields=['status'])
        self.assertTrue(self.sigs[1].may_be_asked_to_sign())

        resp = self._send_signature_link(self.sigs[1])
        self.assertIn('notified_on', self.sigs[1].meta or {})
        self.assertEqual(self.sigs[1].status, MOUSignature.STATUS_PENDING)

    def test_send_signature_link_refuses_a_never_invited_row_out_of_order(self):
        self.sigs[2].status = ''
        self.sigs[2].save(update_fields=['status'])
        self.assertFalse(self.sigs[2].may_be_asked_to_sign())

        self._send_signature_link(self.sigs[2])
        self.assertNotIn('notified_on', self.sigs[2].meta or {})

    def test_send_signature_link_refuses_a_signed_row(self):
        self.sigs[1].status = 'signed'
        self.sigs[1].meta = {'signature': 'ORIGINAL'}
        self.sigs[1].save(update_fields=['status', 'meta'])

        self._send_signature_link(self.sigs[1])
        self.assertEqual(self.sigs[1].meta.get('signature'), 'ORIGINAL')
        self.assertNotIn('notified_on', self.sigs[1].meta or {})

    def test_send_signature_link_refuses_a_changes_requested_row(self):
        self.sigs[1].status = MOUSignature.STATUS_CHANGES_REQUESTED
        self.sigs[1].meta = {'change_request_comment': 'x'}
        self.sigs[1].save(update_fields=['status', 'meta'])

        self._send_signature_link(self.sigs[1])
        self.assertNotIn('notified_on', self.sigs[1].meta or {})
        self.assertEqual(self.sigs[1].status, MOUSignature.STATUS_CHANGES_REQUESTED)

    def test_a_blank_row_next_in_chain_still_cannot_sign(self):
        """The signing gate must NOT loosen: may_be_asked_to_sign() alone is
        not enough to sign -- is_ready_to_be_signed() (status == 'pending')
        is still required."""
        self.sigs[1].status = ''
        self.sigs[1].save(update_fields=['status'])
        self.assertTrue(self.sigs[1].may_be_asked_to_sign())

        self._post_signature(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertNotEqual(self.sigs[1].status, 'signed')
