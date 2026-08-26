# XREAL Air 2 / Air 2 Pro — 公式ファームウェアとの機能差

Air 2とAir 2 Proは同じ公式DP/MCUイメージを使います。このディレクトリのビルダーも
両機種に同じ出力を生成し、実機の機種IDに応じた公式のMonitor Nameを維持します。

ビルダーは指定SHA-256の公式イメージだけを受け付け、オフラインで決定論的に変換します。
ファームウェアの取得、USBデバイスの操作、実機への書込みは行いません。

前提となる共通仕様は[コンテナ形式](../../../docs/container-format.md)と
[HIDプロトコル](../../../docs/hid-protocol.md)を参照してください。

## 追加される機能

| 項目 | 公式ファームウェア | このビルド |
|---|---|---|
| native 1080p | 公式の標準表示経路 | 公式RGB profileと4-lane OLED tableを組み合わせたRGB表示 |
| 720p入力 | EDIDで提示しない | mode 1でtrue `1280x720@60`を提示し、`1920x1080`全面へ拡大 |
| 高リフレッシュへの復帰 | 720p入力を想定しない | 72/90/120 Hzでは720pをEDIDから外し、native timingへ復帰 |
| Full-SBS | 通常のDP link設定 | 60 / 72 / 90 HzをRGBで表示し、90 Hzでは`3840x1080@90`に必要なHBR2を使用 |
| HDMI変換器の音声 | 手動切替または対応Adapter通知 | 対象変換器ではUSBデータがない場合にDP音声へ自動切替 |
| 自動音声切替時の表示 | 完全切替ではEDIDを再列挙 | LPCM付きEDIDをB6/HPDで再列挙し、一時的に暗転 |
| 保存音量 | 公式経路で使用 | 自動DP音声でも保存済みgainを復元 |
| 給電維持HDMI抜き差し | 初回再接続で表示が壊れる場合がある | 完全切断edgeでlive B6を一度だけ反転し、変換器自身の遅延再訓練で復旧 |
| mode 9から通常2Dへ復帰 | mode stateを個別に更新 | mode 9専用状態を先に解除してからmode 1へ復帰 |

720pは公式イメージ内のYCbCr scaler profileとOLED group 1を使用します。nativeから720pへ
戻る瞬間だけYCbCr sidebandを設定し、steady 720p中は再書込みしません。これによりAir 2 Proでは
色境界を含むRGB/gradient patternがジラつかず安定しました。native 1080pはRGB profile 0、120 Hzは
対応するOLED group 3を使います。Full-SBSのDP側は公式のodd-profile選択を維持し、MCU側は
mode 3 / 4 / 9で`E0C0` RGBとOLED group 0を選びます。
表示中にRGB/YCbCrの共通設定を切り替える方式ではありません。

## 入出力

| 対象 | 公式ファイル | 公式SHA-256 | 公開出力SHA-256 |
|---|---|---|---|
| DP | `1140` | `350BACE369A83823D8EF867AE04AD07CF64D724C10EC7CEECFB83861AC9672F3` | `46556947E81DD7EBBD7F26B2541B63E0362804C166C020639DA908D2ABB2F486` |
| MCU | `09.1.00.180_20240507.bin` | `C07633E97215346468A18F5306A10F800388A80CCD7DCFE800D468F4AB1BFD49` | `950CA9535AFBD02C40D97A167DB06ECFAEEBC35F6ADCCDED81829CC44A8BE4C9` |

| 対象 | 出力container CRC | bank0 tag | 公式入力から変化するbyte位置数 |
|---|---:|---:|---:|
| DP | `0xA86203B1` | `0xBF` | 384 |
| MCU | `0xCFB740BE` | — | 526 |

## ビルド

```text
mkdir firmware/air2
python xreal/air2/build_dp.py --src firmware/air2/1140 --out air2-dp.bin
python xreal/air2/build_mcu.py --src firmware/air2/09.1.00.180_20240507.bin --out air2-mcu.bin
```

生成だけを検査する場合は`--check-only`、既存ファイルとの完全一致を調べる場合は
`--verify FILE`を使います。入力検査を無効化するオプションはありません。

## 書込みと復旧

公式イメージを`firmware/air2/`へ残した状態で、MCU、DPの順に書き込みます。

```text
python xreal/mcu_flash.py --image air2-mcu.bin --flash
python xreal/dp_flash.py --image air2-dp.bin --flash
```

公式状態へ戻す場合も同じ順序です。

```text
python xreal/mcu_flash.py --restore --flash
python xreal/dp_flash.py --restore --flash
```

フラッシャーはAir 2 / Air 2 ProのPID、公式入力と公開出力のSHA-256、container CRC、
DP bank0 tag、対応する公式復旧イメージを照合します。Air 2とAir 2 Proはproject code
`0x0900`を共有するため、project codeだけでは書込みを許可しません。

## 自動DP音声

MCUは公式の音声初期待機中にUSB `SET_ADDRESS`を監視します。ホストがUSBデバイスを
アドレス指定すればUSB音声を維持し、アドレス0のまま約5秒続いた場合だけ公式の完全な
DP音声切替を実行します。完全切替は`E0B8=1`のLPCM付きCTAを選び、B6/HPDでEDIDを
再列挙するため、一時的な暗転を伴います。

公式切替後は同じEDIDで遅延second-B6を発行して再訓練し、保存済みgainをSmartPAへ
再適用します。対象変換器と720pゲーム機では音声と縦筋のない映像を確認しています。
ほかのHDMI変換器で同じ動作を保証するものではありません。USB音声、手動音声切替、
対応Adapterの通知経路は公式動作を維持します。

## 給電維持HDMI抜き差し

対象変換器の給電を維持してHDMI入力だけを抜いた場合、MCUは
`E086/E088/E089/E090=02/01/02/04`の完全切断edgeで現在のB6を一度だけ反転します。
接続状態`E088=5`でedge latchを解除し、再接続側ではB6へ書きません。これにより変換器自身の
遅延再訓練を妨げず、Air 2 Proでは`B6 1→0`と`0→1`の両方向を含む連続試験が自動復旧しました。
この動作は対象変換器での実測に基づき、ほかの変換器との互換性を保証するものではありません。

実機確認範囲は[verification.md](verification.md)にまとめています。
