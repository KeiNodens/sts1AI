"""MCP server bridge for Slay the Spire 1 (Communication Mod).

Connects to sts1_bridge.py's HTTP server (spawned by CommunicationMod inside
the game) and exposes game actions as MCP tools for LLM clients.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# advisor package lives at <repo>/advisor (parent of mcp/)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from advisor.kb1 import CardKB1
    from advisor.pack import build_pack
    from advisor import drive1
    from advisor import observe1
    _ADVISOR = True
    _KB = CardKB1.load()
    _OBS = observe1.Recorder()
except Exception:
    _ADVISOR = False
    _KB = None
    _OBS = None

mcp = FastMCP("sts1")

_base_url: str = os.environ.get("STS1_BRIDGE_BASE", "http://127.0.0.1:15531")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0)


async def _state() -> dict:
    async with _client() as c:
        r = await c.get(f"{_base_url}/state")
        r.raise_for_status()
        return r.json()


async def _cmd(line: str) -> dict:
    async with _client() as c:
        r = await c.post(f"{_base_url}/cmd", json={"line": line})
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"ok": r.status_code == 200}


def _handle_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPError):
        return ("Error: Cannot reach sts1_bridge at "
                f"{_base_url}. Is the game running with CommunicationMod?")
    return f"Error: {e}"


def _sanitize(obj):
    """LLM 向け軽量サニタイズ: id を持つ要素の name(文字化け日本語)を削る。

    choice_list / label 等の選択肢テキストは操作に必要なので残す。
    """
    if isinstance(obj, dict):
        has_id = "id" in obj
        return {k: _sanitize(v) for k, v in obj.items()
                if not (k == "name" and has_id)}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _summary(state: dict) -> dict:
    """コマンド応答用の軽量要約 (state 全文は返さない)。"""
    gs = (state or {}).get("game_state") or {}
    out = {
        "screen": gs.get("screen_type"),
        "room": gs.get("room_type"),
        "floor": gs.get("floor"),
        "hp": gs.get("current_hp"),
        "cmds": (state or {}).get("available_commands"),
    }
    cs = gs.get("combat_state")
    if cs:
        out["combat"] = {
            "energy": ((cs.get("player") or {}).get("energy")),
            "hand": len(cs.get("hand") or []),
            "enemies": [{"id": m.get("id"), "hp": m.get("current_hp")}
                        for m in (cs.get("monsters") or [])
                        if not m.get("is_gone")],
        }
    return out


async def _cmd_then_state(line: str) -> str:
    """コマンド送信 → 少し待って state 変化を拾って要約を返す。"""
    try:
        s0 = await _state()
        await _cmd(line)
        sig0 = json.dumps(s0, sort_keys=True)
        for _ in range(12):
            await asyncio.sleep(0.5)
            st = await _state()
            if json.dumps(st, sort_keys=True) != sig0:
                return json.dumps({"sent": line, "ok": True,
                                   "state": _summary(st)}, ensure_ascii=False)
        return json.dumps({"sent": line, "ok": True,
                           "note": "no state change observed",
                           "state": _summary(await _state())},
                          ensure_ascii=False)
    except Exception as e:
        return _handle_error(e)


@mcp.tool()
async def get_game_state() -> str:
    """Get the current game state (sanitized — no raw card/monster name text).

    Card/relic/potion/monster entries keep their `id` (e.g. "Strike_R",
    "HSRMod:Danheng0") which is the stable lookup key. Raw `name` fields are
    stripped since they are Japanese text the LLM does not need.
    """
    try:
        st = await _state()
        return json.dumps(_sanitize(st), ensure_ascii=False)
    except Exception as e:
        return _handle_error(e)


@mcp.tool()
async def get_decision_pack() -> str:
    """Get a compact decision pack — the primary LLM feed.

    Contains NO free-text fields: cards are identified by id and expressed as
    structured effects (damage/block/draw/apply_power ops from static card
    analysis + curation rules), plus advisor output: incoming damage, max
    damage, lethal targets, and a suggested action sequence. Custom mod
    mechanics appear as separate resources (e.g. hsr toughness is
    mod_damage pool=toughness, never mixed into HP lethal math).
    """
    if not _ADVISOR:
        return _handle_error(RuntimeError("advisor package unavailable"))
    try:
        st = await _state()
        pack = await asyncio.to_thread(build_pack, st, _KB)
        return json.dumps(pack, ensure_ascii=False)
    except Exception as e:
        return _handle_error(e)


@mcp.tool()
async def send_command(line: str) -> str:
    """Send a raw Communication Mod command line.

    Commands: PLAY <1-based hand index> [0-based enemy index], END, CHOOSE <i>,
    CONFIRM, PROCEED, SKIP, CANCEL, RETURN, LEAVE, POTION <use|discard> <slot>,
    STATE, KEY <key>, CLICK <x> <y>, WAIT <ms>, START <char>.
    Prefer the dedicated tools (play_card / end_turn / choose / proceed) —
    they are easier to get right. PLAY hand index is 1-based, enemy index
    is 0-based.
    """
    return await _cmd_then_state(line)


@mcp.tool()
async def play_card(card_id: str, target_index: int | None = None) -> str:
    """Play a card by its `id` from hand (re-resolves the hand index).

    Args:
        card_id: card `id` field from state/decision_pack (e.g. "Strike_R").
        target_index: 0-based enemy index for targeted attacks (omit for
                      non-targeted cards like Defend).
    """
    try:
        st = await _state()
        hand = (((st.get("game_state") or {}).get("combat_state") or {})
                .get("hand") or [])
        idx = next((i for i, c in enumerate(hand) if c.get("id") == card_id),
                   None)
        if idx is None:
            return json.dumps({"ok": False,
                               "error": f"card {card_id} not in hand",
                               "hand": [c.get("id") for c in hand]})
        line = f"PLAY {idx + 1}"
        if target_index is not None:
            line += f" {target_index}"
        if _OBS is not None:
            _OBS.before(card_id, st)
        res = await _cmd_then_state(line)
        if _OBS is not None:
            try:
                _OBS.after(await _state())
            except Exception:
                pass
        return res
    except Exception as e:
        return _handle_error(e)


@mcp.tool()
async def end_turn() -> str:
    """End the current combat turn."""
    return await _cmd_then_state("END")


@mcp.tool()
async def choose(option_index: int) -> str:
    """Pick choice_list/screen option by 0-based index (events, map nodes,
    Neow, card rewards)."""
    return await _cmd_then_state(f"CHOOSE {option_index}")


@mcp.tool()
async def proceed() -> str:
    """Press the generic proceed/continue button."""
    return await _cmd_then_state("PROCEED")


@mcp.tool()
async def confirm() -> str:
    """Confirm the current selection (grid confirm etc.)."""
    return await _cmd_then_state("CONFIRM")


@mcp.tool()
async def cancel() -> str:
    """Cancel/back out of the current overlay."""
    return await _cmd_then_state("CANCEL")


@mcp.tool()
async def leave() -> str:
    """Leave the current room/shop (out of combat only)."""
    return await _cmd_then_state("LEAVE")


@mcp.tool()
async def run_turn(sleep: float = 0.6) -> str:
    """Autonomously play one combat turn via the advisor.

    Builds the decision pack, then executes advice.plan through Communication
    Mod (re-resolves hand indices by card id). Returns the pack plus the
    execution log. In co-op the command may take a few seconds to apply.
    """
    if not _ADVISOR:
        return _handle_error(RuntimeError("advisor package unavailable"))
    try:
        res = await asyncio.to_thread(drive1.run_turn, _KB, sleep, _OBS)
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return _handle_error(e)


@mcp.tool()
async def flush_observations() -> str:
    """Write accumulated card-play observations into card_kb1.json.

    play_card / run_turn record before/after state diffs; this tool
    aggregates them (median per effect) and persists entries with
    prov="observed" (conf 0.65-0.85). Entries with higher confidence
    (dll/static) are not overwritten — a disagreeing observation is
    stashed under the entry's "obs" field instead.
    """
    if not _ADVISOR or _OBS is None:
        return _handle_error(RuntimeError("advisor package unavailable"))
    try:
        summary = await asyncio.to_thread(_OBS.flush, _KB, _KB.path)
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return _handle_error(e)


def main():
    global _base_url
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=None,
                    help="sts1_bridge URL (default env STS1_BRIDGE_BASE or "
                         "http://127.0.0.1:15531)")
    args = ap.parse_args()
    if args.base_url:
        _base_url = args.base_url
    mcp.run()


if __name__ == "__main__":
    main()
