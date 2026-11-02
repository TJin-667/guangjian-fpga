"""Version-safety checks for current and historical result viewing."""
import unittest
from unittest.mock import patch
from contracts import DETECTOR_ID,LEGACY_DETECTOR_ID,PARAMETER_FREEZE_ID,result_version_label

class ResultVersionTests(unittest.TestCase):
    def test_current_requires_the_complete_parameter_identity(self):
        result=dict(detector_id=DETECTOR_ID,parameter_freeze_id=PARAMETER_FREEZE_ID,automatic_pass=False)
        self.assertIn(PARAMETER_FREEZE_ID,result_version_label(result))
        result['parameter_freeze_id']='old_55_only'
        with self.assertRaisesRegex(ValueError,'freeze identity'):result_version_label(result)

    def test_historical_result_is_explicitly_labelled(self):
        result=dict(detector_id=LEGACY_DETECTOR_ID,automatic_pass=False)
        self.assertIn('历史版本',result_version_label(result))
        self.assertNotIn(PARAMETER_FREEZE_ID,result_version_label(result))

    def test_historical_id_cannot_claim_new_parameter_freeze(self):
        with self.assertRaises(ValueError):
            result_version_label(dict(detector_id=LEGACY_DETECTOR_ID,parameter_freeze_id=PARAMETER_FREEZE_ID,automatic_pass=False))

    def test_auto_pass_is_never_accepted_as_current_or_historical(self):
        for detector in (DETECTOR_ID,LEGACY_DETECTOR_ID):
            with self.assertRaisesRegex(ValueError,'automatic pass'):
                result_version_label(dict(detector_id=detector,automatic_pass=True))

    def test_adapter_refuses_a_stale_or_misbound_bundle(self):
        import frozen_algorithm as algorithm
        with patch.object(algorithm.frozen_runtime,'verify',return_value={'freeze_id':'old','semantic':{'detector_id':DETECTOR_ID}}):
            with self.assertRaisesRegex(ValueError,'identities differ'):algorithm.configuration()

if __name__=='__main__':unittest.main(verbosity=2)
