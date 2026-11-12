"""Validate fixed exposure, independent clear portraits and safe clone-only edits.

This offline test executes the EXACT production exposure helper with fake UE
objects, rather than claiming to have seen an actual Unreal render.
"""
from __future__ import annotations

import ast
import sys
import types
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"unreal_create_previs_preset.py").read_text("utf-8")
CAST=("GPT","GEM","DS","CLA","ZERO")


class Vector:
    def __init__(self,x,y,z):
        self.x,self.y,self.z=x,y,z


class Component:
    def __init__(self,name="",position=None):
        self.name=name
        self.position=position or Vector(25,0,168)
        self.material=None
        self.props={}
    def get_name(self):
        return self.name
    def get_relative_location(self):
        return self.position
    def set_relative_location(self,position,*a):
        self.position=position
    def set_material(self,slot,mat):
        assert slot==0
        self.material=mat
    def set_static_mesh(self,mesh):
        return bool(mesh)
    def set_editor_property(self,key,value):
        self.props[key]=value


class Actor:
    def __init__(self,label="",comps=None):
        self.label=label
        self.comps=comps or []
        self.comp=Component()
        self.props={}
        self.scale=None
        self.settings=Component("postprocess")
    def get_actor_label(self):
        return self.label
    def get_components_by_class(self,*a):
        return self.comps
    def get_component_by_class(self,*a):
        return self.comp
    def set_actor_label(self,label):
        self.label=label
    def set_actor_scale3d(self,scale):
        self.scale=scale
    def get_editor_property(self,key):
        if key!="settings":
            raise RuntimeError(key)
        return self.settings
    def set_editor_property(self,key,value):
        self.props[key]=value


class World:
    def __init__(self,existing):
        self.existing=list(existing)
        self.spawned=[]
    def get_all_level_actors(self):
        return self.existing+self.spawned
    def spawn_actor_from_class(self,kind,position,rotation):
        item=Actor()
        item.kind=kind
        self.spawned.append(item)
        return item


class TestV120ReviewLook(unittest.TestCase):
    def make_look(self):
        tree=ast.parse(SOURCE)
        matches=[x for x in tree.body if isinstance(x,ast.FunctionDef)
                 and x.name=="apply_v120_cast_review_look"]
        self.assertEqual(len(matches),1)
        ue=types.SimpleNamespace(
            Vector=Vector, Rotator=Vector,
            StaticMeshComponent=type("SMC",(),{}),
            PointLightComponent=type("PLC",(),{}),
            StaticMeshActor=type("SMA",(),{}),
            PostProcessVolume=type("PPV",(),{}),
            AutoExposureMethod=types.SimpleNamespace(AEM_MANUAL="Manual"),
            EditorAssetLibrary=types.SimpleNamespace(load_asset=lambda p:p),
        )
        ns={"unreal":ue,"V11_CAST_SOURCE_JOB":
            "f32dea96d7a94990b3eb274d1cef3de3"}
        isolated=ast.fix_missing_locations(
            ast.Module(body=matches,type_ignores=[]))
        exec(compile(isolated,"review-helper","exec"),ns)
        return ns["apply_v120_cast_review_look"]

    def cast(self):
        names=(
            "Right_Eye_Iris","Left_Eye_Iris",
            "Right_Eye_Highlight","Left_Eye_Highlight",
            "Right_Brow","Left_Brow","Nose","Mouth_Center",
        )
        actors={}
        for cast in CAST:
            extra=(["Hair_SidePart_Fringe"] if cast=="GPT"
                   else [f"Hair_Layer_{i:02d}" for i in range(4)]
                   if cast=="GEM"
                   else [f"Hair_Braid_{i:02d}" for i in range(7)]
                   if cast=="DS"
                   else ["Right_Wrist_Red_Thread"] if cast=="ZERO"
                   else [])
            items=[Component(name,Vector(25,-13 if name.startswith("Right") else
                                           13,168)) for name in names+tuple(extra)]
            if cast=="ZERO":
                items[-1].position=Vector(0,-43,88)
            actors[cast]=Actor("WO_CANDIDATE_CHAR_"+cast,items)
        return actors

    def test_true_manual_exposure_and_visible_faces_on_cloned_level(self):
        cast=self.cast()
        world=World([Actor("WO_CANDIDATE_ReviewFloor"),
                     Actor("WO_CANDIDATE_ReviewLight"),*cast.values()])
        original={ident:[(p.name,p.position) for p in actor.comps]
                  for ident,actor in cast.items()}
        result=self.make_look()(world,cast)
        self.assertEqual(result["face_component_overrides"],52)
        self.assertEqual(result["exposure_method"],"manual")
        self.assertEqual(result["bloom_intensity"],0.0)
        self.assertEqual(result["exposure_bias"],-1.5)
        self.assertTrue(result["v120_source_master_unchanged"])
        for actor in cast.values():
            comps={x.name:x for x in actor.comps}
            for eye in ("Left_Eye_Iris","Right_Eye_Iris"):
                self.assertEqual(comps[eye].position.x,57)
            for highlight in ("Left_Eye_Highlight","Right_Eye_Highlight"):
                self.assertEqual(comps[highlight].position.x,62)
        zero={x.name:x for x in cast["ZERO"].comps}
        self.assertLess(zero["Right_Wrist_Red_Thread"].position.y,0)
        self.assertEqual(len(world.spawned),2)
        wall,post=world.spawned
        self.assertEqual(wall.label,"WO_V120_NeutralBackdrop")
        self.assertEqual(post.label,"WO_V120_FixedExposure")
        self.assertEqual(post.props["unbound"],True)
        self.assertEqual(post.settings.props["auto_exposure_method"],"Manual")
        self.assertTrue(post.settings.props["override_auto_exposure_method"])
        self.assertFalse(post.settings.props[
            "auto_exposure_apply_physical_camera_exposure"])
        self.assertEqual(post.settings.props["bloom_intensity"],0.0)
        floor=world.existing[0]
        self.assertIn("/Materials/M_Charcoal",floor.comp.material)
        self.assertIn("/Materials/M_Parchment",wall.comp.material)
        self.assertEqual(world.existing[1].comp.props["intensity"],350.0)

    def test_portrait_cameras_cannot_include_neighbouring_actor(self):
        tree=ast.parse(SOURCE)
        data=next(node.value for node in tree.body
                  if isinstance(node,ast.Assign)
                  and any(isinstance(t,ast.Name) and
                          t.id=="V11_CAMERA_POSES" for t in node.targets))
        poses=ast.literal_eval(data)
        self.assertEqual(tuple(poses),("LINEUP",*CAST))
        self.assertEqual(poses["LINEUP"][2],40.0)
        for index,short in enumerate(CAST):
            location,target,focal,filmback=poses[short]
            self.assertEqual(location[1],(index-2)*165)
            self.assertEqual(target[1],location[1])
            self.assertEqual(focal,50.0)
            self.assertEqual(filmback,(13.5,24.0))
            # 480cm * 13.5mm / 50mm = 129.6cm total width. Adjacent actor
            # is 165cm away and thus outside this cast-only portrait frame.
            self.assertLess(location[0]*filmback[0]/focal,160)

    def test_no_source_master_saving_or_approved_asset_writes(self):
        tree=ast.parse(SOURCE)
        fn=next(x for x in tree.body
                if isinstance(x,ast.FunctionDef)
                and x.name=="apply_v120_cast_review_look")
        body=ast.get_source_segment(SOURCE,fn)
        self.assertNotIn("save_loaded_asset",body)
        self.assertNotIn("save_current_level",body)
        self.assertNotIn("/Approved/",body)
        self.assertIn("V11_CAST_SOURCE_JOB",body)
        self.assertNotIn("EditorAssetLibrary.delete",body)


if __name__=="__main__":
    unittest.main()
