"""decision pack の advice.plan を Communication Mod コマンドで実行するドライバ。

プロトコル注意:
- PLAY は **1-based**。state の hand 配列は 0-based → 送信時に +1 する。
- PLAY の敵 index は 0-based(pack の敵 "e" と同じ)。
- コマンド実行後の state 反映は非同期。TiS co-op では数秒遅れることがある。
- 手札 index はプレイのたびにずれる → id で毎回再解決する。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from .pack import build_pack
from .kb1 import CardKB1

BASE = os.environ.get("STS1_BRIDGE_BASE", "http://127.0.0.1:15531")


def state() -> dict | None:
    try:
        with urllib.request.urlopen(BASE + "/state", timeout=5) as r:
            return json.loads(r.read() or b"null")
    except Exception:
        return None


def cmd(line: str) -> bool:
    try:
        req = urllib.request.Request(
            BASE + "/cmd", data=json.dumps({"line": line}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _sig(st) -> str:
    """変化検知用の軽量シグネチャ"""
    try:
        return json.dumps(st, sort_keys=True)[:8000]
    except Exception:
        return repr(st)


def wait_change(prev, timeout: float = 4.0, poll: float = 0.3):
    """コマンド後に state が変わるまで待つ。変われば新 state。"""
    s0 = _sig(prev)
    t = time.time() + timeout
    while time.time() < t:
        st = state()
        if st is not None and _sig(st) != s0:
            return st
        time.sleep(poll)
    return state()


def _hand(st) -> list:
    return (((st or {}).get("game_state") or {}).get("combat_state") or {}) \
        .get("hand") or []


def _find_hand_i(st, card_id: str) -> int | None:
    for i, c in enumerate(_hand(st)):
        if c.get("id") == card_id:
            return i
    return None


def play_turn(pack: dict, st0: dict, sleep: float = 0.6,
              obs=None) -> list[dict]:
    """advice.plan を実行する。st0 = 現在の生 state。
    obs(observe1.Recorder) を渡すと各 play の前後 state を記録する。"""
    log: list[dict] = []
    st = st0
    for step in (pack.get("advice") or {}).get("plan") or []:
        act = step.get("act")
        if act == "end_turn":
            ok = cmd("END")
            log.append({"step": step, "ok": ok})
            st = wait_change(st, timeout=6.0)
            break
        if act != "play_card":
            continue
        i0 = _find_hand_i(st, step.get("id"))
        if i0 is None:
            log.append({"step": step, "ok": False, "err": "card gone"})
            continue
        line = f"PLAY {i0 + 1}"
        if step.get("tgt") is not None:
            line += f" {step['tgt']}"
        if obs is not None:
            obs.before(step.get("id"), st)
        ok = cmd(line)
        log.append({"step": {**step, "play_i": i0 + 1}, "ok": ok})
        st = wait_change(st)
        if obs is not None and ok:
            obs.after(st)
        time.sleep(sleep)
    return log


def run_turn(kb: CardKB1 | None = None, sleep: float = 0.6,
             obs=None) -> dict:
    """state → pack → (戦闘なら plan 実行 / それ以外は先頭選択肢ヒント)。"""
    st = state()
    if st is None:
        return {"error": "no state"}
    pack = build_pack(st, kb or CardKB1.load())
    if "combat" in pack:
        pack["log"] = play_turn(pack, st, sleep=sleep, obs=obs)
    else:
        opts = pack.get("options") or []
        if opts:
            pack["hint"] = opts[0]
    return pack


def choose(i: int) -> bool:
    return cmd(f"CHOOSE {i}")


def confirm() -> bool:
    return cmd("CONFIRM")


def proceed() -> bool:
    return cmd("PROCEED")


def cancel() -> bool:
    return cmd("CANCEL")
