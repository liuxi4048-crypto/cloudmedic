# ProtoPedia 登録用ドラフト

登録先: https://protopedia.net/ （要アカウント）
参考: https://protopedia.gitbook.io/helpcenter/registration

---

## 作品タイトル

**CloudMedic 🩺 — 障害対応を自律実行するSREエージェント**

## 概要（サマリー欄）

深夜のオンコール対応をAIに任せられたら——CloudMedicは、Cloud Run上のサービスを
医師のように「診察」する自律SREエージェントです。エラー率やレイテンシの異常を検知すると、
Geminiがログ調査・デプロイ履歴確認を自ら計画・実行して原因を特定し、ロールバックや
スケールアウトなどの処置を選択。回復を確認したら、ポストモーテムの作成と再発防止タスクの
GitHub Issue起票まで完了させます。処置前に人間の承認を挟む「承認モード」も備え、
実運用への段階導入を見据えた設計です。

## ストーリー（本文）

### 背景 — オンコールという「痛み」

サービス障害の対応は、いまだに人間の集中力と睡眠時間に依存しています。
アラートで起こされ、ダッシュボードとログを行き来し、「直近のデプロイが怪しい」と
当たりをつけてロールバックし、朝にはポストモーテムを書く。
この一連の流れは高度な判断に見えて、実は「観察 → 仮説 → 検証 → 処置」という
再現可能なプロセスです。ならば、AIエージェントに任せられるはず。

### CloudMedic の動き

1. **検知**: ウォッチドッグがバイタル（エラー率・p95レイテンシ・メモリ）を常時監視
2. **診察**: Gemini が function calling で診察ツールを自ら選択・実行
   - バイタル確認 → ログ検索（例外名や外部API名などのシグネチャ特定）→ デプロイ履歴確認
3. **処置**: 鑑別診断の結果に応じて4種類の処置から選択
   - デプロイ起因 → ロールバック / メモリリーク → 再起動
   - プール枯渇 → スケールアウト / 外部API障害 → サーキットブレーカー
4. **回復確認**: 処置後のトラフィックを観測。回復しなければ別の処置を再検討（最大3回）
5. **カルテ**: ポストモーテムを自動生成し、再発防止タスクをGitHub Issueに起票

### こだわり

- **Human-in-the-loop**: 処置前に人間の承認を求める「承認モード」を実装。
  いきなり全自動を信頼できない現場でも、承認モードから段階的に導入できます。
- **体験できるデモ**: ダッシュボードから4種類の障害をワンクリック注入でき、
  エージェントの思考がSSEでリアルタイムに流れる様子を誰でも体験できます。
- **DevOpsを「まわす」**: GitHub Actions + Workload Identity Federation（キーレス）で
  push→テスト→Cloud Runデプロイ→スモークテストまで全自動。
- **落ちないエージェント**: Gemini APIが使えない状況では同一ツールで動く決定的
  フォールバックエンジンに自動切替（SREツール自身が単一障害点にならないように）。

### システム構成

GitHub Actions（CI/CD・WIF認証）→ Cloud Build → **Cloud Run**
Cloud Run内: 患者サービス（デモEC）/ ウォッチドッグ / Medicエージェント（**Gemini 2.5 Flash** via Vertex AI）/ SSEダッシュボード

## 開発素材

- システム: Google Cloud Run / Vertex AI (Gemini API) / Cloud Build / Cloud Logging
- 言語・FW: Python 3.12 / FastAPI / google-genai SDK
- CI/CD: GitHub Actions（Workload Identity Federation）
- フロント: HTML/CSS/JavaScript（Server-Sent Events）

## タグ案

`AIエージェント` `Gemini` `CloudRun` `SRE` `DevOps` `障害対応` `FastAPI` `findy_hackathon`

## 登録時チェックリスト

- [ ] メイン画像: ダッシュボードのスクリーンショット（障害対応中の画面）
- [ ] 追加画像: アーキテクチャ図、ポストモーテム画面、承認モード画面
- [ ] デモ動画URL（YouTube限定公開でも可）
- [ ] GitHubリポジトリURLを「関連リンク」に記載
- [ ] デプロイURLを記載
- [ ] ステータスを「完成」に設定
