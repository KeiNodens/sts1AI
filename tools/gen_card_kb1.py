"""decomp_cards/*.java → card_kb1.json (id→fx 静的 KB).

2パス構成:
  1) 全ファイルから ID/class名/base値/cost/type/flags/upgrade差分 を収集
  2) use() 内の Action コンストラクタ呼出を引数解決して fx 生成

LLM には出さない(name/desc は KB に含めない)。
"""
import os, re, json

SRC = os.path.join(os.path.dirname(__file__), "..", "decomp_cards")
OUT = os.environ.get("STS1_KB_PATH", os.path.join(os.getcwd(), "card_kb1.json"))

RE_ID = re.compile(r'public static final String ID = "([^"]+)"')
RE_ID2 = re.compile(r'(?:public static final String )?ID\s*=\s*(?:\w+\.)?makeID\("([^"]+)"')
RE_ID3 = re.compile(r'ID\s*=\s*\w+\.class\.getSimpleName\(\)')
RE_FIELD = re.compile(r'this\.(base\w+)\s*=\s*(-?\d+)')
RE_TARGET = re.compile(r'CardTarget\.(\w+)')
RE_TYPE = re.compile(
    r'CardType\.(ATTACK|SKILL|POWER|STATUS|CURSE)(?!\w)')
RE_COLOR = re.compile(r'CardColor\.(\w+)(?!\w)')
RE_RARITY = re.compile(
    r'CardRarity\.(BASIC|SPECIAL|COMMON|UNCOMMON|RARE|CURSE)(?!\w)')
RE_COST = re.compile(r'super\(ID,\s*[^,]+,\s*"[^"]*",\s*(-?\d+)')
RE_USE = re.compile(r'public void (?:use|onUse|cardEffect|effect|applyEffect)\(')
RE_CAST = re.compile(r'\(\s*Abstract\w+\s*\)\s*')
RE_UPG = re.compile(r'this\.(upgrade\w+)\s*\(\s*(-?\d+)')

TGT_MAP = {"ENEMY": "enemy", "ALL_ENEMY": "all_enemies", "SELF": "self",
           "NONE": "none", "ALL": "all", "ENEMY_OR_SELF": "enemy"}

FIELD_OF = {
    "this.damage": "baseDamage", "this.block": "baseBlock",
    "this.magicNumber": "baseMagicNumber",
    "this.secondMagicNumber": "baseSecondMagicNumber",
    "this.thirdMagicNumber": "baseThirdMagicNumber",
    "this.draw": "baseDraw", "this.heal": "baseHeal",
    "this.discard": "baseDiscard",
    "this.baseDamage": "baseDamage", "this.baseBlock": "baseBlock",
    "this.baseMagicNumber": "baseMagicNumber",
}

# custom action → fx テンプレ("dmg" は baseDamage を使う)
CUSTOM = {
    "FeedAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "HandOfGreedAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "GreedAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "RitualDaggerAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "LessonLearnedAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "SearingBlowAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "MeteorStrikeAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "ThunderStrikeAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "ScrapeAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "ReaperAction": [{"op": "damage", "n": "dmg", "tgt": "all_enemies"},
                     {"op": "heal", "n": "dmg", "tgt": "self"}],
    "WhirlwindAction": [{"op": "damage", "n": "dmg", "tgt": "all_enemies"}],
    "ConstrictedAction": [{"op": "apply_power", "n": "magic", "tgt": "enemy",
                           "power": "Constricted"}],
    "HavocAction": [{"op": "play_top", "n": 1}],
    "ExhumeAction": [{"op": "return_exhaust", "n": 1}],
    "DualWieldAction": [{"op": "copy_card", "n": "magic"}],
    "NightmareAction": [{"op": "copy_card", "n": "magic"}],
    "DiscoveryAction": [{"op": "discover", "n": "magic"}],
    "BetterDiscoveryAction": [{"op": "discover", "n": "magic"}],
    "ForeignInfluenceAction": [{"op": "discover", "n": "magic"}],
    "PrismaticShardAction": [{"op": "discover", "n": "magic"}],
    "InfernalBladeAction": [{"op": "add_card", "n": 1}],
    "WhiteNoiseAction": [{"op": "add_card", "n": 1}],
    "ChrysalisAction": [{"op": "add_card", "n": "magic"}],
    "TransmutationAction": [{"op": "add_card", "n": 1}],
    "FastingAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Strength"},
                      {"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Dexterity"}],
    "DoppelgangerAction": [{"op": "copy_hand_next", "n": 1}],
    "ExhaustNonAttackAction": [{"op": "exhaust_card", "n": "magic"}],
    "DiscardPileToTopOfDeckAction": [{"op": "deck_top", "n": 1}],
    "DrawPileToHandAction": [{"op": "tutor", "n": "magic"}],
    "ArmamentsAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "TrueGritAction": [{"op": "block", "n": "blk", "tgt": "self"},
                       {"op": "exhaust_card", "n": 1}],
    "PurityAction": [{"op": "exhaust_card", "n": "magic"}],
    "SeeingRedAction": [{"op": "gain_energy", "n": "magic"}],
    "DeepBreathAction": [{"op": "draw", "n": "magic"}],
    "RecycleAction": [{"op": "exhaust_card", "n": 1},
                      {"op": "gain_energy", "n": "magic"}],
    "RebootAction": [{"op": "draw", "n": "magic"}],
    "AggregateAction": [{"op": "draw", "n": "magic"}],
    "FTLAction": [{"op": "draw", "n": "magic"}],
    "MultiCastAction": [{"op": "evoke", "n": "magic"}],
    "StormAction": [{"op": "channel", "n": "magic", "orb": "Lightning"}],
    "ZapAction": [{"op": "channel", "n": 1, "orb": "Lightning"}],
    "DefragmentAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                          "power": "Focus"}],
    "BufferAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                      "power": "Buffer"}],
    "FusionAction": [{"op": "channel", "n": "magic", "orb": "Plasma"}],
    "ReprogramAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                         "power": "Focus"}],
    "ReinforcedBodyAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "SteamBarrierAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "SpotWeaknessAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                            "power": "Strength", "cond": "enemy_attacking"}],
    "DarkEmbraceAction": [{"op": "apply_power", "n": 1, "tgt": "self",
                           "power": "DarkEmbrace"}],
    "CombustAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Combust"}],
    "RuptureAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Rupture"}],
    "BrutalityAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                         "power": "Brutality"}],
    "JuggernautAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                          "power": "Juggernaut"}],
    "FlameBarrierAction": [{"op": "block", "n": "blk", "tgt": "self"},
                           {"op": "apply_power", "n": "magic", "tgt": "self",
                            "power": "FlameBarrier"}],
    "GhostlyArmorAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "EscapePlanAction": [{"op": "draw", "n": "magic"}],
    "CalculatedGambleAction": [{"op": "discard_hand", "n": 1},
                               {"op": "draw", "n": "magic"}],
    "ReflexAction": [{"op": "draw", "n": "magic"}],
    "TacticianAction": [{"op": "gain_energy", "n": "magic"}],
    "ExpertiseAction": [{"op": "draw", "n": "magic"}],
    "SetupAction": [{"op": "zero_cost", "n": 1}],
    "ForethoughtAction": [{"op": "zero_cost", "n": "magic"}],
    "StasisAction": [{"op": "copy_card", "n": 1}],
    "ViolenceAction": [{"op": "tutor_attack", "n": "magic"}],
    "SecretWeaponAction": [{"op": "tutor_attack", "n": "magic"}],
    "SecretTechniqueAction": [{"op": "tutor_skill", "n": "magic"}],
    "PrayAction": [{"op": "gain_mantra", "n": "magic"}],
    "ProstrateAction": [{"op": "gain_mantra", "n": "magic"}],
    "WorshipAction": [{"op": "gain_mantra", "n": "magic"}],
    "Fasting2Action": [{"op": "apply_power", "n": "magic", "tgt": "self",
                        "power": "Fasting"}],
    "SwivelAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "ConjureBladeAction": [{"op": "enter_stance", "n": 0}],
    "DevaFormAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                        "power": "Deva"}],
    "DevotionAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                        "power": "Devotion"}],
    "EstablishmentAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                             "power": "Establishment"}],
    "LikeWaterAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                         "power": "LikeWater"}],
    "MentalFortressAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                              "power": "MentalFortress"}],
    "NirvanaAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Nirvana"}],
    "RushdownAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                        "power": "Rushdown"}],
    "ScrawlAction": [{"op": "draw", "n": "magic"}],
    "AlphaAction": [{"op": "add_card", "n": 1}],
    "BattleHymnAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                          "power": "BattleHymn"}],
    "BlasphemyAction": [{"op": "apply_power", "n": 1, "tgt": "self",
                         "power": "Blasphemy"}],
    "BrillianceAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "CarveRealityAction": [{"op": "add_card", "n": "magic"}],
    "CollectAction": [{"op": "add_card", "n": "magic"}],
    "ConjureBladeAction2": [{"op": "add_card", "n": "magic"}],
    "DeusExMachinaAction": [{"op": "add_card", "n": "magic"}],
    "FollowUpAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "ForeignInfluenceAction2": [{"op": "discover", "n": 1}],
    "JustLuckyAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "KnowledgeAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                         "power": "Knowledge"}],
    "LessonLearnedAction2": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "OmniscienceAction": [{"op": "discover", "n": 1}],
    "ReachHeavenAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "SashWhipAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "SpiritShieldAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "ThirdEyeAction": [{"op": "block", "n": "blk", "tgt": "self"},
                       {"op": "scry", "n": "magic"}],
    "WishAction": [{"op": "wish", "n": 1}],
    "MasterfulStabAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "GrandFinaleAction": [{"op": "damage", "n": "dmg", "tgt": "all_enemies"}],
    "UnloadAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "BulletTimeAction": [{"op": "zero_hand", "n": 1}],
    "BurstAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                     "power": "Burst"}],
    "CorpseExplosionAction": [{"op": "apply_power", "n": "magic", "tgt": "enemy",
                               "power": "CorpseExplosion"}],
    "CatalystAction": [{"op": "apply_power", "n": 1, "tgt": "enemy",
                        "power": "Catalyst"}],
    "AdrenalineAction": [{"op": "gain_energy", "n": "magic"},
                         {"op": "draw", "n": "second"}],
    "AlchemizeAction": [{"op": "gain_potion", "n": 1}],
    "DistractionAction": [{"op": "add_card", "n": "magic"}],
    "DoppelgangerAction2": [{"op": "draw", "n": "magic"},
                            {"op": "gain_energy", "n": "magic"}],
    "MalaiseAction": [{"op": "apply_power", "n": "magic", "tgt": "enemy",
                       "power": "StrengthLoss"},
                      {"op": "apply_power", "n": "magic", "tgt": "enemy",
                       "power": "Weak"}],
    "PhantasmalKillerAction": [{"op": "apply_power", "n": 1, "tgt": "self",
                                "power": "PhantasmalKiller"}],
    "ShadowShieldAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "StormOfSteelAction": [{"op": "add_card", "n": "magic"}],
    "WraithFormv2Action": [{"op": "apply_power", "n": "magic", "tgt": "self",
                            "power": "WraithForm"}],
    "FiendFireAction": [{"op": "exhaust_hand", "n": 1},
                        {"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "BaneAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "BackflipAction": [{"op": "block", "n": "blk", "tgt": "self"},
                       {"op": "draw", "n": "magic"}],
    "DaggerThrowAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"},
                          {"op": "draw", "n": 1},
                          {"op": "discard", "n": 1}],
    "DashAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"},
                   {"op": "block", "n": "blk", "tgt": "self"}],
    "FlechettesAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "HeelHookAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "RipAndTearAction": [{"op": "damage", "n": "dmg", "tgt": "random_enemy"}],
    "SneakyStrikeAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "AllOutAttackAction": [{"op": "damage", "n": "dmg", "tgt": "all_enemies"},
                           {"op": "discard", "n": 1}],
    "EndTurnAgonyAction": [{"op": "end_turn", "n": 1}],
    "ConserveBatteryAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "DoubleEnergyAction": [{"op": "double_energy", "n": 1}],
    "EquilibriumAction": [{"op": "block", "n": "blk", "tgt": "self"},
                          {"op": "apply_power", "n": "magic", "tgt": "self",
                           "power": "Equilibrium"}],
    "ImpulseAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Impatient"}],
    "SkimAction": [{"op": "draw", "n": "magic"}],
    "HologramAction": [{"op": "block", "n": "blk", "tgt": "self"},
                       {"op": "return_discard", "n": "magic"}],
    "ReboundAction": [{"op": "rebound", "n": 1}],
    "ScavengeAction": [{"op": "gain_energy", "n": "magic"}],
    "UndoAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "TempestAction": [{"op": "channel", "n": "magic", "orb": "Lightning"}],
    "AutoplayAction": [{"op": "play_top", "n": "magic"}],
    "GashAction": [{"op": "apply_power", "n": "magic", "tgt": "enemy",
                    "power": "Constricted"}],
    "HandOfGreedAction2": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "HemokinesisAction": [{"op": "lose_hp", "n": "magic2self", "tgt": "self"},
                          {"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "HemokinesisAction2": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "OfferingAction": [{"op": "lose_hp", "n": "magic", "tgt": "self"},
                       {"op": "gain_energy", "n": "second"},
                       {"op": "draw", "n": "magic"}],
    "PummelAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "RiddleWithHolesAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "SecondWindAction": [{"op": "block", "n": "blk", "tgt": "self"},
                         {"op": "exhaust_card", "n": "magic"}],
    "SeverSoulAction": [{"op": "exhaust_nonattack", "n": 1},
                        {"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "WhisperAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "ChaosAction": [{"op": "channel_random", "n": "magic"}],
    "FusionAction2": [{"op": "channel", "n": "magic", "orb": "Plasma"}],
    "RainbowAction": [{"op": "channel_random", "n": "magic"}],
    "CoolheadedAction": [{"op": "channel", "n": "magic", "orb": "Frost"},
                         {"op": "draw", "n": "second"}],
    "GoForTheEyesAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "CompileDriverAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "CoreSurgeAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                         "power": "Artifact"},
                        {"op": "exhaust_card", "n": 1}],
    "RedoAction": [{"op": "draw", "n": "magic"}],
    "SweepingBeamAction": [{"op": "damage", "n": "dmg", "tgt": "all_enemies"},
                           {"op": "draw", "n": "magic"}],
    "OverclockAction": [{"op": "draw", "n": "magic"},
                        {"op": "add_card", "n": 1, "card": "Burn"}],
    "MachineLearningAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                               "power": "MachineLearning"}],
    "RepeatFormAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                          "power": "Repeat"}],
    "SeekAction": [{"op": "tutor", "n": "magic"}],
    "SelfRepairAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                          "power": "Repair"}],
    "StaticDischargeAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                               "power": "StaticDischarge"}],
    "LoopAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                    "power": "Loop"}],
    "CreativeAIAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                          "power": "CreativeAI"}],
    "BiasedCognitionAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                               "power": "BiasCogn"}],
    "CapacitorAction": [{"op": "gain_orb_slot", "n": "magic"}],
    "ConsumeAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Consume"}],
    "DarknessAction": [{"op": "channel", "n": 1, "orb": "Dark"}],
    "DefragmentAction2": [{"op": "apply_power", "n": "magic", "tgt": "self",
                           "power": "Focus"}],
    "EchoAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                    "power": "Echo"}],
    "ElectrodynamicsAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                               "power": "Electrodynamics"}],
    "GlacierAction": [{"op": "block", "n": "blk", "tgt": "self"},
                      {"op": "channel", "n": "magic", "orb": "Frost"}],
    "HelloWorldAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                          "power": "HelloWorld"}],
    "MelterAction": [{"op": "remove_block", "n": 1, "tgt": "enemy"}],
    "PanaceaAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Artifact"}],
    "SunderAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "BlizzardAction": [{"op": "damage", "n": "dmg", "tgt": "all_enemies"}],
    "BullseyeAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"},
                       {"op": "apply_power", "n": "magic", "tgt": "enemy",
                        "power": "Lockon"}],
    "ClawAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "ScrapeAction2": [{"op": "damage", "n": "dmg", "tgt": "enemy"},
                      {"op": "draw", "n": "magic"}],
    "FissionAction": [{"op": "evoke_all", "n": 1}],
    "GeneticAlgorithmAction": [{"op": "block", "n": "blk", "tgt": "self"}],
    "HyperbeamAction": [{"op": "damage", "n": "dmg", "tgt": "all_enemies"},
                        {"op": "apply_power", "n": "magic", "tgt": "self",
                         "power": "Focus", "neg": True}],
    "MeteorStrikeAction2": [{"op": "damage", "n": "dmg", "tgt": "enemy"},
                            {"op": "channel", "n": "magic", "orb": "Plasma"}],
    "ReboundAction2": [{"op": "rebound", "n": 1}],
    "AmplifyAction": [{"op": "apply_power", "n": "magic", "tgt": "self",
                       "power": "Amplify"}],
    "AttackDamageAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "PummelDamageAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    # --- hsr-mod 系 ---
    "ElementalDamageAction": [{"op": "damage", "n": "dmg", "tgt": "enemy"}],
    "ElementalDamageAllAction": [{"op": "damage", "n": "dmg",
                                  "tgt": "all_enemies"}],
    "FollowUpAction": [{"op": "follow_up", "n": 1}],
    "BreakAction": [{"op": "mod_damage", "n": 0, "pool": "toughness",
                     "tgt": "enemy"}],
    "ToughnessDamageAction": [{"op": "mod_damage", "n": "magic",
                               "pool": "toughness", "tgt": "enemy"}],
    "ReduceChargeAction": [{"op": "spend_resource", "n": "magic",
                            "pool": "charge"}],
    "ReduceChargeByHandCardNumAction": [{"op": "spend_resource", "n": 1,
                                         "pool": "charge"}],
    "GainChargeAction": [{"op": "gain_resource", "n": "magic",
                          "pool": "charge"}],
    "ShoutVoiceAction": [],
    "DoublePoisonAction": [{"op": "multiply_power", "n": 2, "tgt": "enemy",
                            "power": "Poison"}],
    "TriplePoisonAction": [{"op": "multiply_power", "n": 3, "tgt": "enemy",
                            "power": "Poison"}],
    "BetterDrawPileToHandAction": [{"op": "tutor", "n": "magic"}],
    "DrawPileToHandAction2": [{"op": "tutor", "n": "magic"}],
    "UniqueDiscoveryAction": [{"op": "discover", "n": "magic"}],
    "GainBlockRandomCardAction": [{"op": "block", "n": "blk", "tgt": "self"}],
}


def strip_debug(src: str) -> str:
    pat = re.compile(r'if\s*\(\s*Settings\.(isDebug|isInfo|showTestCards|isModded)')
    out, i, n = [], 0, len(src)
    while True:
        m = pat.search(src, i)
        if not m:
            out.append(src[i:])
            break
        out.append(src[i:m.start()])
        j = src.index('{', m.end())
        depth, k = 1, j + 1
        while k < n and depth:
            depth += (src[k] == '{') - (src[k] == '}')
            k += 1
        i = k
    return ''.join(out)


def _block_end(src: str, j: int) -> int:
    """src[j]=='{' として対応 '}' の次位置を返す"""
    depth, k = 1, j + 1
    while k < len(src) and depth:
        depth += (src[k] == '{') - (src[k] == '}')
        k += 1
    return k


def strip_upgraded(src: str) -> str:
    """upgraded 分岐を基本版に正規化:
    if (this.upgraded) {X} else {Y} → Y
    if (!this.upgraded) {X} else {Y} → X
    """
    pat = re.compile(r'if\s*\(\s*(!?)\s*this\.upgraded\s*\)')
    out, i = [], 0
    while True:
        m = pat.search(src, i)
        if not m:
            out.append(src[i:])
            break
        neg = bool(m.group(1))
        j = src.find('{', m.end())
        if j < 0:
            out.append(src[i:])
            break
        k = _block_end(src, j)
        rest = src[k:k + 12]
        else_m = re.match(r'\s*else\s*\{', rest)
        if neg:
            # 非強化=if本体を残す → else 側を捨てる
            out.append(src[i:m.start()])
            out.append(src[j + 1:k - 1])
            if else_m:
                k2 = _block_end(src, k + else_m.end() - 1)
                i = k2
            else:
                i = k
        else:
            # 強化=if本体を捨てる → else 側を残す
            out.append(src[i:m.start()])
            if else_m:
                ej = k + else_m.end() - 1
                k2 = _block_end(src, ej)
                out.append(src[ej + 1:k2 - 1])
                i = k2
            else:
                i = k
    return ''.join(out)


def resolve(arg: str, base: dict):
    arg = arg.strip()
    if arg in FIELD_OF:
        return base.get(FIELD_OF[arg], 0)
    if re.fullmatch(r'-?\d+', arg):
        return int(arg)
    return None


def ctor_calls(body: str, cls: str):
    """`new <cls>(` の出現毎にトップレベル引数リストを yield"""
    pos = 0
    pat = 'new ' + cls + '('
    while True:
        i = body.find(pat, pos)
        if i < 0:
            return
        j = i + len(pat)
        depth, k = 1, j
        while k < len(body) and depth:
            depth += (body[k] == '(') - (body[k] == ')')
            k += 1
        inner = body[j:k - 1]
        args, d, last = [], 0, 0
        for x, c in enumerate(inner):
            if c in '([':
                d += 1
            elif c in ')]':
                d -= 1
            elif c == ',' and d == 0:
                args.append(inner[last:x])
                last = x + 1
        args.append(inner[last:])
        yield [a.strip() for a in args], i
        pos = k


def nested_ctor(arg: str):
    m = re.match(r'new (\w+)\s*\(', arg)
    return m.group(1) if m else None


def find_loops(body: str):
    """`for(int i=0;i<N` 系の繰り返し回数とブロック範囲を返す"""
    spans = []
    for m in re.finditer(
            r'for\s*\([^;{]*?(\w+)\s*=\s*(\d+)\s*;[^;{]*?<\s*(this\.magicNumber|\d+)',
            body):
        bound = (m.group(3), int(m.group(2)))  # (bound, start)
        # for ヘッダの残り `; ++i)` を飛ばして ')' の次からブロックを探す
        j = body.find(')', m.end())
        if j < 0:
            continue
        j += 1
        while j < len(body) and body[j] in ' \t\n\r':
            j += 1
        if j < len(body) and body[j] == '{':
            depth, k = 1, j + 1
            while k < len(body) and depth:
                depth += (body[k] == '{') - (body[k] == '}')
                k += 1
            spans.append((j, k, bound))
        else:
            k = body.find(';', j)
            spans.append((j, k if k > 0 else len(body), bound))
    return spans


def _aval(arglist, base, default):
    """アクションクラス内の引数値解決:
    リテラル > card.damage/block/magic 参照 > default"""
    for a in arglist:
        a = a.strip()
        if re.fullmatch(r'-?\d+', a):
            return int(a)
    for a in arglist:
        if re.search(r'(?:card\.|\.)(?:base)?[Dd]amage\b', a):
            return base.get("baseDamage", 0)
        if re.search(r'(?:card\.|\.)(?:base)?[Bb]lock\b', a):
            return base.get("baseBlock", 0)
        if "magicNumber" in a:
            return base.get("baseMagicNumber", 0)
    return default


def _scan_action_file(path, base, emit, resolve, nval, cls2file, depth,
                      _seen=None):
    """mod 独自アクションの .java を読み、中のバニラアクションを fx 化。
    depth 2 まで再帰(アクション内アクション)。値は呼び出し元カードの
    base 値で近似する。"""
    if depth > 2:
        return
    _seen = _seen or set()
    if path in _seen:
        return
    _seen.add(path)
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return
    body = RE_CAST.sub('', strip_debug(src))
    cls_name = os.path.splitext(os.path.basename(path))[0]
    ex = {"via": cls_name}

    def dmg_def():
        return base.get("baseDamage", 0)

    if 'new DamageAllEnemiesAction(' in body:
        emit("damage", dmg_def(), "all_enemies", ex)
    if 'new VampireDamageAllEnemiesAction(' in body:
        emit("damage", dmg_def(), "all_enemies", ex)
        emit("heal", dmg_def(), "self", ex)
    if 'new VampireDamageAction(' in body:
        emit("damage", dmg_def(), "enemy", ex)
        emit("heal", dmg_def(), "self", ex)
    for cls_r in ("DamageRandomEnemyAction", "AttackDamageRandomEnemyAction"):
        if 'new ' + cls_r + '(' in body:
            emit("damage", dmg_def(), "random_enemy", ex)
    for args, _ in ctor_calls(body, "DamageAction"):
        n = dmg_def()
        if len(args) > 1 and "DamageInfo" in args[1]:
            for da, _ in ctor_calls(args[1], "DamageInfo"):
                n = _aval(da[1:], base, n)
        t = "self" if args and re.search(r'player|owner|source', args[0]) \
            else "enemy"
        emit("damage" if t == "enemy" else "lose_hp", n, t, ex)
    for args, _ in ctor_calls(body, "GainBlockAction"):
        emit("block", _aval(args, base, base.get("baseBlock", 0)), "self", ex)
    for args, _ in ctor_calls(body, "DrawCardAction"):
        emit("draw", _aval(args[1:], base, base.get("baseMagicNumber") or 1),
             None, ex)
    for args, _ in ctor_calls(body, "DiscardAction"):
        emit("discard", _aval(args[1:], base, 1), None, ex)
    for args, _ in ctor_calls(body, "LoseHPAction"):
        emit("lose_hp", _aval(args, base, 0), "self", ex)
    for args, _ in ctor_calls(body, "HealAction"):
        emit("heal", _aval(args, base, base.get("baseMagicNumber", 0)),
             "self", ex)
    for args, _ in ctor_calls(body, "GainEnergyAction"):
        emit("gain_energy", _aval(args, base, base.get("baseMagicNumber", 0)),
             None, ex)
    for args, _ in ctor_calls(body, "ApplyPowerAction"):
        inner = ','.join(args[1:])
        pwm = re.search(r'new (\w+Power)\s*\(', inner)
        t = "enemy" if args and re.search(r'\bm\b|monster|target', args[0]) \
            else "self"
        e = dict(ex)
        if pwm:
            pw = pwm.group(1)
            e["power"] = pw[:-5] if pw.endswith("Power") else pw
        emit("apply_power",
             _aval(args[3:] if len(args) > 3 else args[1:], base,
                   base.get("baseMagicNumber") or 1), t, e)
    for args, _ in ctor_calls(body, "ChannelAction"):
        orb = None
        for a in args:
            oc = nested_ctor(a)
            if oc:
                orb = oc
        e = dict(ex)
        e["orb"] = orb[:-3] if orb and orb.endswith("Orb") else orb
        emit("channel", 1, None, e)
    if 'new ExhaustAction(' in body:
        emit("exhaust_card", 1, None, ex)
    for args, _ in ctor_calls(body, "EvokeAction"):
        emit("evoke", _aval(args, base, 1), None, ex)
    for cls_t in ("MakeTempCardInHandAction", "MakeTempCardInDrawPileAction",
                  "MakeTempCardInDiscardAction"):
        for args, _ in ctor_calls(body, cls_t):
            ref = None
            for a in args:
                oc = nested_ctor(a)
                if oc:
                    ref = oc
            e = dict(ex)
            if ref:
                e["card"] = ref
            emit("add_card", 1, None, e)
    # ネストした独自アクション(浅い再帰)
    if depth < 2:
        for sub in set(re.findall(r'new (\w+Action)\s*\(', body)):
            if sub in cls2file and sub not in (
                    "DamageAction", "GainBlockAction", "DrawCardAction",
                    "ApplyPowerAction", "VFXAction", "SFXAction",
                    "WaitAction", "TextAboveCreatureAction"):
                _scan_action_file(cls2file[sub], base, emit, resolve, nval,
                                  cls2file, depth + 1, _seen)


def loop_repeat_at(spans, pos, base):
    for s, e, (bound, start) in spans:
        if s <= pos < e:
            if bound == "this.magicNumber":
                return max(base.get("baseMagicNumber", 1) - start, 1)
            return max(int(bound) - start, 1)
    return None


def parse_card(path: str, cls2id: dict, mod_mode: bool = False,
               stats: dict | None = None, cls2file: dict | None = None):
    src = open(path, encoding="utf-8", errors="replace").read()
    m = RE_ID.search(src) or RE_ID2.search(src)
    cid = m.group(1) if m else None
    if not cid and RE_ID3.search(src):
        cid = os.path.splitext(os.path.basename(path))[0]
    if not cid:
        if (mod_mode and re.search(r'extends \w*Card\b', src)
                and re.search(r'public void (use|onUse|cardEffect)\(', src)
                and not re.search(r'\babstract\s+class\b', src)):
            cid = os.path.splitext(os.path.basename(path))[0]
        else:
            return None

    base = {}
    for f, v in RE_FIELD.findall(src):
        base[f] = int(v)
    if stats:  # データ駆動カード: CSV 等からの値で this.damage 解決を可能に
        for k, v in stats.get("base", {}).items():
            base.setdefault(k, v)
    tgt_m = RE_TARGET.search(src)
    tgt = TGT_MAP.get(tgt_m.group(1) if tgt_m else "ENEMY", "enemy")
    typ = RE_TYPE.search(src)
    col = RE_COLOR.search(src)
    rar = RE_RARITY.search(src)
    cm = RE_COST.search(src)
    cost = int(cm.group(1)) if cm else None
    if stats:
        cost = cost if cost is not None else stats.get("cost")
        if not typ and stats.get("type"):
            typ = stats.get("type")
        if not rar and stats.get("rarity"):
            rar = stats.get("rarity")
        if stats.get("target"):
            tgt = stats["target"]
    flags = {}
    for flag, key in (("this.exhaust = true", "exhaust"),
                      ("this.isEthereal = true", "ethereal"),
                      ("this.isInnate = true", "innate"),
                      ("this.retain = true", "retain")):
        if flag in src:
            flags[key] = True
    upg = {}
    for f, v in RE_UPG.findall(src):
        upg[f] = int(v)

    um = RE_USE.search(src)
    body = src[um.start():] if um else ""
    nxt = re.search(r'\n\s*public (?:void|[A-Z])', body[10:])
    if nxt:
        body = body[:nxt.start() + 10]
    body = RE_CAST.sub('', strip_upgraded(strip_debug(body)))
    loops = find_loops(body)

    def nval(tok):
        """'dmg'/'blk'/'magic'/'second' または int → 値"""
        if tok == "dmg":
            return base.get("baseDamage", 0)
        if tok == "blk":
            return base.get("baseBlock", 0)
        if tok == "magic":
            return base.get("baseMagicNumber", 0)
        if tok == "second":
            return base.get("baseSecondMagicNumber", 0)
        if tok == "magic2self":
            return base.get("baseSecondMagicNumber") or base.get("baseMagicNumber", 0)
        return int(tok) if isinstance(tok, str) else tok

    fx = []
    seen_cls = set()

    def emit(op, n, t=None, extra=None):
        e = {"op": op, "n": n}
        if t:
            e["tgt"] = t
        if extra:
            e.update(extra)
        fx.append(e)

    # --- 基本アクション(引数解決) ---
    def dmg_tgt(a0):
        if a0 in ("p", "owner", "player") or "AbstractDungeon.player" in a0:
            return "self"
        if a0 == "mo" or a0 in re.findall(r'for \(AbstractMonster (\w+)', body):
            return "all_enemies"
        return "enemy"

    for args, pos in ctor_calls(body, "DamageAction"):
        n = base.get("baseDamage", 0)
        if len(args) > 1 and "DamageInfo" in args[1]:
            for da, _ in ctor_calls(args[1], "DamageInfo"):
                if len(da) > 1:
                    v = resolve(da[1], base)
                    if v is not None:
                        n = v
        rep = loop_repeat_at(loops, pos, base)
        ex = {"repeat": rep} if rep else None
        dt = dmg_tgt(args[0]) if args else (tgt if tgt != "none" else "enemy")
        emit("damage" if dt != "self" else "lose_hp", n, dt, ex)
        seen_cls.add("DamageAction")
    for cls, t2 in (("DamageAllEnemiesAction", "all_enemies"),
                    ("DamageRandomEnemyAction", "random_enemy"),
                    ("VampireDamageAction", "enemy"),
                    ("VampireDamageAllEnemiesAction", "all_enemies")):
        if 'new ' + cls + '(' in body:
            emit("damage", base.get("baseDamage", 0), t2)
            if "Vampire" in cls:
                emit("heal", base.get("baseDamage", 0), "self")
            seen_cls.add(cls)
    # ランダム敵 + ループ回数(Sword Boomerang 等)
    for args, pos in ctor_calls(body, "AttackDamageRandomEnemyAction"):
        rep = loop_repeat_at(loops, pos, base)
        ex = {"repeat": rep} if rep else None
        emit("damage", base.get("baseDamage", 0), "random_enemy", ex)
        seen_cls.add("AttackDamageRandomEnemyAction")
    for args, _ in ctor_calls(body, "GainBlockAction"):
        v = resolve(args[-1], base)
        emit("block", v if v is not None else base.get("baseBlock", 0), "self")
        seen_cls.add("GainBlockAction")
    for args, _ in ctor_calls(body, "DrawCardAction"):
        v = resolve(args[1], base) if len(args) > 1 else None
        emit("draw", v if v is not None else base.get("baseDraw") or base.get("baseMagicNumber", 0))
        seen_cls.add("DrawCardAction")
    for args, _ in ctor_calls(body, "DiscardAction"):
        v = resolve(args[2], base) if len(args) > 2 else None
        emit("discard", v if v is not None else 1)
        seen_cls.add("DiscardAction")
    for args, _ in ctor_calls(body, "LoseHPAction"):
        v = resolve(args[-1], base)
        emit("lose_hp", v if v is not None else 0, "self")
        seen_cls.add("LoseHPAction")
    for args, _ in ctor_calls(body, "HealAction"):
        v = resolve(args[-1], base)
        emit("heal", v if v is not None else base.get("baseMagicNumber", 0), "self")
        seen_cls.add("HealAction")
    for args, _ in ctor_calls(body, "GainEnergyAction"):
        v = resolve(args[0], base)
        emit("gain_energy", v if v is not None else base.get("baseMagicNumber", 0))
        seen_cls.add("GainEnergyAction")

    # --- ApplyPowerAction ---
    for args, pos in ctor_calls(body, "ApplyPowerAction"):
        tgt_arg = args[0] if args else "p"
        pt = "self" if tgt_arg in ("p", "owner", "player") else (
            "all_enemies" if tgt_arg == "mo" or
            tgt_arg in [v for v in re.findall(r'for \(AbstractMonster (\w+)', body)] else "enemy")
        inner = ','.join(args[1:])
        # パワー ctor を inner から探す
        pwm = re.search(r'new (\w+Power)\s*\(', inner)
        if not pwm:
            continue
        pw = pwm.group(1)
        # 値: ApplyPowerAction の量引数 or power ctor の数値
        amt = None
        if len(args) > 3:
            amt = resolve(args[3], base)
        if amt is None:
            for cand in reversed(args[1:]):
                if 'new' in cand:
                    continue
                v = resolve(cand, base)
                if v is not None:
                    amt = v
                    break
        if amt is None:
            amt = base.get("baseMagicNumber", 1)
        emit("apply_power", amt, pt,
             {"power": pw[:-5] if pw.endswith("Power") else pw})
        seen_cls.add("ApplyPowerAction")

    # --- オーブ/スタンス/その他 ---
    for args, _ in ctor_calls(body, "ChannelAction"):
        orb = None
        for a in args:
            oc = nested_ctor(a)
            if oc:
                orb = oc
        emit("channel", 1, None, {"orb": orb[:-3] if orb and orb.endswith("Orb") else orb})
        seen_cls.add("ChannelAction")
    for cls in ("ApplyStanceAction", "ChangeStanceAction", "StanceChangeAction"):
        for args, _ in ctor_calls(body, cls):
            stance = None
            for a in args:
                sm = re.search(r'"(\w+)"|Stance\.(\w+)|new (\w+)\(', a)
                if sm:
                    stance = next(g for g in sm.groups() if g)
            emit("enter_stance", 0, None, {"stance": stance})
            seen_cls.add(cls)
    for args, _ in ctor_calls(body, "EvokeAction"):
        v = resolve(args[-1], base) if args else None
        emit("evoke", v if v is not None else 1)
        seen_cls.add("EvokeAction")
    for cls in ("ExhaustAction", "ExhaustSpecificCardAction"):
        for args, _ in ctor_calls(body, cls):
            v = resolve(args[-1], base) if args else None
            emit("exhaust_card", v if isinstance(v, int) and v >= 0 else 1)
            seen_cls.add(cls)
    if 'new DiscardSpecificCardAction(' in body:
        emit("discard", 1)
    for cls in ("MakeTempCardInHandAction", "MakeTempCardInDrawPileAction",
                "MakeTempCardInDiscardAction", "MakeTempCardInDiscardAndDeckAction"):
        for args, _ in ctor_calls(body, cls):
            ref = None
            n = 1
            for a in args:
                oc = nested_ctor(a)
                if oc and oc in cls2id:
                    ref = cls2id[oc]
                elif oc and (oc.endswith("Card") or oc == "Shiv"):
                    ref = oc
                else:
                    v = resolve(a, base)
                    if v is not None:
                        n = v
            emit("add_card", n, None, {"card": ref} if ref else None)
            seen_cls.add(cls)
    for args, _ in ctor_calls(body, "RemoveAllBlockAction"):
        emit("lose_block", 0, dmg_tgt(args[0]) if args else "self")
    if 'new RemoveSpecificPowerAction(' in body:
        pwm = re.search(r'RemoveSpecificPowerAction\([^,]+,\s*[^,]+,\s*(?:new (\w+Power)|"(\w+)")', body)
        if pwm:
            emit("remove_power", 0, None, {"power": (pwm.group(1) or pwm.group(2) or "").replace("Power", "")})

    # --- カスタムアクション ---
    for cls, tpl in CUSTOM.items():
        if cls in seen_cls or ('new ' + cls + '(') not in body:
            continue
        for t in tpl:
            e = {k: (nval(v) if k == "n" else v) for k, v in t.items()}
            fx.append(e)
        seen_cls.add(cls)

    # --- 未知アクション: まずクラス内を再帰解析、駄目なら名前推定 ---
    _NAME_HINTS = [
        (r'DamageAll',  {"op": "damage", "n": "dmg", "tgt": "all_enemies"}),
        (r'DamageRandom', {"op": "damage", "n": "dmg", "tgt": "random_enemy"}),
        (r'Damage|Attack|Hit|Strike|Slash|Shoot|Shot|Kick|Blow|Pierce|Cut',
         {"op": "damage", "n": "dmg", "tgt": "enemy"}),
        (r'Block|Armor|Shield|Defend|Guard|Barrier|Protect',
         {"op": "block", "n": "blk", "tgt": "self"}),
        (r'Draw|Scry',   {"op": "draw", "n": "magic"}),
        (r'Energy|Charge', {"op": "gain_energy", "n": "magic"}),
        (r'Heal|Regen|Recover', {"op": "heal", "n": "magic", "tgt": "self"}),
        (r'Exhaust',     {"op": "exhaust_card", "n": 1}),
        (r'Discard',     {"op": "discard", "n": 1}),
        (r'Apply.*Power|Buff|Debuff|Power',
         {"op": "apply_power", "n": "magic", "tgt": None}),
        (r'Orb|Channel', {"op": "channel", "n": "magic"}),
        (r'Stance',      {"op": "enter_stance", "n": 0}),
        (r'LoseHp|SelfDamage|Hurt', {"op": "lose_hp", "n": "magic",
                                     "tgt": "self"}),
    ]
    _NAME_SKIP = re.compile(
        r'VFX|SFX|Effect|Sound|Talk|Wait|Shake|Tint|Flash|Anim|Text|Banner|'
        r'TextAbove|Speech|RollMove|SetMove|Escape|Suicide|Spawn|Summon|'
        r'HealCheck|HandCheck|StunCheck|UseCard|DiscardPile|DrawPile|'
        r'QueueCard|CardQueue|ShowCard|PlayCard|GainBlockAction|'
        r'InfoPanel|Screen|Dialog|Wait|Music|Voice|Shout|Portrait', re.I)
    for cls in set(re.findall(r'new (\w+Action)\s*\(', body)):
        if cls in seen_cls or cls in CUSTOM:
            continue
        seen_cls.add(cls)
        if _NAME_SKIP.search(cls):
            continue
        resolved = False
        if cls2file and cls in cls2file:
            n0 = len(fx)
            _scan_action_file(cls2file[cls], base, emit, resolve, nval,
                              cls2file, depth=1)
            resolved = len(fx) > n0
        if not resolved:
            for pat, tpl in _NAME_HINTS:
                if re.search(pat, cls):
                    e = dict(tpl)
                    e["n"] = nval(e["n"])
                    if e.get("tgt") is None:
                        e["tgt"] = "enemy" if tgt != "self" else "self"
                    e["guess"] = True
                    fx.append(e)
                    break

    # 同一 via アクション内の条件分岐を同一効果として重複抽出したものを畳む
    # (例: HaltAction の「基本ブロック3 / Wrath時追加」が block3 ×2 になる実害)
    # via 無しの重複は正当なマルチヒット等の可能性があるので残す
    seen_via = set()
    dedup = []
    for e in fx:
        if e.get("via"):
            k = (e["via"], e.get("op"), e.get("n"), e.get("tgt"),
                 e.get("power"))
            if k in seen_via:
                continue
            seen_via.add(k)
        dedup.append(e)
    fx = dedup
    # 条件分岐由来の enemy+all_enemies 重複: all_enemies を alt_tgt に退避
    singles = [e for e in fx
               if e.get("op") == "damage" and e.get("tgt") == "enemy"]
    aoes = [e for e in fx
            if e.get("op") == "damage" and e.get("tgt") == "all_enemies"]
    for s in singles:
        dup = next((a for a in aoes if a.get("n") == s.get("n")), None)
        if dup:
            s.setdefault("alt_tgt", "all_enemies")
            fx.remove(dup)
            aoes.remove(dup)

    # base 値はあるのに fx 空 → guess
    if not fx:
        if base.get("baseDamage", 0) > 0:
            emit("damage", base["baseDamage"], tgt, {"guess": True})
        if base.get("baseBlock", 0) > 0:
            emit("block", base["baseBlock"], "self", {"guess": True})
        if (base.get("baseMagicNumber", 0) > 0 and typ
                and (typ.group(1) if hasattr(typ, "group") else typ) == "POWER"):
            emit("apply_power", base["baseMagicNumber"], "self", {"guess": True})

    ent = {"fx": fx, "prov": "static", "conf": 0.9}
    if cost is not None:
        ent["cost"] = cost
    if typ:
        ent["type"] = typ.group(1) if hasattr(typ, "group") else typ
    if col:
        ent["color"] = col.group(1) if hasattr(col, "group") else col
    if rar:
        ent["rarity"] = rar.group(1) if hasattr(rar, "group") else rar
    if tgt:
        ent["target"] = tgt
    ent.update(flags)
    if upg:
        ent["upg"] = upg
    if stats and stats.get("upg"):
        merged = dict(stats["upg"])
        merged.update(upg)
        ent["upg"] = merged
    return cid, ent


def collect(src_root: str, mod_mode: bool = False, existing: dict | None = None,
            stats_map: dict | None = None):
    """src_root 配下の .java を解析して card エントリを返す。
    stats_map: {クラス名 or id: {"base":{..},"cost":..,"type":..,"target":..}}
      — データ駆動 mod の値を注入して this.damage 解決に使う。"""
    cls2id = dict(existing or {})
    files = []
    for root, _, fns in os.walk(src_root):
        for fn in fns:
            if fn.endswith(".java"):
                files.append(os.path.join(root, fn))
    cls2file = {os.path.splitext(os.path.basename(p))[0]: p for p in files}
    for p in files:
        s = open(p, encoding="utf-8", errors="replace").read()
        m = RE_ID.search(s) or RE_ID2.search(s)
        if m:
            cls2id[os.path.splitext(os.path.basename(p))[0]] = m.group(1)
        elif RE_ID3.search(s):
            cls2id[os.path.splitext(os.path.basename(p))[0]] = \
                os.path.splitext(os.path.basename(p))[0]

    cards, n_skip = {}, 0
    powers = {}
    for p in files:
        stem = os.path.splitext(os.path.basename(p))[0]
        st = (stats_map or {}).get(stem)
        r = parse_card(p, cls2id, mod_mode, st, cls2file)
        if r:
            cards[r[0]] = r[1]
        else:
            n_skip += 1
        # power 型メタ(apply_power の加点方向判定用)
        s = open(p, encoding="utf-8", errors="replace").read()
        if re.search(r'extends \w*Power\b', s):
            pt = re.search(r'PowerType\.(BUFF|DEBUFF)', s)
            if not pt:
                # 継承元名で推定(hsr の BuffPower/DebuffPower 等)
                em = re.search(r'extends\s+(\w+)', s)
                if em and "Debuff" in em.group(1):
                    pt = "debuff"
                elif em and "Buff" in em.group(1):
                    pt = "buff"
                else:
                    pt = None
            else:
                pt = pt.group(1).lower()
            pid_m = re.search(r'POWER_ID\s*=\s*"([^"]+)"', s)
            pid = pid_m.group(1) if pid_m else \
                stem[:-5] if stem.endswith("Power") else stem
            if pt:
                powers[pid] = pt
    return cards, cls2id, n_skip, powers


def main():
    import argparse
    global SRC, OUT
    ap = argparse.ArgumentParser(description="Parse locally supplied Java sources into card effects.")
    ap.add_argument("--source", default=SRC)
    ap.add_argument("--out", default=os.environ.get("STS1_KB_PATH", OUT))
    args = ap.parse_args()
    SRC, OUT = args.source, args.out
    if not os.path.isdir(SRC):
        ap.error("Provide --source with locally prepared Java sources; none are distributed here.")
    cards, _cls2id, n_skip, powers = collect(SRC)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "prov": "static", "cards": cards,
                   "powers": powers}, f, ensure_ascii=False, indent=1)
    print(f"cards={len(cards)} powers={len(powers)} "
          f"skipped={n_skip} -> {OUT}")


if __name__ == "__main__":
    main()
