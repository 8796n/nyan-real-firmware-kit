# MOKIN UC6101B

MOKIN UC6101B搭載ドック向けのNintendo Switch 2互換Intel HEXビルダーです。
21.xで実機確認済みのNintendo VDM応答処理と状態リセット時パルスに加え、23.0の純正ドック
アップデートに追従して、コマンド`0x02`への応答値を`0003005F`から`0003006E`へ変更します。

2026-09-14、変更後の起動とSwitch 2の外部ディスプレイVRR設定の有効化を確認しました。
**VRRの実動作は未確認です。この変更はVRR実装の追加ではありません。** 応答値変更前に同じ
設定を有効化できたかは未確認で、設定の可否がこの変更によるものかも確定していません。

このディレクトリにファームウェアや書き込みツールは含まれません。`build.py`はイメージを生成・
検証するだけで、ハードウェアへアクセスしません。

## 対応入力

| 項目 | 値 |
|---|---|
| 公式ファイル | `XL_UC6101B_LT8712SX_Cto2DP+PD_V000612__20250724_CKS_0x1152B5C_WithPDtoC.HEX` |
| 入力SHA-256 | `BE3C7FD831B7D3C1C6D822D70C72EACF2DA21958E03C6448A9857DB6D762AA7D` |
| 出力SHA-256 | `AD718ED4B90948414EA24D3D1FAD77CE16493BF343B283B8FD76E212737FE108` |
| 出力image checksum | `0x11520CD` |
| 出力Block 1 CRC-8 | `0x35` |
| Nintendoコマンド`0x02`の応答値 | `0003006E` |

この1版だけに対応します。SHAが異なるイメージへ流用せず、別版は個別に解析してください。

## 生成

公式ファイルを`firmware/peripherals/mokin/uc6101b/`へ置いた例です。

```bash
python peripherals/mokin/uc6101b/build.py \
  --src firmware/peripherals/mokin/uc6101b/XL_UC6101B_LT8712SX_Cto2DP+PD_V000612__20250724_CKS_0x1152B5C_WithPDtoC.HEX \
  --out uc6101b-switch2.hex
```

書き出さず検査だけ行う場合:

```bash
python peripherals/mokin/uc6101b/build.py --src STOCK.HEX --check-only
```

既存の出力が決定論的な生成結果と一致するか確認する場合:

```bash
python peripherals/mokin/uc6101b/build.py --src STOCK.HEX --verify uc6101b-switch2.hex
```

ビルダーは入力SHA、Intel HEXの全レコードchecksum、変更前バイト、変更アドレス集合、Block 1
CRC-8、image checksum、出力SHAを検証します。検証を回避するオプションはありません。

## 書き込み前に

公式イメージを別の安全な場所へ保存してください。それが復旧手段です。書き込みは製品の公式手順に
従い、対象機種とメモリ設定を再確認してください。このリポジトリはベンダー製更新ツールを配布せず、
書き込み操作も自動化しません。

変更の根拠は[設計](docs/design.md)、確認済みの範囲は[実機検証](docs/verification.md)にあります。

---

## English

This dependency-free builder retains the Nintendo VDM fallback and reset pulse
verified on Switch 2 21.x, and follows the official dock update on system version
23.0 by changing the command-`0x02` reply from `0003005F` to `0003006E`.
Boot and enabling the external-display VRR setting were confirmed on 2026-09-14.
**Actual VRR operation remains unverified; this patch adds no VRR implementation.**
Whether the reply change affected the availability of that setting is also unconfirmed.

The builder accepts one exact official MOKIN UC6101B Intel HEX image.
It validates the stock SHA-256, every Intel HEX record, guarded before-bytes,
the complete changed-address set, the LT8712SX Block 1 CRC, the image checksum,
and the deterministic output SHA-256.

The script only builds an image; it never accesses hardware. Keep the official
image as your recovery path and follow the product's official flashing procedure.
No firmware or vendor update utility is provided here.
