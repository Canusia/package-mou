"""Copying a signing link is not an email, and must not look like one.

get_signature_link stamped meta['notified_on'], which the signatures table
renders as "Sent <date>" -- so opening the modal reported a delivery that
never happened.
"""
from django.test import TestCase

from ..models import MOUSignature
from .factories import make_mou_with_chain


class SignatureLinkStampTests(TestCase):
    def setUp(self):
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1])
        self.sig = self.sigs[1]
        self.sig.status = MOUSignature.STATUS_NEXT
        self.sig.save(update_fields=['status'])

    def test_copying_a_link_does_not_stamp_notified_on(self):
        self.sig.mark_pending_from_signature_link()
        self.sig.refresh_from_db()
        self.assertNotIn('notified_on', self.sig.meta or {})

    def test_copying_a_link_still_makes_the_row_signable(self):
        self.sig.mark_pending_from_signature_link()
        self.sig.refresh_from_db()
        self.assertEqual(self.sig.status, MOUSignature.STATUS_PENDING)

    def test_an_existing_sent_stamp_is_preserved(self):
        self.sig.meta = {'notified_on': '08/01/2026 09:00 AM'}
        self.sig.save(update_fields=['meta'])
        self.sig.mark_pending_from_signature_link()
        self.sig.refresh_from_db()
        self.assertEqual(self.sig.meta['notified_on'], '08/01/2026 09:00 AM')
