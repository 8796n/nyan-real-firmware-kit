# Peripherals

メガネ以外のドック、変換器などを対象にしたファームウェアビルダーを置きます。
各機種は`peripherals/<vendor>/<model>/`に分け、少なくとも次を含めます。

- 既知の公式入力だけを受け付ける、標準ライブラリのみのビルダー
- 変更前バイト、出力SHA、機器固有checksumの検証
- 変更内容と実機確認範囲の記録

公式・改造済みファームウェアやベンダー製更新ツールは置きません。ビルダーと解析結果だけを
公開します。現在の対応機種は[MOKIN UC6101B](mokin/uc6101b/README.md)です。

---

Firmware builders for docks, adapters, and other non-glasses devices live
under `peripherals/<vendor>/<model>/`. Each supported device must pin its stock
input, guard every patch, verify the deterministic output, and document the
hardware-tested scope. Vendor firmware, patched images, and vendor update tools
are not distributed.
