# firmware/

入手した公式ファームウェアをここへ置いてください。このディレクトリはgitignoreされており、
中身はコミットされません。

| 機種 | ファイル | SHA-256 |
|---|---|---|
| Air (gen 1) | `1140` | `66A28C7BE1842D6837C68A5586CB0465099787F421427BE0CBE9691C858837DA` |
| Air (gen 1) | `07.1.02.387_20240428.bin` | `B1784C6D618D3CF6F03D77A93442C3267A425CB2BE415E8912539E165645A3E7` |
| Air 2 / Air 2 Pro | `air2/1140` | `350BACE369A83823D8EF867AE04AD07CF64D724C10EC7CEECFB83861AC9672F3` |
| Air 2 / Air 2 Pro | `air2/09.1.00.180_20240507.bin` | `C07633E97215346468A18F5306A10F800388A80CCD7DCFE800D468F4AB1BFD49` |
| MOKIN UC6101B | `peripherals/mokin/uc6101b/XL_UC6101B_LT8712SX_Cto2DP+PD_V000612__20250724_CKS_0x1152B5C_WithPDtoC.HEX` | `BE3C7FD831B7D3C1C6D822D70C72EACF2DA21958E03C6448A9857DB6D762AA7D` |

別の安全な場所にも保管してください。本ツールは本体からのバックアップ機能を提供しません。
Air（第1世代）は完全なファームウェア読み出しが不可能で、Air 2 / Air 2 Proは未確認です。
したがって、これらのファイルが復旧手段です。

Air 2とAir 2 Proは両ファイルを共有します。1つのp55ビルドが実行時に機種別の動作を選び、
両機種で書き込みと復旧を実機確認済みです。同じ公開出力を各機種の正確なPIDに対して受け付けます。
UC6101Bのビルダーはイメージ生成だけを行い、書き込み機能は含みません。

---

## English

Put the official firmware files you obtained at the paths in the table above.
This directory is gitignored; nothing in it is ever committed. Keep another
copy somewhere safe. This tooling provides no readback backup: full firmware
readback is confirmed impossible on Air (gen 1) and has not been established on
Air 2 / Air 2 Pro. These files are therefore your recovery path.

Air 2 and Air 2 Pro share both files: one p55 build serves both and selects its
behaviour at run time. Writing and recovery are hardware-verified on each. The
same published modified outputs are accepted for both exact model PIDs. The
UC6101B builder only generates an image and includes no flashing support.
