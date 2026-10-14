import tempfile
from pathlib import Path
import unittest
from advisor.kb1 import CardKB1, SEED
from advisor.pack import build_pack
from test_pack import _combat_state, _card, _mob

class TestStandalone(unittest.TestCase):
    def test_evaluator_is_bundled_and_works_with_seed_only(self):
        pack = build_pack(_combat_state([_card("Strike_R", 1)], [_mob(hp=5)]), CardKB1())
        self.assertNotIn("advice_err", pack)
        self.assertIn(0, pack["advice"]["lethal"])

    def test_custom_knowledge_path_is_used_for_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "custom.json"
            kb = CardKB1.load(path=str(p))
            kb.record("TEST_CARD", [{"op": "block", "n": 7}], "observed", 0.65)
            kb.save()
            self.assertTrue(p.exists())
            self.assertEqual(CardKB1.load(path=str(p)).lookup("TEST_CARD")["conf"], 0.65)

    def test_seed_records_are_not_shared_between_instances(self):
        a, b = CardKB1(), CardKB1()
        a.cards["Strike_R"]["fx"][0]["n"] = 999
        self.assertEqual(b.cards["Strike_R"]["fx"][0]["n"], 6)
        self.assertEqual(SEED["Strike_R"]["fx"][0]["n"], 6)
