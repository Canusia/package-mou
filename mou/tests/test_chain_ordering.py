"""A school with an open change request must not advance its signing chain.

current_unsigned_signatures() excluded `changes_requested` alongside `signed`,
so the "lowest unsigned signer" skipped past a blocked step: weight 3 was
marked Next Up and emailed while weight 2's change request was still open.
This contradicted is_next_in_chain(), which excludes only `signed`.
"""
from django.test import TestCase

from ..models import MOUSignature
from .factories import make_mou_with_chain


class ChainOrderingTests(TestCase):
    def setUp(self):
        # One school, three signers at weights 1, 2, 3.
        self.mou, self.school, self.sigs = make_mou_with_chain(weights=[1, 2, 3])

    def _set(self, weight, status):
        sig = self.sigs[weight]
        sig.status = status
        sig.save(update_fields=['status'])

    def test_blocked_school_yields_no_current_signer(self):
        self._set(1, 'signed')
        self._set(2, MOUSignature.STATUS_CHANGES_REQUESTED)
        self.assertEqual(list(self.mou.current_unsigned_signatures()), [])

    def test_blocked_school_marks_nobody_next_up(self):
        self._set(1, 'signed')
        self._set(2, MOUSignature.STATUS_CHANGES_REQUESTED)
        self.mou.initialize_signature_status()
        self.sigs[3].refresh_from_db()
        self.assertEqual(self.sigs[3].status or '', '')

    def test_unblocked_chain_advances_to_the_next_weight(self):
        self._set(1, 'signed')
        current = list(self.mou.current_unsigned_signatures())
        self.assertEqual([s.pk for s in current], [self.sigs[2].pk])

    def test_agrees_with_is_next_in_chain(self):
        """Whatever this method returns must itself be next in its chain."""
        self._set(1, 'signed')
        self._set(2, MOUSignature.STATUS_CHANGES_REQUESTED)
        self._set(3, '')
        for sig in self.mou.current_unsigned_signatures():
            self.assertTrue(
                sig.is_next_in_chain(),
                f'weight {sig.signator_template.weight} returned but not next in chain',
            )

    def test_fresh_chain_starts_at_the_lowest_weight(self):
        current = list(self.mou.current_unsigned_signatures())
        self.assertEqual([s.pk for s in current], [self.sigs[1].pk])
