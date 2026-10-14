"""観測フィードバック — カードプレイ前後の state 差分から実効果を推定する。

sts2 advisor/observe.py の StS1(Communication Mod) 移植版。
静的 KB やキュレーションが間違っていても、「実際に撃ったら何が
起きたか」から効果シグネチャを推定して card_kb1.json に書き戻す。

帰属は曖昧(毒ティック・オーブ受動・敵カウンター・co-op 相手の
介入が差分に混ざる)ので conf は観測数で 0.65〜0.85 にスケールし、
dll 解析(0.9 以上)より下に置く。高 conf エントリと矛盾する場合は
上書きせず entry["obs"] に留め置く。

使い方:
    obs = Recorder()
    obs.before(card_id, state)   # play 直前の生 state
    obs.after(state)             # play 完了後の生 state
    obs.flush(kb, path="card_kb1.json")  # 集約して KB へ書き戻す
"""
from __future__ import annotations

import statistics


def _powers(lst: list | None) -> dict:
    return {p.get("id"): p.get("amount") or 0
            for p in lst or [] if p.get("id")}


def _snap(state: dict) -> dict:
    """差分計算用に必要なフィールドだけを抽出する。"""
    cs = ((state or {}).get("game_state") or {}).get("combat_state") or {}
    p = cs.get("player") or {}
    enems = {}
    for i, e in enumerate(cs.get("monsters") or []):
        # is_gone の死体も残す — hp→0 で死んだ敵を除外すると
        # リーサル分のダメージが観測から抜け落ちる
        enems[i] = {
            "hp": e.get("current_hp") or 0,
            "blk": e.get("block") or 0,
            "pw": _powers(e.get("powers")),
        }
    orbs = [o for o in (p.get("orbs") or []) if o.get("id")]
    return {
        "hp": p.get("current_hp") or 0,
        "blk": p.get("block") or 0,
        "en": p.get("energy") or 0,
        "pw": _powers(p.get("powers")),
        "orbs": len(orbs),
        "hand": len(cs.get("hand") or []),
        "draw": len(cs.get("draw_pile") or []),
        "enems": enems,
    }


def _diff(s0: dict, s1: dict) -> list[dict]:
    """2スナップショットの差分を効果シグネチャ風の fx リストにする。"""
    fx: list[dict] = []

    # 敵へのダメージ(ブロック削り + HP 削りの合算を実ダメージ近似)
    hits = {}
    for eid, e1 in s1["enems"].items():
        e0 = s0["enems"].get(eid)
        if e0 is None:
            continue
        lost = max(0, (e0["blk"] - e1["blk"])) + max(0, (e0["hp"] - e1["hp"]))
        if lost > 0:
            hits[eid] = lost
    if hits:
        if len(hits) == len(s0["enems"]) and len(s0["enems"]) > 1:
            fx.append({"op": "damage", "n": max(hits.values()),
                       "tgt": "all_enemies"})
        else:
            fx.append({"op": "damage", "n": max(hits.values()),
                       "tgt": "enemy"})
        for eid, e1 in s1["enems"].items():
            e0 = s0["enems"].get(eid)
            if e0 and e1["hp"] > e0["hp"]:
                fx.append({"op": "heal", "n": e1["hp"] - e0["hp"],
                           "tgt": "enemy"})

    # 敵パワーの増加/新規付与 → apply_power tgt=enemy
    for eid, e1 in s1["enems"].items():
        e0 = s0["enems"].get(eid, {"pw": {}})
        for pw, n in e1["pw"].items():
            d = n - (e0["pw"].get(pw) or 0)
            if d > 0:
                fx.append({"op": "apply_power", "power": pw, "n": d,
                           "tgt": "enemy"})

    # 自分
    d_blk = s1["blk"] - s0["blk"]
    if d_blk > 0:
        fx.append({"op": "block", "n": d_blk, "tgt": "self"})
    d_hp = s1["hp"] - s0["hp"]
    if d_hp > 0:
        fx.append({"op": "heal", "n": d_hp, "tgt": "self"})
    elif d_hp < 0:
        fx.append({"op": "lose_hp", "n": -d_hp, "tgt": "self"})
    # コスト消費を差し引いた正味のエネルギー増のみ記録(保守的)
    if s1["en"] > s0["en"]:
        fx.append({"op": "gain_energy", "n": s1["en"] - s0["en"]})
    # 手札増 = ドロー近似(プレイしたカード1枚分を戻して補正)
    drawn = s1["hand"] - s0["hand"] + 1
    if drawn > 0:
        fx.append({"op": "draw", "n": drawn})
    for pw, n in s1["pw"].items():
        d = n - (s0["pw"].get(pw) or 0)
        if d > 0:
            fx.append({"op": "apply_power", "power": pw, "n": d,
                       "tgt": "self"})

    # オーブ(Defect): スロット数の増減 → channel / evoke
    d_orb = s1["orbs"] - s0["orbs"]
    if d_orb > 0:
        fx.append({"op": "channel", "n": d_orb})
    elif d_orb < 0:
        fx.append({"op": "evoke", "n": -d_orb})
    return fx


def _key(fx: dict) -> tuple:
    return (fx.get("op"), fx.get("tgt"), fx.get("power"), fx.get("pool"))


def aggregate(samples: list[list[dict]]) -> list[dict]:
    """同一カードの複数観測を (op,tgt,power) 単位で中央値集約する。"""
    groups: dict[tuple, list] = {}
    for fx_list in samples:
        seen = set()
        for fx in fx_list:
            k = _key(fx)
            if k in seen:  # 同一観測内の重複は1つに
                continue
            seen.add(k)
            groups.setdefault(k, []).append(fx.get("n") or 0)
    out = []
    for (op, tgt, pw, pool), vals in sorted(groups.items()):
        e: dict = {"op": op}
        if vals:
            e["n"] = statistics.median(vals)
        if tgt:
            e["tgt"] = tgt
        if pw:
            e["power"] = pw
        if pool:
            e["pool"] = pool
        out.append(e)
    return out


def conf_for(samples: int) -> float:
    """観測数 → conf。差分帰属は曖昧なので上限 0.85(dll 0.9 未満)。"""
    return min(0.85, 0.55 + 0.1 * samples)


class Recorder:
    """play_turn / MCP play_card に差し込んで実効果を観測する。"""

    def __init__(self) -> None:
        self.samples: dict[str, list[list[dict]]] = {}
        self._pre: tuple[str, dict] | None = None

    def before(self, card_id: str | None, state: dict) -> None:
        if not card_id:
            self._pre = None
            return
        self._pre = (card_id, _snap(state))

    def after(self, state: dict) -> None:
        if self._pre is None:
            return
        cid, s0 = self._pre
        self._pre = None
        fx = _diff(s0, _snap(state))
        if fx:
            self.samples.setdefault(cid, []).append(fx)

    def signatures(self) -> dict[str, list[dict]]:
        return {cid: aggregate(fxs) for cid, fxs in self.samples.items()}

    def flush(self, kb, path: str | None = None) -> dict:
        """集約シグネチャを KB に書き戻す。結果サマリを返す。"""
        summary = {"recorded": [], "conflicted": [], "skipped": []}
        for cid, fxs in self.samples.items():
            fx = aggregate(fxs)
            conf = conf_for(len(fxs))
            cur = kb.lookup(cid)
            if cur is None or (cur.get("conf") or 0) <= conf:
                key = kb.record(cid, fx, "observed", conf)
                kb.cards[key]["obs_n"] = len(fxs)
                summary["recorded"].append(key)
            else:
                cur["obs"] = fx
                cur["obs_n"] = cur.get("obs_n", 0) + len(fxs)
                summary["conflicted"].append(cid)
        self.samples.clear()
        if path:
            kb.save(path)
        return summary
