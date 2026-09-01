# コントリビュートについて

*English follows the Japanese.*

## 絶対に投稿しないでください

**ファームウェアのバイナリ、ダウンロードリンク、ミラー、入手方法を尋ねる質問。**

Issue、Pull Request、コメント、いずれも対象です。該当するものは**議論なく削除**します。
悪意の有無は関係ありません。

このリポジトリはベンダーのファームウェアを配布しません。パッチ済みイメージも配布しません。
パッチ済みイメージは 99% 以上がベンダーのコードだからです。入手経路の説明もしません。
必要なファイルとその SHA-256 は README に書いてあります。それと一致するものを
自分で用意してください。

この方針について議論の余地はありません。方針が気に入らない場合、このリポジトリは
あなたの用途に合いません。

---

## 歓迎するもの

### 実機での検証結果

**いちばん価値があります。** とくに次のような報告です。

- 未検証の OS（Linux、macOS）
- 未検証のホスト環境（AMD、Intel 内蔵、Apple Silicon、各種 HDMI 変換器、ゲーム機）
- `xreal/air/docs/verification.md`または`xreal/air2/docs/verification.md`の表と**違う値**が出たケース
- `peripherals/mokin/uc6101b/docs/verification.md`の未確認項目または**違う結果**

READMEの「公式ファームウェアから変わること」に記載された機種の報告を優先します。新機種対応は、
公式入力SHA、全変更のbefore byte、決定論的な出力SHA、機器固有checksum、解析根拠、復旧手段、
実機確認範囲を揃えたものを歓迎します。

値が違うこと自体が有益な情報です。「合わなかった」報告を歓迎します。

報告には次を含めてください。

- 機種と、書き込んだイメージの SHA-256
- ツールの出力（そのまま貼ってください。要約しないでください）
- ホスト環境（OS、GPU、接続方法）

### 不具合の報告

再現手順と、ツールが実際に出力した内容を添えてください。

---

## コードを送るとき

- **`*.bin`、`*.hex`、`*.HEX`を含めないでください。** `.gitignore` で弾いていますが、念のため確認してください
- 端末のシリアル番号、個人のファイルパス、認証情報を含めないでください
- ツールのコメントとメッセージは英語です。ドキュメントは日本語が正本です
- ビルダは標準ライブラリだけで動きます。**依存を増やさないでください**

### 検証を弱めないでください

ビルダは結果を検証してから返します。SHAの照合、レコードごとのbefore検査に加え、
Air DPでは8051 helperの全状態ベクタ、Air 2系DPではEDID / RGB profile contract、
MCUでは表示・復旧policy model、UC6101BではIntel HEX record、Block 1 CRC、image checksumを
検査します。**`--force`はありません。**
これは意図的な設計です。検証を迂回する仕組みを追加する Pull Request は受け付けません。

書き込みツールも同じです。対応する接続PID、その機種向けの既知SHA-256との完全一致、
コンテナCRC、DPのbank0 tag、機種に合う公式復旧イメージをすべて確認します。
projectCodeはその一部にすぎず、Air 2とAir 2 Proは`0x0900`を共有します。

---

## 安全について

**このツールで生成したイメージは機器のファームウェアを書き換えます。壊れる可能性があります。**

復旧手段は、あなたが入手した公式ファームウェアのファイルだけです。機種によっては
本体から吸い出せません。詳細は README の「最初に読んでください」を参照してください。

他人に「これを焼けば直る」と勧める前に、その人が復旧手段を持っているか確認してください。

---
---

# Contributing

## Never post these

**Firmware binaries, download links, mirrors, or questions asking where to get
them.**

That covers issues, pull requests and comments alike. Anything matching will be
**removed without discussion.** Intent does not matter.

This repository distributes no vendor firmware, and no patched images either --
a patched image is over 99% vendor code. We also do not explain how to obtain
it. The files you need and their SHA-256 are in the README; supply matching
files yourself.

This policy is not open for debate. If you disagree with it, this repository is
not for you.

---

## What is welcome

### Hardware test results

**These are the most valuable contributions.** Especially:

- operating systems not verified here (Linux, macOS)
- host setups not verified here (AMD, Intel integrated, Apple Silicon, HDMI
  converters, consoles)
- **any case where you measure something different** from the tables in
  `xreal/air/docs/verification.md` or `xreal/air2/docs/verification.md`
- untested cases or **different results** from
  `peripherals/mokin/uc6101b/docs/verification.md`

Reports for devices listed under "What changes from the official firmware" in
the README take priority. New-device support is welcome when it includes the
official input SHA, before bytes for every change, deterministic output SHA,
device-specific checksums, analysis, a recovery path, and documented hardware
test coverage.

A mismatch is useful information. Reports that something did not line up are
welcome.

Include:

- the model, and the SHA-256 of the image you flashed
- the tool output, pasted verbatim rather than summarised
- your host setup: OS, GPU, how it is connected

### Bug reports

Include how to reproduce it and what the tools actually printed.

---

## Sending code

- **Do not include `*.bin`, `*.hex`, or `*.HEX`.** `.gitignore` blocks them; check anyway
- No device serial numbers, personal file paths or credentials
- Comments and messages in the tools are English. Documentation is
  Japanese-primary
- The builders run on the standard library alone. **Do not add dependencies**

### Do not weaken the verification

The builders prove their result before returning it: hash checks and per-record
before-image guards. Air DP additionally runs the 8051 helper
over every state vector; Air 2-family DP checks the EDID and RGB-profile
contracts; MCU builders check their display and recovery policy models; and the
UC6101B builder validates Intel HEX records, the Block 1 CRC, and the image
checksum. **There is no `--force`,** and that is deliberate. Pull requests that
add a way around the verification will not be accepted.

The same goes for the flashers. They require a supported connected PID, an exact
known SHA-256 for that model, the container CRC, the DP bank0 tag, and the
matching official stock recovery image. projectCode is only one part of this;
Air 2 and Air 2 Pro share `0x0900`.

---

## Safety

**Images produced by these tools rewrite firmware. They can break the device.**

Your only recovery path is the official firmware file you obtained. On some
models the device cannot be read back at all. See "Read this before anything
else" in the README.

Before telling someone else to flash something, check that they have a recovery
path.
