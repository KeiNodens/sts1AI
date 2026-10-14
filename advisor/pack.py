"""StS1 Communication Mod state → decision pack (StS2 pack と同構造).

同梱の advisor.eval が評価できる形に畳む。
違い:
- カードに vars が無い → 効果は card_kb1.json (id→fx) から引く
- intent は intent 名 + move_base_damage/move_hits で直接取れる
- enemies は entity_id ではなく配列 index (0-based) で識別
- map は {x,y,symbol,children} 構造
"""
from __future__ import annotations

import re
from .kb1 import CardKB1

BLOCKED_KEYS = frozenset({
    "description", "title", "label", "body", "name", "keywords",
    "relic_description", "potion_description", "card_description",
    "flavor", "text",
})

_ATTACK_INTENTS = {"Attack", "SingleAttack", "MultiAttack", "AttackDebuff",
                   "AttackBuff", "DeathBlow"}

# StS1 intent 名 → StS2 pack で使う k 名
_INTENT_MAP = {
    "ATTACK": "Attack", "ATTACK_BUFF": "AttackBuff",
    "ATTACK_DEBUFF": "AttackDebuff", "ATTACK_DEFEND": "Attack",
    "DEFEND": "Block", "DEFEND_BUFF": "Block", "DEFEND_DEBUFF": "Debuff",
    "BUFF": "Buff", "DEBUFF": "Debuff", "STRONG_DEBUFF": "StrongDebuff",
    "DEBUFF_DEBUFF": "Debuff", "ESCAPE": "Escape", "SLEEP": "Sleep",
    "STUN": "Stun", "DEBUG": "Debug", "UNKNOWN": "Unknown", "NONE": "Unknown",
}


def _num(v, default=0):
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else v
    return default


def _power_map(powers) -> dict:
    out = {}
    for p in powers or []:
        pid = p.get("id") or p.get("name")
        if not pid:
            continue
        out[pid] = {"n": _num(p.get("amount")), "t": p.get("type")}
    return out


def _intent_pack(m: dict) -> dict:
    itype = (m.get("intent") or "UNKNOWN").upper()
    k = _INTENT_MAP.get(itype, itype.title().replace("_", ""))
    out = {"k": k}
    if k.startswith("Attack") or k == "Attack":
        dmg = m.get("move_base_damage")
        hits = m.get("move_hits") or 1
        if dmg and dmg > 0:
            out["dmg"], out["hits"] = int(dmg), int(hits)
    return out


def _enemy_pack(i: int, m: dict) -> dict:
    return {
        "e": i,
        "id": m.get("id"),
        "hp": _num(m.get("current_hp")),
        "max_hp": _num(m.get("max_hp")),
        "blk": _num(m.get("block")),
        "gone": m.get("is_gone") or m.get("half_dead"),
        "int": [_intent_pack(m)],
        "pw": _power_map(m.get("powers")),
    }


def _hand_card(c: dict, i: int, kb: CardKB1) -> dict:
    fx, un, prov = kb.fx_for(c)
    e = {
        "i": i,                 # 0-based(内部)。PLAY には i+1 を使う
        "id": c.get("id"),
        "t": c.get("type"),
        "c": c.get("cost"),
        "up": (c.get("upgrades") or 0) > 0,
        "play": bool(c.get("is_playable", True)),
        "tgt": "enemy" if c.get("has_target") else "self",
        "fx": fx, "prov": prov,
    }
    if c.get("exhausts"):
        e["kw"] = ["Exhaust"]
    if c.get("ethereal"):
        e.setdefault("kw", []).append("Ethereal")
    if un:
        e["un"] = un
    return e


def _combat_pack(gs: dict, kb: CardKB1) -> dict:
    cs = gs.get("combat_state") or {}
    p = cs.get("player") or {}
    return {
        "round": _num(cs.get("turn")),
        "phase": "play",
        "en": _num(p.get("energy")),
        "hp": _num(p.get("current_hp")),
        "max_hp": _num(p.get("max_hp")),
        "blk": _num(p.get("block")),
        "pw": _power_map(p.get("powers")),
        "piles": {
            "draw": len(cs.get("draw_pile") or []),
            "disc": len(cs.get("discard_pile") or []),
            "ex": len(cs.get("exhaust_pile") or []),
        },
        "enemies": [_enemy_pack(i, m) for i, m in
                    enumerate(cs.get("monsters") or [])
                    if not m.get("is_gone")],
        "hand": [_hand_card(c, i, kb) for i, c in
                 enumerate(cs.get("hand") or [])],
    }


def _options_pack(state: dict, kb: CardKB1) -> dict:
    gs = state.get("game_state") or {}
    stype = gs.get("screen_type") or "NONE"
    out: dict = {"options": []}
    cl = gs.get("choice_list") or []
    if stype == "MAP":
        for i, name in enumerate(cl):
            # 名は 'x=N' 形式。選択は CHOOSE <i>
            m = re.match(r"x=(\d+)", str(name))
            out["options"].append({"act": "choose", "i": i,
                                   "node": int(m.group(1)) if m else name})
    elif stype in ("EVENT", "GRID", "CARD_REWARD", "BOSS_REWARD",
                   "COMBAT_REWARD", "SHOP_SCREEN", "REST", "CHEST",
                   "HAND_SELECT", "GAME_OVER"):
        for i, name in enumerate(cl):
            out["options"].append({"act": "choose", "i": i})
    return out


def build_pack(state: dict, kb: CardKB1) -> dict:
    """communication mod /state 応答 → decision pack."""
    if not isinstance(state, dict):
        return {"t": "error"}
    gs = state.get("game_state") or {}
    pack: dict = {
        "t": gs.get("screen_type") or "NONE",
        "room": gs.get("room_type"),
        "act": gs.get("act"), "floor": gs.get("floor"),
        "cmds": state.get("available_commands"),
    }
    if "combat_state" in gs:
        pack["combat"] = _combat_pack(gs, kb)
    pack.update(_options_pack(state, kb))
    pack["me"] = {
        "hp": _num(gs.get("current_hp")), "max_hp": _num(gs.get("max_hp")),
        "gold": _num(gs.get("gold")),
        "deck": len(gs.get("deck") or []),
        "class": gs.get("class"),
    }
    # 同梱の評価器を使用する。他のチェックアウトは不要。
    try:
        eval_combat, eval_options = _load_eval()
        if "combat" in pack:
            pack["advice"] = eval_combat(pack["combat"])
        else:
            adv = eval_options(pack)
            if adv:
                pack["advice"] = adv
    except Exception as e:
        pack["advice_err"] = repr(e)
    return pack


def _load_eval():
    """Load the evaluator bundled with this repository."""
    from .eval import eval_combat, eval_options
    return eval_combat, eval_options


def assert_llm_safe(obj, path="$") -> list:
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in BLOCKED_KEYS:
                bad.append(f"{path}.{k}")
            bad += assert_llm_safe(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += assert_llm_safe(v, f"{path}[{i}]")
    return bad
