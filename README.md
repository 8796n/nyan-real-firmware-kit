# nyan Real / Firmware Kit

メガネ型ディスプレイや周辺機器の公式ファームウェアを、手元で検証付きイメージへ改修するツール。

*[English version](README.en.md)*

メガネ向けには、パネル本来の解像度、表示モード、音声などを **nyan Real / Spatial Wall** で
快適に使うための改修を収録しています。周辺機器向けには、実機で再現・検証した互換性修正を
収録します。現在はXREAL Air系メガネとMOKIN UC6101B搭載ドックに対応しています。
Spatial Wallを使わない場合でも各ビルダーは単体で利用できます。

> **nyan Real / Spatial Wall** は電気メガネで空間ディスプレイを扱うためのアプリケーションです
> （Windows / macOS / GNOME / Raspberry Pi）。現在はマニュアルのみ先行公開で、本体は未公開です。
> → [nyan-real-spatial-wall](https://github.com/8796n/nyan-real-spatial-wall)

**本プロジェクトは XREAL（旧 Nreal）、Rokid、MOKINをはじめとするいかなるメーカーとも関係がなく、
承認も後援も受けていません。** 各社の製品名・ブランド名は、このツールが対象とする
ハードウェアを特定する目的でのみ使用しています。メーカーのコード・ブランド・
ファームウェアはここでは一切配布しません。

---

## 最初に読んでください

**このツールで生成したイメージは対象機器のファームウェアを書き換えます。壊れる可能性があります。
そのリスクを全面的に引き受けられない場合は使わないでください。**

次の3点は同時に成り立っていて、3つとも理解する必要があります。

1. **ファームウェアは一切配布しません。ベンダーのものも、パッチ済みのものもです。**
   パッチ済みイメージは 99% 以上がベンダーのコードです。公式ファームウェアはあなた自身が
   用意し、このリポジトリはそれをあなたの手元でパッチ済みイメージに変換します。

2. **入手した公式ファームウェアのファイルは、あなたの復旧手段です。**
   保管してください。1年後にも手元にある場所へバックアップしてください。それを失った状態で
   書き込みに失敗した場合、このリポジトリにできることはありません。

3. **本体から吸い出せるかは機種によります。当てにしないでください。**
   XREAL Air（第1世代）については、純正 MCU アプリケーションの静的解析で
   **読み出し不可を確認済み**です。ホストがアドレスと長さを指定してアプリ領域や
   ブート領域を読み出せる message id は存在せず、ツール側でバックアップを取ることは
   原理的にできません。Air 2 / Air 2 Proは完全なファームウェア読み出しの可否を未確認で、
   本ツールはいずれの機種にもバックアップ機能を提供しません。

**XREAL Air（第1世代）をBeam ProのNebulaで使うなら、Air用ビルドを書き込まないでください。
動かなくなります。**
詳細は[XREAL純正アプリについて](#xreal純正アプリについて)を参照してください。

ベンダーのファームウェアの提供・ホスティング・ミラー・入手方法の説明は行いません。
入手方法を尋ねる質問にも回答しません。ファームウェアのバイナリやダウンロードリンクを含む
Issue および Pull Request は削除します。

---

## 公式ファームウェアから変わること

対応しているのはXREAL Air（第1世代）、Air 2、Air 2 Pro、およびMOKIN UC6101B搭載ドックです。
XREAL Air系はいずれもDPブリッジとMCUを**対で更新**します。Air 2とAir 2 Proは公式イメージと
本キットの出力を共有します。

### XREAL Air（第1世代）

| 項目 | 公式ファームウェア | このビルド |
|---|---|---|
| native RGB | not RGBのOLED経路 | native 2DとFull-SBSをRGBで表示 |
| native解像度 | `1920x1080` | `1920x1200`をpreferred timingとして追加。`1920x1080`も利用可能 |
| 720p | EDIDで提示しない | mode 1でtrue `1280x720@60`を広告し、公式YCbCr scaler経路でパネル全面へ拡大。固定72 / 90 / 120 Hzモードでは広告しない |
| Full-SBS | `3840x1080` @ 60 / 72 Hz。90 Hzモードはあるが、帯域不足で正常動作しない | `3840x1200` @ 60 / 72 / 90 Hz。90 Hzも正常動作 |
| USBデータなしの音声 | 手動切替または対応Adapter通知 | 約5秒後にLPCM対応EDIDを再公告し、保存音量でDP音声へ自動切替（暗転あり） |
| 給電維持HDMI抜き差し | 変換器によって映像が復帰しない場合がある | 一時的な表示乱れの後、数秒で映像を自動復旧 |
| 消費電力 | 同一timing・最低輝度（設定値0）での基準 | 約0.18–0.19 W増（+13–16%） |

モード別の広告内容、タイミング、音声切替などの実装詳細は
[`xreal/air/docs/design.md`](xreal/air/docs/design.md)、実機結果は
[`xreal/air/docs/verification.md`](xreal/air/docs/verification.md)を参照してください。
自動DP音声とHDMI抜き差し復旧は実機試験した変換器での結果で、すべての変換器との互換性は
保証しません。またNVIDIAでpreferredより小さい解像度を真の線上信号として出すには、EDID構成
ごとにdisplay scalingを「なし」に設定する必要があります。

### XREAL Air 2 / Air 2 Pro

| 項目 | 公式ファームウェア | このビルド |
|---|---|---|
| native RGB | not RGBのOLED経路 | native 2DとFull-SBSをRGBで表示 |
| native解像度 | `1920x1080` | パネル自体が1080pのため`1920x1080`のまま |
| 720p | EDIDで提示しない | mode 1でtrue `1280x720@60`を広告し、公式YCbCr scaler経路でパネル全面へ拡大。固定72 / 90 / 120 Hzモードでは広告しない |
| Full-SBS | `3840x1080` @ 60 / 72 Hz。90 Hzモードはあるが、帯域不足で正常動作しない | `3840x1080` @ 60 / 72 / 90 Hz。90 Hzも正常動作 |
| USBデータなしの音声 | 手動切替または対応Adapter通知 | 約5秒後にLPCM対応EDIDを再公告し、保存音量でDP音声へ自動切替（暗転あり） |
| 給電維持HDMI抜き差し | 変換器によって映像が復帰しない場合がある | 復旧処理を追加。Air 2 Pro実機では一時的な表示乱れの後、数秒で自動復旧 |
| 消費電力 | 同一timing・最低輝度（設定値0）での基準 | Air 2実測で約0.17–0.18 W増（約+14%）。Air 2 Proは未測定 |

Air 2 / Air 2 Pro共通設計は[`xreal/air2/docs/design.md`](xreal/air2/docs/design.md)、
実機確認範囲は[`xreal/air2/docs/verification.md`](xreal/air2/docs/verification.md)にあります。音声と
hotplugの互換性は実機試験したHDMI変換器の範囲です。給電維持HDMI抜き差しのend-to-end確認は
Air 2 Proで行い、Air 2では未確認です。

両表の消費電力は、Airでは`1920x1080@90`、Air 2では`1920x1080@60`をidentity出力し、
最低輝度（設定値0）で全面black / whiteを表示したときのグラス全体のUSB入力電力です。内部回路単体の測定値ではありません。
native RGB化を含むこのビルドのトレードオフとして、公式より消費電力が増えます。増加した入力電力の
大部分は最終的に熱になるため、同じ使用条件では発熱も増えると想定されます。ただし、表面温度や
内部温度の上昇量は直接測定していません。

### native RGB化の見え方

公式ファームウェアにはYCbCrと名付けられたパネル経路がありますが、内部のsubsamplingまでは
確定していません。ここでは詳細を推定せず**not RGB**と表記します。このキットはnative 2Dと
Full-SBSをRGB888のままOLEDへ送り、not RGBへの変換を避けます。

| このビルド：native RGB | 公式ファームウェア：not RGB |
|---|---|
| ![滑らかなnative RGBグラデーション](docs/assets/gradient-rgb.png) | ![斜めに鱗状の階調境界が見えるnot RGBグラデーション](docs/assets/gradient-yuv.png) |

画像は見え方の違いを示す模式図で、パネルを撮影したものではありません。緩やかな色
グラデーションでは斜めに連なる階調境界が減り、より滑らかに見えます。

### MOKIN UC6101B搭載ドック

| 項目 | 公式ファームウェア | このビルド |
|---|---|---|
| Switch 2システムバージョン21.x | TVモードへ移行しない | TVモード、DisplayPort 2台同時出力を実機確認 |
| Nintendo VDM | 未認識commandを無応答で破棄 | 種別`0x20`の応答と状態リセット時パルスを追加 |
| 充電・復帰 | 基準 | 15 V / 2.6 A契約とスリープ復帰を実機確認 |

このビルダーはIntel HEXを生成するだけで、書き込み機能は含みません。変更内容は
[`peripherals/mokin/uc6101b/docs/design.md`](peripherals/mokin/uc6101b/docs/design.md)、実機確認範囲は
[`peripherals/mokin/uc6101b/docs/verification.md`](peripherals/mokin/uc6101b/docs/verification.md)を参照してください。

---

## 書き込み前の準備

### 1. 機種と公式ファイルを確認する

ビルダーが受け付ける公式入力と、生成する固定出力は次のとおりです。ハッシュはファイルの
入手先を示すものではなく、手元のファイルが検証済みの基準と同一か確認するためのものです。

| 機種 | 対象 | 公式ファイル | 公式入力SHA-256 | 出力SHA-256 |
|---|---|---|---|---|
| Air（第1世代） | DP | `firmware/1140` | `66A28C7BE1842D6837C68A5586CB0465099787F421427BE0CBE9691C858837DA` | `34AEE893AC697D314CB522D135AAE8C9222CC9461B62C096C616FEF44DE87AD8` |
| Air（第1世代） | MCU | `firmware/07.1.02.387_20240428.bin` | `B1784C6D618D3CF6F03D77A93442C3267A425CB2BE415E8912539E165645A3E7` | `F292B1245F2F26E209D6DACA6ADF50A58534B4EAEDC48C4FC8705703C879223D` |
| Air 2 / Air 2 Pro | DP | `firmware/air2/1140` | `350BACE369A83823D8EF867AE04AD07CF64D724C10EC7CEECFB83861AC9672F3` | `46556947E81DD7EBBD7F26B2541B63E0362804C166C020639DA908D2ABB2F486` |
| Air 2 / Air 2 Pro | MCU | `firmware/air2/09.1.00.180_20240507.bin` | `C07633E97215346468A18F5306A10F800388A80CCD7DCFE800D468F4AB1BFD49` | `950CA9535AFBD02C40D97A167DB06ECFAEEBC35F6ADCCDED81829CC44A8BE4C9` |
| MOKIN UC6101B | Intel HEX | `firmware/peripherals/mokin/uc6101b/XL_UC6101B_LT8712SX_Cto2DP+PD_V000612__20250724_CKS_0x1152B5C_WithPDtoC.HEX` | `BE3C7FD831B7D3C1C6D822D70C72EACF2DA21958E03C6448A9857DB6D762AA7D` | `0DB0BF009776115FA890BDE71C6CC858CD102693A4B3D2CEF99F207826372CF1` |

公式ファイルは上表の場所へ置き、別の安全な場所にもバックアップしてください。`firmware/`は
gitignoreされており、中身がこのリポジトリへコミットされることはありません。

### 2. Pythonと依存パッケージを用意する

Python 3.10以降を使います。ビルダーは標準ライブラリだけで動きます。書き込み、表示モード操作、
VSYNC、レジスタ診断などUSB HIDを使うツールには`hidapi`が必要です。

```bash
pip install -r requirements.txt
```

PyPIには`import hid`を提供する別パッケージもあります。必要なのはコンパイル済みbindingを含む
`hidapi`です。別の`hid`パッケージを同時に入れないでください。

### 3. 対応OSとUSB接続を確認する

実機書き込みを検証したOSはWindowsです。純粋なPythonのビルダーはLinux / macOSでも動きます。
HIDツールも動作する見込みですが未検証です。Windows専用の表示診断もあります。

| 処理 | Windows | Linux / macOS |
|---|---|---|
| DP / MCUイメージのビルド | 対応 | 対応 |
| UC6101B Intel HEXのビルド | 対応 | 対応 |
| DP / MCUの書き込み | 対応・実機確認済み | 未検証 |
| HID表示・レジスタ診断 | 対応 | 未検証 |
| EDID取得、Windows線上信号の確認 | 対応 | 非対応 |

`xreal/display.py --probe`はWindows専用の`edid_dump.py`を呼ぶため、Linux / macOSでは使えません。
通常のモード取得・切替はHID表示ツールとして未検証です。

書き込み時は対象グラスをPCへ直接USB接続し、他のXREAL / Nreal HID機器を外してください。
Linuxではrootを使うか、次のudev ruleなどで`hidraw`へのアクセスを許可します。

```text
# /etc/udev/rules.d/70-xreal.rules
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3318", MODE="0666"
```

---

## スクリプトの役割

### イメージを作る

| スクリプト | 対象 | ハードウェアへの書き込み |
|---|---|---|
| `xreal/air/build_dp.py` | Air（第1世代）のDPイメージ | しない |
| `xreal/air/build_mcu.py` | Air（第1世代）のMCUイメージ | しない |
| `xreal/air2/build_dp.py` | Air 2 / Air 2 Pro共通DPイメージ | しない |
| `xreal/air2/build_mcu.py` | Air 2 / Air 2 Pro共通MCUイメージ | しない |
| `peripherals/mokin/uc6101b/build.py` | UC6101B Intel HEX | しない |

各ビルダーは公式入力のSHA、全パッチ位置のbefore byte、生成後のSHA、機器固有のCRCまたは
checksum、変更範囲を検査します。想定外の入力や結果は拒否し、`--force`はありません。

### XREAL Air系のイメージを書き込む

| スクリプト | 役割 | 書き込み条件 |
|---|---|---|
| `xreal/dp_flash.py` | DPブリッジの確認・書き込み・純正復旧 | `--flash`を付けた場合だけ送信 |
| `xreal/mcu_flash.py` | MCUの検証・書き込み・純正復旧 | `--flash`を付けた場合だけ送信 |

両ツールは接続中のUSB PIDと機種、既知イメージの正確なSHA、project code、コンテナ検査、
対応する純正復旧ファイルを照合します。Air 2とAir 2 Proはproject codeを共有しますが、USB PIDは
別々に確認します。判定を無効化するオプションはありません。

### 状態を確認する

| スクリプト | 内容 | 純正ファームウェア |
|---|---|---|
| `common/display_signal.py` | Windowsのデスクトップ解像度と線上信号を分けて表示 | 使用可 |
| `xreal/edid_dump.py` | ホストが受け取ったEDIDを取得・デコード | 使用可 |
| `xreal/display.py` | Air系の論理表示モードを取得・切替 | 使用可 |
| `xreal/vsync.py` | パネルVSYNCを実測 | 使用可 |
| `xreal/dpreg.py` | DPブリッジのレジスタを読む | 本キットのMCUが必要 |
| `xreal/panelreg.py` | パネルレジスタを読み書きする | 本キットのMCUが必要 |

`display.py`はモード切替時にHPDをトグルするため数秒暗転します。`panelreg.py`の書き込み先は
パネルのRAMで、電源を入れ直すと元へ戻ります。

---

## MOKIN UC6101Bイメージを作る

```bash
python peripherals/mokin/uc6101b/build.py \
  --src firmware/peripherals/mokin/uc6101b/XL_UC6101B_LT8712SX_Cto2DP+PD_V000612__20250724_CKS_0x1152B5C_WithPDtoC.HEX \
  --out uc6101b-switch2.hex
```

この処理はハードウェアへアクセスしません。書き込み前に出力SHAが準備表と一致することを確認し、
公式イメージを復旧用に保管してください。詳しい使い方と書き込み時の注意は
[`peripherals/mokin/uc6101b/README.md`](peripherals/mokin/uc6101b/README.md)にあります。

---

## XREAL Air系のビルドから書き込みまで

DPとMCUは必ず同じ機種向けの組を使ってください。以下はリポジトリのルートで実行します。

### 1. パッチ済みイメージを生成する

Air（第1世代）：

```bash
python xreal/air/build_dp.py  --src firmware/1140                     --out air-dp.bin
python xreal/air/build_mcu.py --src firmware/07.1.02.387_20240428.bin --out air-mcu.bin
```

Air 2 / Air 2 Pro：

```bash
python xreal/air2/build_dp.py  --src firmware/air2/1140                         --out air2-dp.bin
python xreal/air2/build_mcu.py --src firmware/air2/09.1.00.180_20240507.bin     --out air2-mcu.bin
```

生成せず検証だけ行う場合は`--check-only`を使います。

```bash
python xreal/air/build_dp.py --src firmware/1140 --check-only
```

既に生成したファイルが決定論的な出力と完全一致するかは`--verify`で確認できます。

```bash
python xreal/air/build_dp.py --src firmware/1140 --verify air-dp.bin
```

### 2. 書き込み前にイメージを検査する

DPツールを引数なしで実行すると、接続中の機種と動作中のDP版数だけを読みます。何も書きません。

```bash
python xreal/dp_flash.py
```

生成したイメージも`--flash`なしで検査できます。

```bash
python xreal/dp_flash.py  --image air-dp.bin
python xreal/mcu_flash.py --image air-mcu.bin --verify-only
```

Air 2 / Air 2 Proではファイル名を`air2-dp.bin`、`air2-mcu.bin`へ読み替えてください。ここで表示される
機種、SHA、CRC、DP bank tagが準備表と一致しなければ書き込みへ進まないでください。

### 3. 機種ごとの順序で書き込む

#### Air（第1世代）：DP → MCU

```bash
python xreal/dp_flash.py  --image air-dp.bin  --flash
python xreal/mcu_flash.py --image air-mcu.bin --flash
```

#### Air 2 / Air 2 Pro：MCU → DP

```bash
python xreal/mcu_flash.py --image air2-mcu.bin --flash
python xreal/dp_flash.py  --image air2-dp.bin  --flash
```

`--flash`を付けた呼び出しだけが実際に送信します。転送中はケーブルを抜かず、PCをスリープさせないで
ください。DPはFINISH後に自分で再起動し、MCUはbootloader経由でAPPへ復帰するため、正常終了後の
抜き差しは不要です。

### 4. 書き込み後を確認する

もう一度`python xreal/dp_flash.py`を実行し、DP版数が`1140`であることを確認します。`1109`なら
fallbackへ落ちているため、[うまくいかなかったとき](#うまくいかなかったとき)を参照してください。

表示は普段使う解像度、リフレッシュ、Full-SBS、音声経路で確認してください。表示信号やEDIDを
記録する場合は前節の診断スクリプトを使います。コンテナの版数文字列は公式のままなので、
改造済みかどうかは生成SHAと手元の記録で管理してください。

---

## XREAL Air系を純正へ戻す

最初に保存した純正ファイルが準備表の場所に必要です。対応グラスだけを直接USB接続し、MCUを先、
DPを後の順に戻します。

```bash
python xreal/mcu_flash.py --restore --flash
python xreal/dp_flash.py  --restore --flash
```

純正復旧イメージのSHAと接続中のPIDも、通常の書き込みと同じ基準で検査されます。

---

## XREAL純正アプリについて

**XREAL Air（第1世代）をBeam ProのNebulaで使うなら、Air用ビルドを書き込まないでください。
動かなくなります。**

Nebulaのようにグラスへ映像を出すアプリは、レンズの歪みを打ち消す補正をかけて描画します。
その補正データは1080p分しかありません。Air用ビルドは1200pをpreferred timingにするため、
Beam Pro版Nebulaは起動画面から先へ進みません。実機で確認済みで、純正へ戻す以外の回避策は
ありません。通常の外部ディスプレイとして使う場合は問題ありません。

このビルドはコンテナヘッダの版数を変えないため、NebulaやBeam Proが自動的に純正へ戻すことも
ありません。

Air 2 / Air 2 Proはpreferred timingを`1920x1080`から変更せず、どちらもXREAL Beam Proで
通常動作することを実機確認済みです。

USBデータを運ばないHDMI変換経路では、自動DP音声の完全切替後にUSB複合デバイスが閉じます。
対象接続には最初からUSBデータ経路がないためHID制御はできません。USB対応ホストへつなぎ直すと
戻ります。

---

## なぜ生成結果を確認できるのか

ビルダーは単にパッチを当てるだけでなく、次を毎回検証します。

- 公式入力のSHA-256、project code、コンテナCRC
- ラベル付き変更レコードのbefore byteと変更範囲
- 決定論的な出力SHA-256、コンテナCRC、DP bank0 commit tag、変更バイト数
- 生成EDIDのchecksum、DTD / VIC、論理モードごとの広告内容
- Air DPの8051 helper全状態ベクタ、Air 2系DPのEDID / RGB profile contract
- MCU側の表示・復旧policy model
- UC6101BのIntel HEX record、Block 1 CRC-8、image checksum、変更アドレス集合

実機の詳細は各機種の`docs/verification.md`にあります。
共通仕様は[コンテナ形式](docs/container-format.md)と
[HIDプロトコル](docs/hid-protocol.md)を参照してください。

---

## XREAL Air系でうまくいかなかったとき

**別機種イメージを選んだ。** フラッシャーはUSB PIDと固定SHAの組が一致しなければ送信を拒否します。
判定を回避せず、接続中の機種とファイル名を確認してください。

**DPがfallbackイメージで起動した。** 症状はDP版数`1109`、モニタ名`nreal air`、60 Hz固定、
モード切替不能です。bank0が拒否されていますが復旧可能です。正常な対応DPイメージ、または
`--restore`で純正DPを書き直してください。

**MCU APPが起動しない。** USBの接続と切断を繰り返す場合は、ボタンを保持しながらUSB接続して
bootloaderへ入り、保存した純正MCUを`--restore --flash`で戻してください。

**転送が中断した、FINISHが異常statusを返した。** 同じ電源状態で再試行せず、一度抜き差しして
MCUをリセットしてからやり直してください。正常に完了した場合は抜き差し不要です。

---

## リポジトリ構成

```text
xreal/          XREAL Air系のHID、書き込み、診断ツール
  air/          Air（第1世代）のビルダーと設計・検証文書
  air2/         Air 2 / Air 2 Pro共通のビルダーと設計・検証文書
peripherals/    ドック、変換器など周辺機器のビルダーと設計・検証文書
common/         機種非依存の表示診断
docs/           コンテナ形式、HIDプロトコル、共通資料
firmware/       利用者が用意した公式ファイルの置き場所（gitignore）
```

表にない機種とファームウェア版は対象外です。似た型番や同じVIDを持つ別系統の機種へ流用しないでください。

---

## ライセンス

本リポジトリのコードとドキュメントは[Apache License 2.0](LICENSE)の下で提供されます。

このライセンスは、ツールが操作対象とするベンダーのファームウェアには及びません。当該
ファームウェアは権利者に帰属し、いかなる形でも本リポジトリには含まれていません。

---

## コントリビュート

対応機種でのバグ報告と実機検証結果、および検証可能な新機種対応を歓迎します。とくに未検証の
OS・ホスト環境からの報告と、各機種の`docs/verification.md`と違う値が出たケースは貴重です。

**ファームウェアのバイナリ、ダウンロードリンク、およびそれらを求める投稿はしないでください。**
該当するIssueやコメントは議論なく削除します。

詳細は[CONTRIBUTING.md](CONTRIBUTING.md)を参照してください。
