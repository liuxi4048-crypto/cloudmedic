# DevOps × AI Agent Hackathon 提出プラン

## ゴール

〆切 **2026/7/10(金) 23:59** までに以下3点を提出フォーム（Google Form）から提出する。

1. 公開GitHubリポジトリのURL
2. デプロイ済みプロジェクトのURL（動作確認できる状態）
3. ProtoPediaに登録した作品のURL

## プロダクト: CloudMedic 🩺

**「Cloud Run上のサービスを自律的に診察・応急処置し、ポストモーテムまで書くSREエージェント」**

- 障害発生を検知すると、AIエージェント（Gemini）が自律的に「バイタル確認 → ログ調査 → デプロイ履歴確認 → 原因推定 → 処置（ロールバック/再起動/スケールアウト）→ 回復確認 → ポストモーテム作成」を実行する。
- 人間の承認を挟む「承認モード」と全自動の「自動対応モード」を切替可能（実運用を見据えたHuman-in-the-loop設計）。
- デモ用に障害注入ボタン（エラーストーム/レイテンシ悪化/メモリリーク/不良デプロイ）を備えた「患者サービス」を同梱し、審査員がその場で体験できる。

### 審査基準への対応

| 審査基準 | CloudMedicの対応 |
|---|---|
| AIエージェントが価値の中心か | Gemini function callingによる多段自律判断がプロダクトの本体。人間はモード選択と承認のみ |
| 課題へのアプローチ力 | 「深夜のオンコール対応」という実務の痛みに直結。検知→診断→処置→再発防止の一貫ストーリー |
| ユーザビリティ | ワンクリック障害注入→リアルタイムで思考が流れる日本語ダッシュボード（SSE） |
| 実用性・体験価値 | ポストモーテム自動生成・GitHub Issue起票。承認モードで実運用に導入可能な設計 |
| 実装力 | Cloud Run + Gemini + GitHub Actions(WIF)のキーレスCI/CD。テスト・Lint完備 |

### 必須技術要件の充足

- GCP実行基盤: **Cloud Run**（デプロイ先）
- GCP AI: **Gemini API（google-genai SDK、Vertex AI経由でも動作）**

## アーキテクチャ

```
GitHub (main push)
   └─ GitHub Actions  … CI (ruff+pytest) → Workload Identity Federationでキーレス認証
        └─ gcloud run deploy --source .  (Cloud Build)
             └─ Cloud Run サービス "cloudmedic"
                  ├─ 患者サービス (デモAPI + 障害注入)
                  ├─ ウォッチドッグ (異常検知)
                  ├─ Medicエージェント (Gemini function calling ループ)
                  │     tools: get_vital_signs / search_logs / list_deployments /
                  │            apply_treatment / verify_recovery / write_postmortem /
                  │            create_github_issue
                  └─ ダッシュボード (SSEで思考をライブ配信)
```

## スケジュール（残り8日）

| 日付 | 作業 |
|---|---|
| 7/2 | プラン確定・実装一式・提出資料ドラフト（本セッション） |
| 7/3 | ローカルテスト、GitHubリポジトリ作成・push、GCPプロジェクト作成（Cloud Shell）、初回デプロイ |
| 7/4-5 | 動作確認・磨き込み（ダッシュボードUX、プロンプト調整） |
| 7/6 | デモ動画撮影（3分）・ProtoPedia登録 |
| 7/7 | 提出フォーム送信（〆切3日前バッファ） |
| 7/8-10 | 予備日（再提出可なので改善したら再提出） |

## 残作業のうちユーザーの操作/承認が必要なもの

1. ツールインストール承認（winget: Python 3.12 — テスト実行用）
2. GitHubリポジトリ（公開）の作成とpush時の認証
3. Cloud Shellでの `infra/setup.sh` 実行（GCPプロジェクト作成・課金アカウント `0129BB-69E434-CEFFD5` 紐付け・WIF設定）
4. GitHub SecretsへのWIF設定値の登録
5. ProtoPedia登録（要アカウント）・デモ動画撮影・提出フォーム送信
