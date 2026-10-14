"""StS1 ラン全自動ドライバ — CommMod state をポーリングし画面別に進行する。

- 戦闘            : advisor の run_turn (pack→plan 実行)
- マップ          : 先頭の選択肢 (co-op では各プレイヤーが個別に進む)
- イベント/Neow   : 最後の有効選択肢 (「出る/スキップ」系を優先)
- 報酬            : PROCEED で流す (カード報酬もスキップ)
- ショップ        : LEAVE
- 休憩            : 先頭の選択肢
- グリッド選択    : CHOOSE 0 + CONFIRM
- その他          : choice_list があれば末尾、なければ PROCEED→CONFIRM→CANCEL

環境変数 STS1_BRIDGE_BASE で対象インスタンスを切替
(joiner=15531, host=15532 がバットの既定)。

使い方:
    python -m advisor.auto1            # 200 ステップ上限で実行
    python -m advisor.auto1 --steps 60 --sleep 1.0
"""
from __future__ import annotations

import argparse
import os
import time

from . import drive1
from .kb1 import CardKB1
from . import observe1


def _gs(st: dict) -> dict:
    return (st or {}).get("game_state") or {}


def _choices(gs: dict) -> list:
    return gs.get("choice_list") or []


def _choose(gs: dict, prefer_last: bool = True) -> str:
    """choice_list から選ぶ。戻り値は実行したコマンド説明。"""
    ch = _choices(gs)
    if not ch:
        return ""
    i = len(ch) - 1 if prefer_last else 0
    drive1.choose(i)
    return f"CHOOSE {i} ({ch[i] if isinstance(ch[i], str) else '?'})"


def step(kb: CardKB1, obs: observe1.Recorder | None = None
         ) -> tuple[str, dict]:
    """1 回のポーリング+行動。戻り値は (何をしたか, 生 state)。"""
    st = drive1.state()
    if st is None:
        return "no-state", {}
    gs = _gs(st)
    screen = gs.get("screen_type")
    room = gs.get("room_type")
    phase = gs.get("room_phase")

    if screen == "GAME_OVER" or room == "GameOverRoom" or gs.get("is_game_over"):
        return "GAME_OVER", st

    if phase == "COMBAT" or gs.get("combat_state"):
        r = drive1.run_turn(kb, obs=obs)
        plan = ((r.get("advice") or {}).get("plan") or [])
        return f"combat:{len(plan)}steps", st

    if screen == "MAP":
        return _choose(gs, prefer_last=False) or "map:none", st

    if screen == "EVENT":
        return _choose(gs, prefer_last=True) or "event:none", st

    if screen in ("COMBAT_REWARD", "CARD_REWARD", "BOSS_REWARD",
                  "CHEST", "SHOP_SCREEN", "SHOP"):
        drive1.proceed()
        return f"{screen}:proceed", st

    if screen == "REST":
        return _choose(gs, prefer_last=False) or "rest:proceed", st

    if screen == "GRID":
        drive1.choose(0)
        time.sleep(0.4)
        drive1.confirm()
        return "grid:choose0+confirm", st

    if screen in ("HAND_SELECT",):
        drive1.cancel()
        return "hand_select:cancel", st

    if _choices(gs):
        return _choose(gs, prefer_last=True), st

    # フォールバック: 汎用進行キーを順に試す
    drive1.proceed()
    return f"{screen or room or '?'}:proceed", st


def run(steps: int = 200, sleep: float = 1.0, verbose: bool = True,
        observe: bool = True) -> None:
    kb = CardKB1.load()
    obs = observe1.Recorder() if observe else None
    last_sig, stuck = None, 0
    try:
        for i in range(steps):
            what, st = step(kb, obs)
            gs = _gs(st)
            sig = (gs.get("floor"), gs.get("room_type"),
                   gs.get("screen_type"), gs.get("screen_name"),
                   len(_choices(gs)))
            if verbose:
                print(f"[{i:3d}] f{gs.get('floor')} {gs.get('room_type')}/"
                      f"{gs.get('screen_type')} hp={gs.get('current_hp')}"
                      f" -> {what}", flush=True)
            if what == "GAME_OVER":
                print("run ended (game over)")
                return
            if sig == last_sig:
                stuck += 1
                if stuck >= 8:
                    # 詰まり検知: CANCEL→CONFIRM→キー連打で脱出を試す
                    drive1.cancel()
                    time.sleep(0.3)
                    drive1.confirm()
                    time.sleep(0.3)
                    drive1.cmd("PROCEED")
                    if stuck >= 15:
                        print("stuck; giving up")
                        return
            else:
                stuck = 0
            last_sig = sig
            time.sleep(sleep)
    finally:
        if obs is not None and obs.samples:
            summary = obs.flush(kb, path=kb.path)
            if verbose:
                print(f"observations flushed: {summary}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--no-observe", action="store_true",
                    help="観測フィードバックを無効化")
    args = ap.parse_args()
    run(steps=args.steps, sleep=args.sleep, observe=not args.no_observe)


if __name__ == "__main__":
    main()
