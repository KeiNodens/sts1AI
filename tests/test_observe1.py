"""observe1 (観測フィードバック) の回帰テスト."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from advisor import observe1                              # noqa: E402
from advisor.kb1 import CardKB1                           # noqa: E402


def _combat(hand_n=5, monsters=None, hp=80, blk=0, en=3,
            pw=None, orbs=None, draw_n=5):
    return {"game_state": {"combat_state": {
        "player": {"energy": en, "current_hp": hp, "max_hp": 80,
                   "block": blk, "powers": pw or [], "orbs": orbs or []},
        "hand": [{"id": f"c{i}"} for i in range(hand_n)],
        "draw_pile": [{"id": "d"}] * draw_n,
        "discard_pile": [], "exhaust_pile": [],
        "monsters": monsters or []}}}


def _mob(hp=50, blk=0, pw=None, gone=False):
    return {"id": "Cultist", "current_hp": hp, "max_hp": 60,
            "block": blk, "intent": "ATTACK", "move_base_damage": 6,
            "move_hits": 1, "powers": pw or [], "is_gone": gone}


def _pw(pid, n):
    return {"id": pid, "amount": n, "name": "x"}


class TestDiff(unittest.TestCase):
    def test_damage_and_debuff(self):
        s0 = _combat(monsters=[_mob(hp=50)])
        s1 = _combat(hand_n=4, en=2,
                     monsters=[_mob(hp=44, pw=[_pw("Vulnerable", 1)])])
        fx = observe1._diff(observe1._snap(s0), observe1._snap(s1))
        self.assertIn({"op": "damage", "n": 6, "tgt": "enemy"}, fx)
        self.assertIn({"op": "apply_power", "power": "Vulnerable",
                       "n": 1, "tgt": "enemy"}, fx)

    def test_block_and_draw(self):
        s0 = _combat(monsters=[_mob()])
        # 5枚 → play で 4枚 → draw で 5枚 (net +0, +1 補正で draw=1)
        s1 = _combat(hand_n=5, blk=8, en=2, monsters=[_mob()])
        fx = observe1._diff(observe1._snap(s0), observe1._snap(s1))
        self.assertIn({"op": "block", "n": 8, "tgt": "self"}, fx)
        self.assertIn({"op": "draw", "n": 1}, fx)

    def test_gain_energy(self):
        s0 = _combat(monsters=[_mob()])
        s1 = _combat(hand_n=4, en=4, monsters=[_mob()])
        fx = observe1._diff(observe1._snap(s0), observe1._snap(s1))
        self.assertIn({"op": "gain_energy", "n": 1}, fx)

    def test_channel_evoke(self):
        s0 = _combat(monsters=[_mob()],
                     orbs=[{"id": "Lightning", "passive_amount": 3,
                            "evoke_amount": 8}])
        s1 = _combat(hand_n=4, en=2, monsters=[_mob()], orbs=[])
        fx = observe1._diff(observe1._snap(s0), observe1._snap(s1))
        self.assertIn({"op": "evoke", "n": 1}, fx)

    def test_aoe_damage(self):
        s0 = _combat(monsters=[_mob(hp=50), _mob(hp=30)])
        s1 = _combat(hand_n=4, en=2,
                     monsters=[_mob(hp=44), _mob(hp=24)])
        fx = observe1._diff(observe1._snap(s0), observe1._snap(s1))
        self.assertIn({"op": "damage", "n": 6, "tgt": "all_enemies"}, fx)

    def test_dead_mob_still_damage(self):
        s0 = _combat(monsters=[_mob(hp=6), _mob(hp=50)])
        s1 = _combat(hand_n=4, en=2,
                     monsters=[_mob(hp=0, gone=True), _mob(hp=50)])
        fx = observe1._diff(observe1._snap(s0), observe1._snap(s1))
        self.assertIn({"op": "damage", "n": 6, "tgt": "enemy"}, fx)


class TestAggregateFlush(unittest.TestCase):
    def test_median(self):
        fx = observe1.aggregate([
            [{"op": "damage", "n": 6, "tgt": "enemy"}],
            [{"op": "damage", "n": 10, "tgt": "enemy"}],
            [{"op": "damage", "n": 8, "tgt": "enemy"}]])
        self.assertEqual(fx, [{"op": "damage", "n": 8, "tgt": "enemy"}])

    def test_flush_records_new(self):
        kb = CardKB1({})
        rec = observe1.Recorder()
        rec.samples["MOD_CARD_X"] = [
            [{"op": "damage", "n": 6, "tgt": "enemy"}]]
        summary = rec.flush(kb)
        self.assertEqual(summary["recorded"], ["MOD_CARD_X"])
        ent = kb.cards["MOD_CARD_X"]
        self.assertEqual(ent["prov"], "observed")
        self.assertAlmostEqual(ent["conf"], 0.65)
        self.assertEqual(ent["obs_n"], 1)
        self.assertFalse(rec.samples)

    def test_flush_no_overwrite_high_conf(self):
        kb = CardKB1({})
        kb.cards["Bash"] = {"fx": [{"op": "damage", "n": 100}],
                            "prov": "dll", "conf": 0.95}
        rec = observe1.Recorder()
        rec.samples["Bash"] = [[{"op": "damage", "n": 6, "tgt": "enemy"}]]
        summary = rec.flush(kb)
        self.assertEqual(summary["conflicted"], ["Bash"])
        ent = kb.cards["Bash"]
        self.assertEqual(ent["fx"], [{"op": "damage", "n": 100}])
        self.assertEqual(ent["obs"], [{"op": "damage", "n": 6,
                                       "tgt": "enemy"}])
        self.assertEqual(ent["obs_n"], 1)

    def test_lookup_record_prefixed(self):
        kb = CardKB1({})
        kb.cards["Danheng0"] = {"fx": [], "prov": "vars", "conf": 0.5}
        self.assertIsNotNone(kb.lookup("HSRMod:Danheng0"))
        key = kb.record("HSRMod:Danheng0",
                        [{"op": "damage", "n": 6}], "observed", 0.65)
        self.assertEqual(key, "Danheng0")  # prefix 付き二重エントリを作らない
        self.assertNotIn("HSRMod:Danheng0", kb.cards)


class TestRecorder(unittest.TestCase):
    def test_before_after(self):
        rec = observe1.Recorder()
        s0 = _combat(monsters=[_mob(hp=50)])
        rec.before("Strike_R", s0)
        s1 = _combat(hand_n=4, en=2, monsters=[_mob(hp=44)])
        rec.after(s1)
        self.assertIn("Strike_R", rec.samples)
        self.assertEqual(rec.samples["Strike_R"][0],
                         [{"op": "damage", "n": 6, "tgt": "enemy"}])

    def test_no_card_no_sample(self):
        rec = observe1.Recorder()
        rec.before(None, _combat())
        rec.after(_combat())
        self.assertFalse(rec.samples)


if __name__ == "__main__":
    unittest.main()
