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

- 未検証の機種（Air 2、Air 2 Pro など）
- 未検証の OS（Linux、macOS）
- 未検証のホスト環境（AMD、Intel 内蔵、Apple Silicon、各種 HDMI 変換器、ゲーム機）
- `xreal/air/docs/verification.md` の表と**違う値**が出たケース

値が違うこと自体が有益な情報です。「合わなかった」報告を歓迎します。

報告には次を含めてください。

- 機種と、書き込んだイメージの SHA-256
- ツールの出力（そのまま貼ってください。要約しないでください）
- ホスト環境（OS、GPU、接続方法）

### 不具合の報告

再現手順と、ツールが実際に出力した内容を添えてください。

### 他機種への対応

`docs/hid-protocol.md` の「移植するときに見る順番」から始めてください。
**フレームが通ることと、任意の msgid が実装されていることは別です。**
コンテナ形式も機種ごとに違います（`docs/container-format.md`）。

---

## コードを送るとき

- **`*.bin` を含めないでください。** `.gitignore` で弾いていますが、念のため確認してください
- 端末のシリアル番号、個人のファイルパス、認証情報を含めないでください
- ツールのコメントとメッセージは英語です。ドキュメントは日本語が正本です
- ビルダは標準ライブラリだけで動きます。**依存を増やさないでください**

### 検証を弱めないでください

ビルダは結果を検証してから返します。SHA の照合、レコードごとの before 検査、
EDID のデコード、8051 helper の全状態ベクタ実行。**`--force` はありません。**
これは意図的な設計です。検証を迂回する仕組みを追加する Pull Request は受け付けません。

書き込みツールも同じです。projectCode の照合、コンテナ CRC、bank0 tag の検査は、
グラスを壊さないためにあります。

---

## 安全について

**このツールはファームウェアを書き換えます。壊れる可能性があります。**

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

- models not verified here (Air 2, Air 2 Pro, ...)
- operating systems not verified here (Linux, macOS)
- host setups not verified here (AMD, Intel integrated, Apple Silicon, HDMI
  converters, consoles)
- **any case where you measure something different** from the tables in
  `xreal/air/docs/verification.md`

A mismatch is useful information. Reports that something did not line up are
welcome.

Include:

- the model, and the SHA-256 of the image you flashed
- the tool output, pasted verbatim rather than summarised
- your host setup: OS, GPU, how it is connected

### Bug reports

Include how to reproduce it and what the tools actually printed.

### Support for other devices

Start from "移植するときに見る順番" (porting checklist) in
`docs/hid-protocol.md`. **A frame going through does not mean a given message id
is implemented**, and the container format differs per device too -- see
`docs/container-format.md`.

---

## Sending code

- **Do not include `*.bin`.** `.gitignore` blocks them; check anyway
- No device serial numbers, personal file paths or credentials
- Comments and messages in the tools are English. Documentation is
  Japanese-primary
- The builders run on the standard library alone. **Do not add dependencies**

### Do not weaken the verification

The builders prove their result before returning it: hash checks, per-record
before-image guards, an EDID decode, and execution of the 8051 helper over every
state vector. **There is no `--force`,** and that is deliberate. Pull requests
that add a way around the verification will not be accepted.

The same goes for the flashers. The project-code match, the container CRC and
the bank0 tag check exist to keep the glasses alive.

---

## Safety

**These tools rewrite firmware. They can break your glasses.**

Your only recovery path is the official firmware file you obtained. On some
models the device cannot be read back at all. See "Read this before anything
else" in the README.

Before telling someone else to flash something, check that they have a recovery
path.
