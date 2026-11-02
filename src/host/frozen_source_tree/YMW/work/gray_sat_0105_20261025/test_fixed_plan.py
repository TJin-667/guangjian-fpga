import unittest
from fixed_plan import build_plan

class FixedPlanTests(unittest.TestCase):
    def test_eight_roles_and_directions_without_search(self):
        p=build_plan(400,800)
        self.assertEqual({(o['channel'],o['role']) for o in p['observations']},{(c,r) for c in range(1,5) for r in ('low','high')})
        self.assertEqual(len({o['observation_id'] for o in p['observations']}),8)
        self.assertTrue(all(o['gain16']==16 and o['led']==128 for o in p['observations']))
        self.assertFalse(p['online_exposure_search']);self.assertEqual(p['automatic_retries'],0)
        self.assertEqual(p['status'],'REVIEW_ONLY_NOT_CAPTURE_AUTHORIZATION')

    def test_invalid_or_collapsed_pair(self):
        for pair in ((400,400),(800,400),(399,800),(400,801),(True,800)):
            with self.assertRaises(ValueError):build_plan(*pair)

if __name__=='__main__':unittest.main(verbosity=2)
