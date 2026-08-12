import json, unittest
from pathlib import Path
from qpx_bot.accelerators.dynamic_sizing import load_dynamic_sizing_config
from qpx_bot.shadow_matrix.models import thaw_json
from qpx_bot.shadow_matrix.registry import load_registry

ROOT=Path(__file__).parents[1]
class DynamicSourceTests(unittest.TestCase):
 def test_dynamic_shadows_match_authoritative_algorithm_tiers_caps_and_results(self):
  base=load_dynamic_sizing_config(ROOT/"qpx_bot/accelerators/configs/dynamic_sizing_v1.json")
  paired=json.loads((ROOT/"qpx_bot/accelerators/configs/dynamic_sizing_v1_paired_caps.json").read_text())
  expected={25:"dab4dda61ffeeb93a85a46caac2d8c46125145a89230e9e6490751723178b328",40:"72a2eaee1a7b250971150e3d2a4bed4806d0facd5001f612e847ba12c26c6c35",60:"7d3f757924814a1b3bab070bb3ffc5b8e2035fc0b0ab5b26458ac86e7b68ae28",90:"beb5f970c92ddaa114b01f72f3f2ced23d2cfb2d9d1faceca6be755430c356d1"}
  registry=load_registry()
  tiers=[{"upper_bound":x.upper_bound,"multiplier":x.multiplier} for x in base.risk_tiers]
  for cap,fingerprint in expected.items():
   accelerator=registry.by_id[f"dynamic_{cap}"].accelerators[0]; params=thaw_json(accelerator.parameters)
   self.assertEqual(accelerator.algorithm_version,base.accelerator_version)
   self.assertEqual(accelerator.configuration_version,paired["caps"][str(cap)]["configuration_version"])
   self.assertEqual(params["risk_tiers"],tiers); self.assertEqual(params["maximum_position_notional_fraction"],cap/100)
   self.assertEqual(accelerator.configuration_fingerprint,fingerprint)
if __name__=="__main__": unittest.main()
