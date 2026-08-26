# XREAL Air 2 / Air 2 Pro — 公開版の実機確認

## 対象

```text
DP   SHA-256 46556947E81DD7EBBD7F26B2541B63E0362804C166C020639DA908D2ABB2F486
MCU  SHA-256 950CA9535AFBD02C40D97A167DB06ECFAEEBC35F6ADCCDED81829CC44A8BE4C9
```

共通の表示経路はAir 2とAir 2 Proの両方で確認しました。音声付きEDID再列挙はAir 2で、
現行production MCUの自動DP音声と給電維持hotplug復旧はAir 2 Proでend-to-end確認しています。
Windows PC、NVIDIA GPU、720pゲーム機、対象
HDMI→USB-C/DP変換器を使用し、表示信号はWindows DisplayConfigのidentity scaling、
DPレジスタ、panel VSYNCと目視を組み合わせて判定しています。

## ビルド検査

| 対象 | 結果 |
|---|---|
| DP | 公式`1140`から直接生成し、公開SHA、CRC `0xA86203B1`、bank0 tag `0xBF`、384 changed bytesが一致 |
| MCU | 公式`09.1.00.180_20240507.bin`から直接生成し、公開SHA、CRC `0xCFB740BE`、526 changed bytesが一致 |
| 再現性 | 各ビルダーを繰り返してbyte-identical |
| 変更範囲 | 固定before/afterレコード外の変更なし |
| EDID | Air 2 / Air 2 Proの公式Monitor Nameとbase checksumを維持 |
| 書込み制限 | 両機種の個別PID、公開SHA、container、公式復旧イメージを照合 |

## Air 2

| 項目 | 実測結果 |
|---|---|
| MCU書込み | APP `0x0428` → BOOT `0x0427` → APP `0x0428`、3598 logical / 3599 wire packet、FINISH/JUMP_TO_APP status 0 |
| DP書込み | 1208 packet、FINISH ACK、MCU側CRC確認後にDP version `1140` |
| 冷間起動 | `1920x1080@60`、identity scaling、panel `60.002 Hz`、RGB色順・全幅・両眼正常 |
| 2D 60 / 72 / 90 / 120 Hz | `1920x1080`、identity scaling、panel `60.002 / 71.999 / 90.001 / 120.005 Hz`、色・全幅正常、縦筋・ちらつきなし |
| Full-SBS 60 / 72 / 90 Hz | `3840x1080`、identity scaling、左右・色正常、縦筋・ちらつきなし。現行pairの90 Hzは線上`445.5 MHz` / HBR2で再確認 |
| true 720p60 | 線上`1280x720` / `74.25 MHz`、identity scaling、panel `60.002 Hz`、全画面・全幅・色正常、RGB/gradient patternでジラつき・縦筋なし |
| mode切替 | 現行pairでFull-SBS 90 Hz→native 1080p→true 720p→native→true 720pを確認。各経路で色・全幅・安定性を維持 |
| 再接続 | 抜き差し後もmode 1、`1920x1080@60`、RGB表示正常 |
| XREAL Beam Pro | 通常動作を確認 |
| 対象変換器 | 720pゲーム機のcold接続で音声付きEDID再列挙、自動DP音声、保存音量、縦筋なしを確認。切替中は一時的に暗転 |

## Air 2 Pro

| 項目 | 実測結果 |
|---|---|
| MCU書込み | APP `0x0432` → BOOT `0x0431` → APP `0x0432`、3598 logical / 3599 wire packet |
| DP書込み | 1208 packet、FINISH ACK、MCU側CRC確認後にDP version `1140` |
| 冷間起動 | `1920x1080@60`、RGB色順・全幅・両眼正常 |
| 2D 60 / 72 / 90 / 120 Hz | `1920x1080`、identity scaling、色・全幅正常、縦筋・ちらつきなし |
| Full-SBS 60 / 72 / 90 Hz | `3840x1080`、identity scaling、左右・色正常、縦筋・ちらつきなし。90 HzはHBR2 |
| true 720p60 | 線上`1280x720`、identity scaling、全画面・全幅・色正常。RGB/gradient patternでジラつきなし |
| mode切替 | 現行DPで720p→native 1080p RGB→720pを確認後、同じ往復を3回追加実施。全幅・RGB順・正常色・安定性を維持。mode 9→mode 1と各2D/Full-SBS間は直前の共通baseで確認済み |
| XREAL Beam Pro | 通常動作を確認 |
| 対象変換器 | production MCU `950CA953...`と現行DPで、電源専用USB給電・720pゲーム機を使用。起動約5秒後の暗転、DP音声ON、正常映像を確認。給電維持のHDMI抜き差しも、一時的に壊れた後数秒で自動正常化することを複数回確認 |

現行DPはAir 2 Proで、cold true 720p、native 1080p RGB、720pへの復帰、追加3往復のすべてが
ジラつき・ピンク被り・色順異常なしで安定しました。Air 2にも現行MCU/DP pairを再書込みし、
Full-SBS 90 Hz、native 1080p、true 720p、nativeへの復帰、720pへの再復帰を確認しました。
すべてRGB/gradient patternでジラつき・縦筋・色異常なしです。steady 720p中はsidebandを
書き直さず、nativeから720pへ戻る瞬間だけ復元します。

旧MCU `E508...`では給電維持HDMI抜き差しの初回再接続で表示が壊れました。Air方式を直接移植した
`5B2AC937...`は無限再起動となったため不採用です。最終版は完全切断tuple
`E086/E088/E089/E090=02/01/02/04`のedgeごとにlive B6を一度だけ反転し、再接続側では
B6へ書きません。診断付き版で`B6 1→0`と`0→1`の両方向を反復確認後、同じruntime 106 bytesを
持ち診断を除去したproduction版 `950CA953...`でも電源専用USB給電の実使用試験が合格しました。

## 消費電力

Air 2の給電経路にChargerLAB POWER-Z KM003Cを直列接続し、現行RGB版A → 公式B →
現行RGB版A′の順で測定しました。入力は`1920x1080@60`、identity scaling、mode 1、
最低輝度（設定値0）です。各black / white区間は安定後10秒採取し、AとA′の差はblack
`0.372%`、white `0.079%`で再現性基準の1%以内でした。

| pattern | 公式B | 現行RGB版A′ | A′ − B | 公式比 |
|---|---:|---:|---:|---:|
| black | 1.177196 W | 1.345050 W | **+0.167854 W** | **+14.26%** |
| white | 1.301094 W | 1.484802 W | **+0.183709 W** | **+14.12%** |

これはAir 2全体のUSB入力電力で、特定回路の消費電力ではありません。DPとMCUをpairで
切り替えているため、差にはファームウェア変更全体が含まれます。Air 2 Proの消費電力は
測定していません。表面温度と内部温度も未測定です。

## オフラインでの再検証

```text
python xreal/air2/build_dp.py --src firmware/air2/1140 --check-only
python xreal/air2/build_mcu.py --src firmware/air2/09.1.00.180_20240507.bin --check-only
python xreal/dp_flash.py --self-test
python xreal/mcu_flash.py --self-test
```

生成済みファイルとの完全一致は`--verify FILE`で確認できます。

確認範囲は上記のWindows/NVIDIA環境と対象変換器です。ほかのGPU、OS、HDMI変換器でも
表示用の公開機能は同じですが、変換器固有の自動DP音声は同じ動作を保証しません。
