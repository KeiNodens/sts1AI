"""sts1 advisor pack + card_kb1 の回帰テスト."""
import os, sys, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from advisor.pack import build_pack, assert_llm_safe   # noqa: E402
from advisor.kb1 import CardKB1                       # noqa: E402


def _combat_state(hand, monsters, en=3):
    return {
        "available_commands": ["play", "end", "state"],
        "game_state": {
            "screen_type": "NONE", "room_type": "MonsterRoom",
            "floor": 1, "act": 1,
            "current_hp": 80, "max_hp": 80, "gold": 99,
            "class": "IRONCLAD", "deck": [],
            "combat_state": {
                "turn": 1,
                "player": {"energy": en, "current_hp": 80,
                           "max_hp": 80, "block": 0, "powers": []},
                "hand": hand, "draw_pile": [], "discard_pile": [],
                "exhaust_pile": [], "monsters": monsters}}}


def _card(cid, cost, ctype="ATTACK", tgt=True):
    return {"id": cid, "cost": cost, "type": ctype,
            "is_playable": True, "has_target": tgt}


def _mob(hp=50, intent="ATTACK", dmg=6, hits=1):
    return {"id": "Cultist", "name": "x", "current_hp": hp, "max_hp": hp,
            "block": 0, "intent": intent, "move_base_damage": dmg,
            "move_hits": hits, "powers": [], "is_gone": False,
            "half_dead": False}


class TestKB(unittest.TestCase):
    def test_strike(self):
        fx = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json")).cards["Strike_R"]["fx"]
        self.assertEqual(fx, [{"op": "damage", "n": 6, "tgt": "enemy"}])

    def test_bash(self):
        fx = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json")).cards["Bash"]["fx"]
        self.assertIn({"op": "apply_power", "n": 2, "tgt": "enemy",
                       "power": "Vulnerable"}, fx)

    def test_mod_card_unknown_keeps_mod_var(self):
        fx, un, prov = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json")).fx_for({"id": "MOD_XYZ_123"})
        self.assertTrue(un)
        self.assertEqual(prov, "unknown")

    def test_rule_fx_replace(self):
        # rules1.json: Limit Break → power_multiply
        fx, un, prov = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json")).fx_for({"id": "Limit Break"})
        self.assertIn({"op": "power_multiply", "n": 2, "tgt": "self",
                       "power": "Strength", "rule": True}, fx)
        self.assertFalse(un)

    def test_rule_fx_add_keeps_static(self):
        # fx_add は静的效果にルールを追加する
        fx, un, prov = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json")).fx_for({"id": "Perfected Strike"})
        ops = [f["op"] for f in fx]
        self.assertIn("damage", ops)
        self.assertIn("conditional_bonus", ops)

    def test_power_type_normalized(self):
        kb = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json"))
        self.assertEqual(kb.power_type("Vulnerable"), "debuff")
        # "Corpse Explosion" / "CorpseExplosionPower" 系の表記ゆれ
        self.assertIsNotNone(kb.power_type("Dexterity"))

    def test_debuff_flag_annotated(self):
        # powers メタから debuff フラグが付く(敵弱化の加点方向用)
        fx, _, _ = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json")).fx_for({"id": "Bash"})
        vul = [f for f in fx if f.get("power") == "Vulnerable"]
        self.assertTrue(vul and vul[0].get("debuff") is True)


class TestPack(unittest.TestCase):
    def test_fx_attached_and_safe(self):
        kb = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json"))
        st = _combat_state([_card("Strike_R", 1), _card("Bash", 2)],
                           [_mob(hp=50)])
        pack = build_pack(st, kb)
        h0 = pack["combat"]["hand"][0]
        self.assertEqual(h0["fx"][0]["n"], 6)
        self.assertEqual(h0["prov"], "static")
        self.assertFalse(assert_llm_safe(pack))

    def test_lethal_plan(self):
        kb = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json"))
        st = _combat_state([_card("Strike_R", 1), _card("Bash", 2),
                            _card("Defend_R", 1, "SKILL", False)],
                           [_mob(hp=14)])
        adv = build_pack(st, kb)["advice"]
        self.assertEqual(adv["max_dmg"], 14.0)
        self.assertEqual(adv["lethal"], [0])
        ids = [p["id"] for p in adv["plan"] if p["act"] == "play_card"]
        self.assertIn("Bash", ids)
        self.assertIn("Strike_R", ids)

    def test_enemy_index_zero_target(self):
        kb = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json"))
        st = _combat_state([_card("Strike_R", 1)], [_mob(hp=50)])
        adv = build_pack(st, kb)["advice"]
        play = [p for p in adv["plan"] if p["act"] == "play_card"]
        self.assertEqual(play[0]["tgt"], 0)

    def test_card_reward_options(self):
        kb = CardKB1.load(path=str(Path(__file__).parent / "fixtures/knowledge.json"))
        st = {"available_commands": ["choose", "proceed"],
              "game_state": {"screen_type": "COMBAT_REWARD",
                             "room_type": "MonsterRoom", "floor": 1,
                             "act": 1, "current_hp": 80, "max_hp": 80,
                             "gold": 0, "class": "IRONCLAD", "deck": [],
                             "choice_list": ["a", "b"]}}
        pack = build_pack(st, kb)
        self.assertEqual(len(pack["options"]), 2)
        self.assertFalse(assert_llm_safe(pack))


if __name__ == "__main__":
    unittest.main()
