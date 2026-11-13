"""Test live 79-point lower-face failure mode without importing Unreal."""
import ast
import math
import unittest
from pathlib import Path


SCRIPT=Path(__file__).resolve().parents[1]/"unreal_create_previs_preset.py"
TREE=ast.parse(SCRIPT.read_text("utf-8"))
FN=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and
        n.name=="select_lower_jaw_symmetric_landmarks")
ns={}
exec(compile(ast.Module(body=[FN],type_ignores=[]),str(SCRIPT),"exec"),ns)
pick=ns["select_lower_jaw_symmetric_landmarks"]


def live_shaped_landmarks():
    # Reproduce the 2026-11-13 RTX4090 receipt: 79 points, full Y span
    # 21.692cm, full Z span 26.850cm, and a one-sided 0-centred lower band.
    lower=[-9.2]+[0.2+0.30*i for i in range(30)]
    coords=[(1.0,y,i*0.12) for i,y in enumerate(lower)]
    coords += [(0.0,-10.846 if i==0 else
                10.846 if i==1 else (i%9-4)*2.1,
                13.0+13.85*i/47.0) for i in range(48)]
    assert len(coords)==79
    return coords


class SymmetricJawSelectionTests(unittest.TestCase):
    def test_reproduces_failure_and_selects_balanced_jaw(self):
        coords=live_shaped_landmarks()
        ys=[p[1] for p in coords]
        z=sorted(p[2] for p in coords)
        mid=(min(ys)+max(ys))/2.0
        half=(max(ys)-min(ys))/2.0
        low=z[int(len(z)*0.38)]
        old_left=[p for p in coords if p[2]<=low and p[1]<mid-half*0.28]
        self.assertEqual(len(old_left),1)
        ids,shifts,info=pick(coords)
        self.assertEqual(len(ids),16)
        self.assertEqual(len(shifts),16)
        self.assertEqual((info["lower_left"],info["lower_right"]),(8,8))
        self.assertEqual(ids,sorted(set(ids)))
        self.assertTrue(all(0<abs(delta)<=0.1 for delta in shifts))
        for index,shift in zip(ids,shifts):
            self.assertLess((coords[index][1]-info["local_center"])*shift, 0.0)

    def test_narrow_or_one_sided_bands_fail_closed(self):
        narrow=[(0.0,0.001*i,float(i)) for i in range(79)]
        with self.assertRaisesRegex(ValueError,"lower_face_width_invalid"):
            pick(narrow)
        # Missing lower-face landmarks must never commit an asymmetrical edit.
        sparse=[(0.0,float(i),float(i)) for i in range(19)]
        with self.assertRaisesRegex(ValueError,"landmark_count_outside_bounds"):
            pick(sparse)

    def test_does_not_exceed_unit_safety_limit(self):
        coords=live_shaped_landmarks()
        ids,shifts,_=pick(coords)
        self.assertTrue(math.isclose(max(map(abs,shifts)),0.1,
                                     rel_tol=0,abs_tol=1e-10))
        self.assertTrue(all(coords[i][2]<=3.6 for i in ids))


if __name__=="__main__":
    unittest.main()
