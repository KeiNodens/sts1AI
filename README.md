# sts1AI

[![Python checks](https://github.com/KeiNodens/sts1AI/actions/workflows/ci.yml/badge.svg)](https://github.com/KeiNodens/sts1AI/actions)

Slay the Spireを、人間とAIで協力プレイするためのローカルツールです。Together in SpireとCommunication Modを使い、自作のAutoMP、HTTPブリッジ、MCPサーバー、カード評価器を組み合わせています。

自分のWindows環境で開発した実験的なプロジェクトです。セーブの衝突対策と再接続を含みます。他の利用者による導入や、あらゆるModの互換性は確認していません。ゲームや第三者Modの配布物は含みません。

## できること

- 同一PCの人間側・AI側をlocalhostで接続し、キャラクター指定や出発を補助する。
- 同一PCでのセーブ衝突を避けるため、AutoMPでプレイヤー別のセーブ名を使う。
- ゲーム状態を取得し、MCPからカード使用・ターン終了・選択などを行う。
- カードの効果を構造化して順序と組み合わせを評価し、実行前後の差分を記録する。

AIクライアントが判断する経路と、Pythonの定型処理で動く自動ドライバの両方があります。自動ドライバの結果をLLMのプレイ能力の指標としては扱っていません。

## 前提と導入

Windows、Python 3.11以降、購入済みのSlay the Spire、ModTheSpire、BaseMod、StSLib、Together in Spire、Communication Modが必要です。Java ModのビルドにはJDKとjarコマンドも必要です。

[Together in Spire](https://steamcommunity.com/sharedfiles/filedetails/?id=2384072973)、[Communication Mod](https://github.com/ForgottenArbiter/CommunicationMod)、[ModTheSpire](https://github.com/kiooeht/ModTheSpire)は提供元から別途取得してください。

このリポジトリだけを取得し、ルートで次を実行します。隣のsts2AIフォルダーは不要です。

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -c requirements-lock.txt .
.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

## AutoMPのビルド

ゲームと依存ModのJARへのパスを、自分の環境に置き換えてください。

```powershell
./scripts/build-mods.ps1 -GameJar '<game>/desktop-1.0.jar' -ModTheSpireJar '<path>/ModTheSpire.jar' -BaseModJar '<path>/BaseMod.jar' -StSLibJar '<path>/StSLib.jar' -TogetherInSpireJar '<path>/TogetherInSpire.jar' -JdkBin '<jdk>/bin'
```

out/automp.jarをゲームのmodsフォルダーへコピーします。out/testdeck.jarは検証用カード注入Modなので、通常のプレイには不要です。ビルド成果物には依存JARやゲームのクラスを含めません。

## Communication Modと起動

Communication Modのconfig.propertiesで、commandをこのリポジトリのPythonとブリッジに向けます。Communication Modはcommandを空白で区切り、引用符を解釈しません。この構成では、リポジトリを空白のないパスへ置いてください。Windowsのpropertiesではバックスラッシュのエスケープが必要なため、スラッシュ表記を使います。既存設定は先にバックアップしてください。

```properties
command=<repo>/.venv/Scripts/python.exe <repo>/sts1_bridge.py
runAtGameStart=true
```

人間側を起動してからAI側を起動します。ゲームのウィンドウが開き、AutoMPが接続を試みます。

```powershell
./scripts/launch.ps1 -GameDir '<game>' -ModTheSpireJar '<path>/ModTheSpire.jar' -Role host
./scripts/launch.ps1 -GameDir '<game>' -ModTheSpireJar '<path>/ModTheSpire.jar' -Role join
```

hostのブリッジは15532、AI側は15531、ゲーム同士の接続は49580です。-Characterでキャラクターを指定し、-Embarkで自動出発を有効にできます。セーブ名の変更と自動再接続はゲームに副作用があります。重要なセーブを退避し、テスト用のランで確認してください。

## MCPクライアントへの登録

設定例の`<repo>`を絶対パスに置き換えます。MCPは標準入出力を使います。

```json
{
  "mcpServers": {
    "sts1": {
      "command": "<repo>/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_bridge.server"],
      "env": {"STS1_KB_PATH": "<repo>/card_kb1.json"}
    }
  }
}
```

主なツールはget_game_state、get_decision_pack、play_card、end_turn、run_turn、flush_observationsです。ゲームを動かすツールは実際のランを進めます。ブリッジの変更先はSTS1_BRIDGE_BASEまたはサーバーの--base-urlで指定できます。

```powershell
.venv/Scripts/python.exe -m advisor.auto1 --steps 200
```

これはAIクライアントを使わずに動く定型ドライバです。ゲームを進行させ、観測をカードKBへ書き込みます。

## カード効果の知識ベース

生成済みの大規模KBは配布しません。ファイルがなければ、少数の手書きシードとルールで動作します。未知カードの効果を正確に評価できるとは限りません。保存先はSTS1_KB_PATH、既定は実行ディレクトリのcard_kb1.jsonです。

ローカルで用意したJavaソースを解析する場合:

```powershell
.venv/Scripts/python.exe -m tools.gen_card_kb1 --source '<local-sources>' --out card_kb1.json
```

任意のMod解析にはCFRを別途取得します。対象Modの条件を確認して自分のローカル環境で利用し、生成されたソースやKBをこのリポジトリへ追加しないでください。

```powershell
.venv/Scripts/python.exe -m tools.gen_mod_kb1 --cfr '<path>/cfr.jar' --game-dir '<game>' --workshop-dir '<workshop>/646570'
```

## 構成と検証

advisor/に評価・観測、mcp_bridge/にMCP、sts1_bridge.pyにゲームとの標準入出力の橋渡し、automp/とtestdeck/に自作Java Modがあります。tests/fixturesの小さな合成データでテストし、本番のKBは読みません。

公開用の確認結果と実機検証の区別は[VALIDATION.md](VALIDATION.md)、データと操作の注意点は[SECURITY.md](SECURITY.md)、出典は[NOTICE.md](NOTICE.md)を参照してください。自作部分は[MIT License](LICENSE)です。

各プロジェクトは別々の仮想環境へ導入してください。検証済みの依存バージョンはrequirements-lock.txtに固定しています。
