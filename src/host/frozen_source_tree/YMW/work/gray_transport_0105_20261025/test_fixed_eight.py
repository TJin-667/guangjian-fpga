import copy
import unittest
from fixed_eight import validate_eight
import test_host_transport as fixtures

class FixedEightTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.HostTransportTests();f.setUp();self.fixture=f;self.records=[]
        for index,(channel,role) in enumerate((c,r) for c in range(1,5) for r in ('low','high')):
            f.tag.update(request_id=index+1,dvp_sequence=index+10,publish_sequence=index+1,frame_id=(65534+index)&65535,
                         config_epoch=index+1,camera_generation=index+1,light_generation=index+1)
            f.params.update(exposure_lines=400 if role=='low' else 800,light_mask=1<<(channel-1))
            receiver,_,meta,_=f.loaded();validated=receiver.finalize(meta,expected_query_seq=f.seq,now=1)
            self.records.append(dict(sample_id='sample004',pose_id='poseA',channel=channel,role=role,validated=validated))

    def validate(self,records=None):
        return validate_eight(self.records if records is None else records,sample_id='sample004',pose_id='poseA',low=400,high=800,roi=self.fixture.roi,board=self.fixture.board)

    def test_exact_four_low_high_roles_with_frame_id_wrap(self):
        result=self.validate();self.assertEqual(result['formal_observations'],8)
        self.assertFalse(result['online_exposure_search']);self.assertFalse(result['physical_pose_verified_by_software'])
        self.assertEqual(len({r['observation_id'] for r in result['observations']}),8)

    def test_old_six_budget_and_duplicate_roles_rejected(self):
        with self.assertRaises(ValueError):self.validate(self.records[:6])
        bad=copy.deepcopy(self.records);bad[-1]=copy.deepcopy(bad[-2])
        with self.assertRaises(ValueError):self.validate(bad)

    def test_same_exposure_wrong_gain_direction_pose_and_stale_rejected(self):
        changes=[('exposure_lines',400),('gain16',32),('light_mask',2),('brightness',127)]
        for key,value in changes:
            bad=copy.deepcopy(self.records);bad[1]['validated']['metadata']['parameters'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(bad)
        for key,value in [('pose_id','other'),('sample_id','sample005')]:
            bad=copy.deepcopy(self.records);bad[1][key]=value
            with self.assertRaises(ValueError):self.validate(bad)
        bad=copy.deepcopy(self.records);bad[1]['validated']['metadata']['identity']['request_id']=1
        with self.assertRaises(ValueError):self.validate(bad)

    def test_changed_training_planes_or_payload_rejected(self):
        bad=copy.deepcopy(self.records);bad[0]['validated']['gray'][0,0]^=1
        with self.assertRaises(ValueError):self.validate(bad)
        bad=copy.deepcopy(self.records);bad[0]['validated']['payload']=bytes(len(bad[0]['validated']['payload']))
        with self.assertRaises(ValueError):self.validate(bad)

if __name__=='__main__':unittest.main(verbosity=2)
