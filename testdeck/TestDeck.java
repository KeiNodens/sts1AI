package testdeck;

import basemod.BaseMod;
import basemod.interfaces.OnStartBattleSubscriber;
import basemod.interfaces.PostInitializeSubscriber;
import basemod.interfaces.OnPlayerTurnStartPostDrawSubscriber;
import com.evacipated.cardcrawl.modthespire.lib.SpireInitializer;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.helpers.CardLibrary;
import com.megacrit.cardcrawl.rooms.AbstractRoom;

@SpireInitializer
public class TestDeck implements PostInitializeSubscriber,
        OnStartBattleSubscriber, OnPlayerTurnStartPostDrawSubscriber {
    // 戦闘開始時に手札へ追加するカード ID
    private static final String[] IDS = {
        "SashWhip", "Halt", "HSRMod:Danheng0"
    };
    private int injected = 0;

    public static void initialize() {
        new TestDeck();
    }

    public TestDeck() {
        BaseMod.subscribe(this);
    }

    public void receivePostInitialize() {
    }

    public void receiveOnBattleStart(AbstractRoom room) {
        injected = 0;
    }

    // 各ターン(手札ドロー後)に差し込む(先頭数ターンのみ)
    public void receiveOnPlayerTurnStartPostDraw() {
        if (injected >= 5 || AbstractDungeon.player == null) {
            return;
        }
        injected++;
        for (String id : IDS) {
            AbstractCard c = CardLibrary.getCard(id);
            if (c != null) {
                AbstractDungeon.player.hand.addToHand(c.makeCopy());
            }
        }
    }
}
