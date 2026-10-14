package automp;

import basemod.BaseMod;
import basemod.interfaces.PostInitializeSubscriber;
import com.evacipated.cardcrawl.modthespire.lib.SpireInitializer;
import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.megacrit.cardcrawl.characters.AbstractPlayer;
import com.megacrit.cardcrawl.core.CardCrawlGame;
import com.megacrit.cardcrawl.screens.mainMenu.MainMenuScreen;
import java.lang.reflect.Method;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import spireTogether.SpireTogetherMod;
import spireTogether.network.Integration;
import spireTogether.network.P2P.P2PManager;
import spireTogether.network.P2P.P2PPlayer;
import spireTogether.network.PF.PFClient;
import spireTogether.network.PF.PFPlayer;
import spireTogether.network.PF.PFServer;
import spireTogether.network.objects.settings.GameSettings;
import spireTogether.screens.ScreenManager;
import spireTogether.screens.lobby.MPLobbyScreen;

@SpireInitializer
public class AutoMP implements PostInitializeSubscriber {
    // env:
    //   TIS_AUTOMP  = "host" | "join"  (未設定なら何もしない)
    //   TIS_PORT    = PF port (default 49580)
    //   TIS_HOST_IP = join 先 IP (default 127.0.0.1)
    //   TIS_CHAR    = 自動キャラ選択 (enum名/クラス名/表示名, 大文字小文字無視)
    //   TIS_EMBARK  = "1" でロビー到達後に自動 embark
    //   TIS_ASC     = host 側アセンション (default: RECOMMENDED 値=1 のまま)
    private static String role = null;
    private static String port = "49580";
    private static String hostIP = "127.0.0.1";
    private static String charName = null;
    private static boolean autoEmbark = false;
    private static int asc = -1;

    // 0=無効/未読, 1=メニュー待ち, 2=ロビー処理, 9=完了
    private static volatile int state = 0;
    private static int menuTicks = 0;
    private static volatile boolean charApplied = false;
    private static volatile boolean embarked = false;
    // join 側再接続: 一度でも生きた PFClient を観測したら armed。
    // 切断時に TiS 本体は heartbeat timeout → メニューに戻すだけで
    // 再試行しないので、こちらで検知して doJoin フローへ戻す。
    private static volatile boolean joinArmed = false;
    private static int deadSeen = 0;

    public static void initialize() {
        new AutoMP();
    }

    public AutoMP() {
        BaseMod.subscribe(this);
    }

    public void receivePostInitialize() {
        readEnv();
    }

    private static void readEnv() {
        String r = System.getenv("TIS_AUTOMP");
        if (r == null) {
            return;
        }
        r = r.trim().toLowerCase();
        if (!r.equals("host") && !r.equals("join")) {
            log("TIS_AUTOMP=" + r + " は未対応 (host|join)");
            return;
        }
        role = r;
        String p = System.getenv("TIS_PORT");
        if (p != null && !p.trim().isEmpty()) {
            port = p.trim();
        }
        String ip = System.getenv("TIS_HOST_IP");
        if (ip != null && !ip.trim().isEmpty()) {
            hostIP = ip.trim();
        }
        String c = System.getenv("TIS_CHAR");
        if (c != null && !c.trim().isEmpty()) {
            charName = c.trim();
        }
        autoEmbark = "1".equals(System.getenv("TIS_EMBARK"));
        String a = System.getenv("TIS_ASC");
        if (a != null && !a.trim().isEmpty()) {
            try {
                asc = Integer.parseInt(a.trim());
            } catch (NumberFormatException ignored) {
            }
        }
        state = 1;
        log("enabled role=" + role + " port=" + port + " ip=" + hostIP
                + (charName != null ? " char=" + charName : "")
                + (autoEmbark ? " embark" : ""));
    }

    @SpirePatch(clz = CardCrawlGame.class, method = "update")
    public static class Ticker {
        public static void Postfix() {
            AutoMP.tick();
        }
    }

    // 同一PCの2インスタンスは multiplayer/saves/ を共有するため、
    // <gameID>.tis が最後に autosave した側のデータで上書きされ、
    // 再接続時に相手プレイヤーのキャラとして復元されてしまう。
    // ファイル名を <gameID>.p<playerID>.tis にして分離する。
    // 互換セーブ走査はファイル名ではなく中身の mpData.gameID で
    // 判定するので、suffix 込みでも検出・再開・削除はそのまま動く。
    @SpirePatch(clz = spireTogether.saves.objects.MultiplayerGameSave.class,
            method = SpirePatch.CONSTRUCTOR,
            paramtypez = {long.class, String.class,
                    spireTogether.network.P2P.P2PClientData.class})
    public static class PerPlayerSaveName {
        public static void Postfix(
                spireTogether.saves.objects.MultiplayerGameSave __instance) {
            try {
                P2PPlayer self = P2PManager.GetSelf();
                if (self == null || self.id == null || self.id < 0) {
                    return;
                }
                suffix(__instance, "filePath", ".p" + self.id);
                suffix(__instance, "localSaveFolderLoc", ".p" + self.id);
            } catch (Throwable ignored) {
            }
        }

        private static void suffix(Object inst, String name, String sfx)
                throws Exception {
            java.lang.reflect.Field f = findField(inst.getClass(), name);
            if (f == null) {
                return;
            }
            f.setAccessible(true);
            String v = (String) f.get(inst);
            if (v != null && v.endsWith(".tis")) {
                f.set(inst, v.substring(0, v.length() - 4) + sfx + ".tis");
            }
        }

        private static java.lang.reflect.Field findField(
                Class<?> c, String name) {
            while (c != null) {
                try {
                    return c.getDeclaredField(name);
                } catch (NoSuchFieldException e) {
                    c = c.getSuperclass();
                }
            }
            return null;
        }
    }

    private static void tick() {
        if (state == 0) {
            readEnv();
        }
        if (state == 0 || CardCrawlGame.mainMenuScreen == null) {
            return;
        }
        if ("join".equals(role)) {
            watchdogJoin();
        }
        if (state == 9) {
            return;
        }
        try {
            if (state == 1) {
                if (CardCrawlGame.mainMenuScreen.screen != MainMenuScreen.CurScreen.MAIN_MENU) {
                    return;
                }
                if (++menuTicks < 30) {
                    return;
                }
                if (P2PManager.data != null) {
                    state = 9;
                    return;
                }
                // Multiplayer メニューボタン押下時にやっている初期化を再現。
            // compatibleSaves が null のまま join すると register 処理で NPE になる。
            try {
                java.util.ArrayList<spireTogether.saves.objects.MultiplayerGameSave> saves =
                        spireTogether.saves.objects.MultiplayerGameSave.GetAllCompatibleSaves();
                // 同一PCでは <gameID>.p<id>.tis が全プレイヤー分混在する。
                // 再接続では playerID が再割当てされるため id での完全一致は
                // 使えず、「host は常に id=0」で区別する:
                //   join 側は非 host の save のみ、host 側は p0 のみを再開対象にする。
                // 同一ゲームの新旧 save が残る場合に備え saveTime 降順。
                java.util.Iterator<spireTogether.saves.objects.MultiplayerGameSave> it =
                        saves.iterator();
                while (it.hasNext()) {
                    spireTogether.saves.objects.MultiplayerGameSave s = it.next();
                    Integer pid = (s.playerMPData != null)
                            ? s.playerMPData.id : null;
                    boolean hostSave = pid != null && pid == 0;
                    if (role.equals("join") ? hostSave : !hostSave) {
                        it.remove();
                    }
                }
                saves.sort(new java.util.Comparator<spireTogether.saves.objects.MultiplayerGameSave>() {
                    public int compare(
                            spireTogether.saves.objects.MultiplayerGameSave a,
                            spireTogether.saves.objects.MultiplayerGameSave b) {
                        return Long.compare(b.saveTime, a.saveTime);
                    }
                });
                spireTogether.util.SpireVariables.compatibleSaves = saves;
            } catch (Throwable t) {
                t.printStackTrace();
            }
            try {
                spireTogether.util.SpireHelp.Multiplayer.ResetMod(false);
            } catch (Throwable t) {
                t.printStackTrace();
            }
            state = 2;
            if (role.equals("host")) {
                doHost();
            } else {
                doJoin();
            }
            }
            if (state == 2) {
                tickLobbyExtras();
            }
        } catch (Throwable t) {
            t.printStackTrace();
        }
    }

    private static void doHost() {
        try {
            SpireTogetherMod.HostPort = port;
            SpireTogetherMod.mpType = Integration.MPType.PORT_FORWARD;
            GameSettings settings = new GameSettings();
            if (asc >= 0) {
                settings.ascensionLevel = asc;
            }
            P2PManager.Init(settings);
            P2PManager.integration = new PFServer();
            if (!SpireTogetherMod.isConnected) {
                log("PFServer init failed; retrying");
                state = 1;
                menuTicks = 0;
                return;
            }
            P2PManager.AddPlayer(new PFPlayer(0));
            ScreenManager.Open(MPLobbyScreen.class);
            log("hosted on port " + port);
        } catch (Throwable t) {
            t.printStackTrace();
            state = 1;
            menuTicks = 0;
        }
    }

    private static void doJoin() {
        SpireTogetherMod.IP = hostIP;
        SpireTogetherMod.ConnectPort = port;
        SpireTogetherMod.mpType = Integration.MPType.PORT_FORWARD;
        Thread w = new Thread(new Runnable() {
            public void run() {
                while (state != 9 && P2PManager.data == null) {
                    PFClient c = null;
                    try {
                        c = new PFClient();
                    } catch (Throwable t) {
                        t.printStackTrace();
                    }
                    if (SpireTogetherMod.isConnected) {
                        P2PManager.integration = c;
                        log("connected to " + hostIP + ":" + port);
                        return;
                    }
                    if (c != null) {
                        try {
                            c.Terminate();
                        } catch (Throwable ignored) {
                        }
                    }
                    try {
                        Thread.sleep(1500);
                    } catch (InterruptedException ignored) {
                    }
                }
            }
        });
        w.setDaemon(true);
        w.start();
        log("joining " + hostIP + ":" + port + " ...");
    }

    // join 側の切断監視。PFClient が死んだ/heartbeat が止まったら
    // state=1 に戻して「compatibleSaves 再スキャン→ResetMod→再接続」
    // を走らせる。再接続ではサーバ側で playerID が振り直されるので、
    // register 後の LoadSave が自分の .p<id>.tis を拾って戦闘途中から
    // 復元される。doJoin のリトライ中 (一度も繋がっていない間) は
    // joinArmed=false なのでここでは何もしない。
    private static void watchdogJoin() {
        Integration integ = P2PManager.integration;
        boolean alive = false;
        if (integ instanceof PFClient && !integ.terminate) {
            PFClient c = (PFClient) integ;
            alive = true;
            if (c.heartbeat != null && c.heartbeat.lastReceived != null
                    && ChronoUnit.SECONDS.between(c.heartbeat.lastReceived,
                            LocalDateTime.now()) > 15) {
                alive = false;  // heartbeat 応答が 15s 以上無い
            }
        }
        if (alive) {
            joinArmed = true;
            deadSeen = 0;
            return;
        }
        if (!joinArmed || ++deadSeen < 90) {
            return;  // ~1.5s 様子見 (TiS 側の reset 処理と競合しないよう)
        }
        deadSeen = 0;
        joinArmed = false;
        log("connection lost; rejoining");
        try {
            if (integ != null) {
                integ.Terminate();
            }
        } catch (Throwable ignored) {
        }
        charApplied = false;
        embarked = false;
        state = 1;
        menuTicks = 0;
    }

    // ロビー到達後の自動キャラ選択 / 自動 embark
    private static void tickLobbyExtras() {
        if (!(ScreenManager.screen instanceof MPLobbyScreen)) {
            return;
        }
        P2PPlayer self;
        try {
            self = P2PManager.GetSelf();
        } catch (Throwable t) {
            return;
        }
        if (self == null) {
            return;
        }
        if (charName != null && !charApplied) {
            AbstractPlayer p = findChar(charName);
            if (p != null) {
                try {
                    // LoadCharacterModel 相当を cosmetic に依存せず直接設定。
                    // Embark() が実際に読むのは characterRender.playerClass と
                    // self.playerClass/HP だけ。
                    self.UpdatePlayerClass(p.chosenClass, true);
                    self.HP = p.maxHealth;
                    spireTogether.monsters.CharacterEntity e =
                            spireTogether.monsters.CharacterEntity.Get(p, false);
                    if (e != null) {
                        e.setRenderScale(e.lobbyScale);
                        e.SetDrawPosition(1420.0f
                                * spireTogether.util.SpireVariables.scale.x,
                                400.0f
                                * spireTogether.util.SpireVariables.scale.y);
                        MPLobbyScreen.characterRender = e;
                    }
                    charApplied = true;
                    log("char selected: " + p.chosenClass.name());
                } catch (Throwable t) {
                    t.printStackTrace();
                }
            } else {
                charApplied = true;
                log("char not found: " + charName);
            }
        }
        if (autoEmbark && !embarked && (charName == null || charApplied)) {
            try {
                self.startStatus = P2PPlayer.StartStatus.EMBARKED;
                Method m = MPLobbyScreen.class.getDeclaredMethod("Embark");
                m.setAccessible(true);
                m.invoke(ScreenManager.screen);
                embarked = true;
                state = 9;
                log("embarked");
            } catch (Throwable t) {
                t.printStackTrace();
            }
        }
    }

    private static AbstractPlayer findChar(String name) {
        for (AbstractPlayer p : CardCrawlGame.characterManager.getAllCharacters()) {
            if (p.chosenClass != null && p.chosenClass.name().equalsIgnoreCase(name)) {
                return p;
            }
            if (p.getClass().getSimpleName().equalsIgnoreCase(name)) {
                return p;
            }
            try {
                String n = p.getLocalizedCharacterName();
                if (n != null && n.equalsIgnoreCase(name)) {
                    return p;
                }
            } catch (Throwable ignored) {
            }
        }
        return null;
    }

    private static void log(String s) {
        System.out.println("[AutoMP] " + s);
    }
}
