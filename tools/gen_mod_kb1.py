"""インストール済み mod jar をデコンパイルし、card_kb1.json に mod カードをマージ。

使い方:
  python tools/gen_mod_kb1.py            # mods フォルダ全走査
  python tools/gen_mod_kb1.py X.jar ...  # 個別

- mod jar は zip → クラスを decomp_mods/<mod>/ へ cfr で展開
- gen_card_kb1.collect(mod_mode=True) で id 無しクラス名でも拾う
- KB には mod 名と指紋(ファイルサイズ+mtime)を記録 → mod 更新で再解析可能
"""
import os, re, sys, json, glob, zipfile, subprocess, hashlib, tempfile
try:
    from . import gen_card_kb1 as g
except ImportError:
    import gen_card_kb1 as g

STS = os.environ.get("STS1_GAME_DIR", "")
WS = os.environ.get("STS1_WORKSHOP_DIR", "")
MODS = os.path.join(STS, "mods")
CFR = os.environ.get("CFR_JAR", "")
JAVA = os.environ.get("JAVA_EXE", "java")
OUT_JAVA = os.environ.get("JAVA_EXE", "java")

# カード実装を持たないライブラリ系は飛ばす
SKIP_JARS = {"ModTheSpire.jar", "BaseMod.jar", "StSLib.jar",
             "CommunicationMod.jar", "ramsaver.jar",
             "OptimizeTheSpire.jar", "TogetherInSpire.jar",
             "GifTheSpireLib.jar", "SignatureLib.jar", "actlikeit.jar",
             "ShionUnlock.jar", "MintModSkin.jar", "LustTravelPatch.jar",
             "mod-uploader.jar"}


def fp(path):
    st = os.stat(path)
    return f"{st.st_size}:{int(st.st_mtime)}"


def decompile(jar: str, outdir: str):
    """jar 全体を cfr で decompile。mod は小さいので丸ごとやる。"""
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run([JAVA, "-jar", CFR, jar, "--outputdir", outdir],
                       capture_output=True, text=True, timeout=600)
    return r.returncode


def load_kb():
    if os.path.exists(g.OUT):
        return json.load(open(g.OUT, encoding="utf-8"))
    return {"schema": 1, "prov": "static", "cards": {}, "mods": {}}


# hsr-mod の cardData.csv レイアウト(ヘッダは中国語/GBK)
# 0:ID 1:Name 2:Rarity 3:Type 4:Target 5:Cost 6:Desc 7:Damage 8:TR
# 9:Block 10:Magic 11:UpgCost 12:Desc+ 13:UpgDamage 14:UpgTR 15:UpgBlock
# 16:UpgMagic 17:Path 18:Element 19:Versatility
_CSV_TGT = {"ENEMY": "enemy", "ALL_ENEMY": "all_enemies", "SELF": "self",
            "NONE": "none", "ALL": "all"}


def _int(s, d=0):
    try:
        return int(str(s).strip())
    except (ValueError, TypeError):
        return d


def parse_carddata_csvs(jar: str) -> dict:
    """jar 内の *cardData*.csv を探し {id: stats} を返す(データ駆動 mod 用)。"""
    out = {}
    with zipfile.ZipFile(jar) as z:
        names = [n for n in z.namelist()
                 if n.lower().endswith(".csv") and "card" in n.lower()]
        for n in names:
            if "/ZHS/" in n:  # 英語版優先(ZHS はスキップ)
                continue
            raw = z.read(n)
            for enc in ("gbk", "utf-8-sig", "utf-8"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            import csv as _csv, io
            rows = list(_csv.reader(io.StringIO(text)))
            if not rows or "ID" not in rows[0][0]:
                continue
            for r in rows[1:]:
                if len(r) < 17 or not r[0].strip():
                    continue
                cid = r[0].strip()
                dmg, tr, blk, mag = (_int(r[7]), _int(r[8]), _int(r[9]),
                                     _int(r[10]))
                stats = {
                    "base": {"baseDamage": dmg, "baseBlock": blk,
                             "baseMagicNumber": mag},
                    "cost": _int(r[5], -9),
                    "type": r[3].strip() or None,
                    "rarity": r[2].strip() or None,
                    "target": _CSV_TGT.get(r[4].strip(), "enemy"),
                    "upg": {},
                }
                if stats["cost"] == -9:
                    stats.pop("cost")
                for dst, idx, key in (("upgradeDamage", 13, None),
                                      ("upgradeBlock", 15, None),
                                      ("upgradeMagicNumber", 16, None),
                                      ("upgradeCost", 11, None)):
                    v = _int(r[idx], -9)
                    if v != -9:
                        stats["upg"][dst] = v
                if not stats["upg"]:
                    stats.pop("upg")
                fx_extra = []
                if tr:
                    fx_extra.append({"op": "mod_damage", "n": tr,
                                     "pool": "toughness", "tgt": "enemy"})
                if fx_extra:
                    stats["fx_extra"] = fx_extra
                out[cid] = stats
    return out


def main():
    import argparse
    global STS, WS, MODS, CFR, JAVA, OUT_JAVA
    ap = argparse.ArgumentParser(description="Generate local Mod card effects; no binaries are distributed.")
    ap.add_argument("jars", nargs="*")
    ap.add_argument("--game-dir", default=STS)
    ap.add_argument("--workshop-dir", default=WS)
    ap.add_argument("--cfr", default=CFR)
    ap.add_argument("--java", default=JAVA)
    ap.add_argument("--out", default=g.OUT)
    ap.add_argument("--cache-dir", default=OUT_JAVA)
    args = ap.parse_args()
    if not args.cfr or not os.path.isfile(args.cfr):
        ap.error("Provide --cfr or CFR_JAR pointing to a separately obtained CFR JAR.")
    if not args.jars and not args.game_dir and not args.workshop_dir:
        ap.error("Provide JAR paths, --game-dir, or --workshop-dir.")
    STS, WS, CFR, JAVA, OUT_JAVA = args.game_dir, args.workshop_dir, args.cfr, args.java, args.cache_dir
    MODS = os.path.join(STS, "mods") if STS else ""
    g.OUT = args.out
    jars = args.jars or sorted(
        p for p in (glob.glob(os.path.join(WS, "*", "*.jar")) if WS else [])
        + (glob.glob(os.path.join(MODS, "*.jar")) if MODS else []))
    kb = load_kb()
    kb.setdefault("mods", {})
    cls2id = {}
    total = 0
    for path in jars:
        if os.path.basename(path) in SKIP_JARS:
            print(f"skip {os.path.basename(path)}")
            continue
        if not os.path.exists(path):
            print(f"missing {path}")
            continue
        name = os.path.splitext(os.path.basename(path))[0]
        if kb["mods"].get(name) == fp(path):
            print(f"unchanged {name}")
            continue
        outdir = os.path.join(OUT_JAVA, name)
        print(f"decompiling {name} ...", flush=True)
        try:
            decompile(path, outdir)
        except Exception as e:
            print(f"  decomp err {e}")
            continue
        stats_map = parse_carddata_csvs(path)
        if stats_map:
            print(f"  csv: {len(stats_map)} card rows")
        cards, cls2id, n_skip, powers = g.collect(
            outdir, mod_mode=True, existing=cls2id, stats_map=stats_map)
        kb.setdefault("powers", {}).update(powers)
        # CSV 由来の値を後付け(fx_extra=靭性等 + クラス未検出カードの救済)
        for cid, st in stats_map.items():
            ent = cards.get(cid)
            if ent is None:
                ent = {"fx": [], "prov": "csv", "conf": 0.7}
                if st.get("cost") is not None:
                    ent["cost"] = st["cost"]
                for k in ("type", "rarity", "target"):
                    if st.get(k):
                        ent[k] = st[k]
                if st.get("upg"):
                    ent["upg"] = st["upg"]
                if st["base"].get("baseDamage"):
                    ent["fx"].append({"op": "damage",
                                      "n": st["base"]["baseDamage"],
                                      "tgt": st.get("target") or "enemy"})
                if st["base"].get("baseBlock"):
                    ent["fx"].append({"op": "block",
                                      "n": st["base"]["baseBlock"],
                                      "tgt": "self"})
                cards[cid] = ent
            ent["fx"].extend(st.get("fx_extra") or [])
        for cid, ent in cards.items():
            ent["mod"] = name
        kb["cards"].update(cards)
        kb["mods"][name] = fp(path)
        total += len(cards)
        print(f"  {name}: +{len(cards)} cards (skipped {n_skip})")
    with open(g.OUT, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=1)
    print(f"done. total cards in KB: {len(kb['cards'])} (+{total} new)")


if __name__ == "__main__":
    main()
