# UC6101B Switch 2互換パッチの設計

## 概要

対象はMOKIN UC6101Bの2025-07-24版Intel HEXです。Switch 2システムバージョン21.xとの
互換性がある同系統のLT8712SXファームウェアと比較し、次の2処理を移植しています。

1. 未認識Nintendo VDMへ送信種別`0x20`の空応答を返す。
2. Nintendoプロトコル状態のリセット後、`XDATA 0xA110` bit 1をclear→delay→setする。

1だけの候補は実機でTVモードへ入らず、2も含む現在の出力でTVモード移行を確認したため、
公開ビルダーは成功した組み合わせだけを生成します。

## VDMフォールバック

UC6101BのNintendo VDMハンドラは、既知でないcommandを受けると`0xD559`の`RET`へ分岐して
無応答になります。一方、同じイメージ内の`0xD4A6`には送信種別`0x20`の応答を構築して共通送信
処理へ進むブロックがあります。

`0xD51E`の`JNZ rel8`について、次PC `0xD520`から`0xD4A6`への変位は`-122`、8 bit表現で
`0x86`です。このため機能変更は次の1 byteです。

```text
0x00D51F: 39 -> 86
```

## 状態リセット時パルス

既存リセットルーチン末尾のcallを、未使用領域`0xF89D`へ追加する20 byte stubに向けます。
stubは元のリセット処理を完了後、既存のbit操作関数とdelay関数を使って`XDATA 0xA110` bit 1を
clear→delay→setし、呼び出し元へ戻ります。

```text
0x00F27C..0x00F27E: 02 61 19 -> 02 F8 9D
0x00F89D..0x00F8B0: 20 byte stubを追加
```

## Intel HEXとBlock 1 CRC

各Intel HEXレコードのchecksumとは別に、LT8712SXは`0x0000..0xFFFE`を対象とするCRC-8を
`0xFFFF`に保持します。未実装アドレスは`0xFF`として計算します。

- polynomial: `0x31`
- init: `0x00`
- bit order: MSB-first
- xorout: `0x00`
- 生成後の格納値: `0x51`

ビルダーは入力全体のSHA-256と変更前バイトを照合してからパッチし、変更アドレスが宣言した24
byteだけであること、CRC、image checksum、最終ファイルSHAが固定値と一致することを検査します。
