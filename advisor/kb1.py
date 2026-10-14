"""StS1 card knowledge base — card id → 効果シグネチャ.

StS1 の Communication Mod state にはカードのダメージ値が載らないので、
id→fx の静的 KB が必須。バニラカードは jar 解析で自動生成予定、
当面は主要カードを手書き + 名前推定で補う。
"""
from __future__ import annotations

import copy
import json
import os
import re

KB_PATH = os.environ.get("STS1_KB_PATH", os.path.join(os.getcwd(), "card_kb1.json"))

# id → {"fx":[...], "note":...} 手書きシード(バニラ主要カード)
SEED = {
    "Strike_R": {"fx": [{"op": "damage", "n": 6, "tgt": "enemy"}]},
    "Defend_R": {"fx": [{"op": "block", "n": 5, "tgt": "self"}]},
    "Bash": {"fx": [{"op": "damage", "n": 8, "tgt": "enemy"},
                    {"op": "apply_power", "n": 2, "power": "Vulnerable",
                     "tgt": "enemy"}]},
    "Neutralize": {"fx": [{"op": "damage", "n": 3, "tgt": "enemy"},
                          {"op": "apply_power", "n": 1, "power": "Weak",
                           "tgt": "enemy"}]},
    "Survivor": {"fx": [{"op": "block", "n": 8, "tgt": "self"},
                        {"op": "discard", "n": 1}]},
    "Zap": {"fx": [{"op": "channel", "n": 1, "orb": "Lightning"}]},
    "Dualcast": {"fx": [{"op": "evoke", "n": 2}]},
    "Eruption": {"fx": [{"op": "damage", "n": 9, "tgt": "enemy"},
                        {"op": "enter_stance", "n": 1, "stance": "Wrath"}]},
    "Vigilance": {"fx": [{"op": "block", "n": 8, "tgt": "self"},
                         {"op": "enter_stance", "n": 1, "stance": "Calm"}]},
}

# 名前推定(バニラは id が英語名)
_HINTS = [
    (re.compile(r"strike", re.I), [{"op": "damage", "n": 6, "tgt": "enemy"}]),
    (re.compile(r"defend|protect|guard", re.I),
     [{"op": "block", "n": 5, "tgt": "self"}]),
    (re.compile(r"draw|scribe", re.I), [{"op": "draw", "n": 1}]),
]


class CardKB1:
    def __init__(self, data: dict | None = None,
                 rules: dict | None = None):
        self.cards: dict = copy.deepcopy(SEED)
        self.powers: dict = {}
        if data:
            self.cards.update(data.get("cards", {}))
            self.powers.update(data.get("powers", {}))
        self.path = KB_PATH
        rules = rules or {}
        self.power_rules = rules.get("power_rules", {})
        self.card_rules = rules.get("card_rules", {})
        # per-mod キュレーション: mods.<mod名>.{cards,powers,resources}
        # KB エントリの "mod" フィールドと照合して適用
        self.mod_rules = rules.get("mods", {})
        self.resources = {}  # {mod: {pool名: 説明}} — 独自リソースの意味メモ
        self.powers.update(
            {k: v.get("type") for k, v in self.power_rules.items()
             if v.get("type") in ("buff", "debuff")})
        for mname, msec in self.mod_rules.items():
            self.resources[mname] = msec.get("resources", {})
            for k, v in (msec.get("powers") or {}).items():
                if v.get("type") in ("buff", "debuff"):
                    self.powers[k] = v["type"]

    @classmethod
    def load(cls, path: str | None = None,
             rules_path: str | None = None) -> "CardKB1":
        data = None
        p = path or KB_PATH
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = None
        rules = None
        rp = rules_path or os.path.join(os.path.dirname(__file__),
                                        "rules1.json")
        if os.path.exists(rp):
            try:
                with open(rp, encoding="utf-8") as f:
                    rules = json.load(f)
            except Exception:
                rules = None
        kb = cls(data, rules)
        kb.path = p
        return kb

    _NORM_PW = re.compile(r'(?i)(power)$')

    def _norm_key(self, pid: str) -> str:
        """'Corpse Explosion'/'CorpseExplosionPower' → 'corpsexplosion'"""
        s = self._NORM_PW.sub('', (pid or '').replace(' ', '')
                            .replace('_', ''))
        return s.lower()

    def power_type(self, pid: str | None) -> str | None:
        """power id → 'buff'|'debuff'|None(不明)。表記ゆれは正規化して照合。"""
        if not pid:
            return None
        if not hasattr(self, "_pn"):
            self._pn = {self._norm_key(k): v
                        for k, v in self.powers.items()}
        return self.powers.get(pid) or self._pn.get(self._norm_key(pid))

    def _annotate(self, fx_list: list) -> list:
        """apply_power に debuff フラグを付与(評価の加点方向用)。"""
        for fx in fx_list:
            if fx.get("op") == "apply_power":
                t = self.power_type(fx.get("power"))
                if t:
                    fx["debuff"] = (t == "debuff")
        return fx_list

    def _resolve(self, cid: str | None):
        """live card.id → KB エントリ。実機 ID は 'modid:X' 形式、
        KB キーは prefix 無しが多い → bare 名で逆引きする。
        衝突時は ':' を含まない(基底側の)エントリを優先。"""
        if not cid:
            return None, None
        ent = self.cards.get(cid)
        if ent:
            return cid, ent
        if not hasattr(self, "_bare"):
            self._bare = {}
            for k in self.cards:
                self._bare.setdefault(
                    k.split(":")[-1].lower(), []).append(k)
        bare = cid.split(":")[-1].lower()
        cands = self._bare.get(bare) or []
        if len(cands) == 1:
            return cands[0], self.cards[cands[0]]
        if cands:
            pick = next((k for k in cands if ":" not in k), sorted(cands)[0])
            return pick, self.cards[pick]
        return None, None

    def _rules_for(self, cid: str, ent: dict | None) -> list:
        """global card_rules + KB の mod フィールド経由の per-mod ルール。"""
        out = []
        if cid in self.card_rules:
            out.append(self.card_rules[cid])
        if ent and ent.get("mod"):
            mc = (self.mod_rules.get(ent["mod"]) or {}).get("cards", {})
            if cid in mc:
                out.append(mc[cid])
        return out

    def fx_for(self, card: dict):
        """card → (fx, unknown_vars, provenance)."""
        cid = card.get("id")
        kb_key, ent = self._resolve(cid)
        rules = self._rules_for(kb_key or cid, ent)
        if ent:
            fx = list(ent.get("fx", []))
            for rule in rules:
                if rule.get("fx_replace"):  # 後勝ち(mod 固有が最終優先)
                    fx = [dict(x, rule=True) for x in rule["fx_replace"]]
            for rule in rules:
                fx += [dict(x, rule=True) for x in rule.get("fx_add", [])]
            return (self._annotate(fx), [], ent.get("prov", "static"))
        for rule in rules:
            fx = [dict(x, rule=True) for x in
                  (rule.get("fx_replace") or rule.get("fx_add") or [])]
            if fx:
                return (self._annotate(fx), [], "rule")
        base = (cid or "").replace("+", "").replace("_R", "")
        for pat, fx in _HINTS:
            if pat.search(base):
                return (self._annotate(
                    [dict(x, guess=True) for x in fx]), [], "guess")
        return ([{"op": "mod_var", "n": 0, "guess": True}], [cid or "?"],
                "unknown")

    def lookup(self, cid: str | None):
        """cid → KB エントリ(dict) or None。prefix フォールバック込み。"""
        _key, ent = self._resolve(cid)
        return ent

    def record(self, cid: str, fx: list, prov: str, conf: float) -> str:
        """fx シグネチャを記録して実際に書いた KB キーを返す。
        live id が既存エントリに解決できる場合はそちらへ書く
        (bare/modid: 二重エントリ化を防ぐ)。"""
        key, _ent = self._resolve(cid)
        k = key or cid
        ent = self.cards.get(k) or {}
        ent["fx"] = fx
        ent["prov"] = prov
        ent["conf"] = conf
        self.cards[k] = ent
        return k

    def save(self, path: str | None = None) -> None:
        """cards を card_kb1.json に書き戻す。powers/mods/schema は
        ファイル値を温存する(rules 由来の合成値は書き戻さない)。"""
        p = path or self.path
        data = {}
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["cards"] = self.cards
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
