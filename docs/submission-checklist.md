# 提出チェックリスト（〆切: 2026/7/10(金) 23:59）

## STEP 0: 事前確認

- [x] ハッカソン参加登録済み（Findy Conference申し込みフォーム）

## STEP 1: 開発・デプロイ

- [ ] ローカルでテストが全て通る（`pytest` / `ruff check .`）
- [ ] GitHubに**公開**リポジトリ `cloudmedic` を作成し push
- [ ] Cloud Shellで `infra/setup.sh` を実行（課金: `0129BB-69E434-CEFFD5`）
- [ ] GitHub Secrets 3点を登録（GCP_PROJECT_ID / GCP_SA_EMAIL / GCP_WIF_PROVIDER）
- [ ] GitHub Actions のデプロイが成功し、Cloud Run URLで動作確認
  - [ ] ダッシュボードが表示される
  - [ ] 障害注入 → エージェントが自動対応 → ポストモーテム生成まで一連動作
  - [ ] 承認モードでの承認フロー動作
  - [ ] Geminiエンジンで動作している（対応ログ冒頭の「エンジン: gemini」表示）
- [ ] README のバッジ・デモURLを実URLに更新

## STEP 2: ProtoPedia 登録

- [ ] ProtoPediaアカウント作成（https://protopedia.net/）
- [ ] `docs/protopedia.md` の内容で作品登録
- [ ] スクリーンショット3枚以上（ダッシュボード/対応中/ポストモーテム）
- [ ] デモ動画（`docs/demo-video-script.md` の台本で撮影→YouTubeにアップ）
- [ ] ステータス「完成」で公開

## STEP 3: 提出フォーム

- [ ] 作品提出フォーム（Google Form）から提出:
      https://docs.google.com/forms/d/e/1FAIpQLScYR-nIwo2Fglx1Srlui2dDt5rN_iIS6YYeLfMrRHvUpoMuFg/viewform
  - [ ] GitHubリポジトリURL（公開）
  - [ ] デプロイ済みプロジェクトURL（Cloud Run）
  - [ ] ProtoPedia作品URL
- [ ] 提出完了メール/画面を保存

## 提出後（任意・再提出可）

- [ ] X(Twitter)で `#findy_hackathon` を付けて紹介
- [ ] 改善したら再提出（最新タイムスタンプが審査対象）
