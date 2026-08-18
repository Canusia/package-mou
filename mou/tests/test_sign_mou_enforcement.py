"""Signing order is a server-side rule, not a template one.

sign_mou's POST handler called form.save() without checking status or chain
position, so an old signing URL could be replayed to sign out of order or to
overwrite an existing signature.

request_changes shares the same server-side gate: replaying a request_changes
POST against a signed row, an out-of-order row, or a never-invited row must
not un-sign it or otherwise act on it.
"""
import importlib.util

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..models import MOUSignature
from .factories import make_mou_with_chain

_PKG = 'mou.mou' if importlib.util.find_spec('mou.mou') else 'mou'


@override_settings(ROOT_URLCONF=f'{_PKG}.tests.urls_hs')
class SignMouEnforcementTests(TestCase):
    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1, 2])
        self.client = Client()

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

    def test_request_changes_cannot_be_issued_by_a_never_invited_row(self):
        self.sigs[1].status = ''
        self.sigs[1].save(update_fields=['status'])
        self._post_request_changes(self.sigs[1])
        self.sigs[1].refresh_from_db()
        self.assertNotEqual(self.sigs[1].status, MOUSignature.STATUS_CHANGES_REQUESTED)

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

    def test_send_signature_link_rejects_a_row_the_gate_would_reject(self):
        """A row the gate rejects must not be sent a link (mirrors the shared
        is_turn_to_act() rule -- pending but out of chain order here)."""
        self.sigs[2].status = MOUSignature.STATUS_PENDING
        self.sigs[2].save(update_fields=['status'])
        self.assertFalse(self.sigs[2].is_turn_to_act())

        self.client.get(
            reverse('mou_ce:bulk_action'),
            {'action': 'send_signature_link', 'ids[]': [str(self.sigs[2].id)]},
        )
        self.sigs[2].refresh_from_db()
        # send_notification() would bump notification_count / notified_on.
        self.assertNotIn('notified_on', self.sigs[2].meta or {})
