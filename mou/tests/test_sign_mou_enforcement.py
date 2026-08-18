"""Signing order is a server-side rule, not a template one.

sign_mou's POST handler called form.save() without checking status or chain
position, so an old signing URL could be replayed to sign out of order or to
overwrite an existing signature.
"""
from django.test import Client, TestCase
from django.urls import reverse

from ..models import MOUSignature
from .factories import make_mou_with_chain


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
