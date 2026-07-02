# インフラセットアップ手順

## 前提

- Google Cloud アカウント（ハッカソンのクーポン課金アカウントが使えること）
- GitHub アカウント（このリポジトリを公開リポジトリとして所有していること）

## 手順

### 1. GCPセットアップ（Cloud Shellで約3分）

[Cloud Shell](https://shell.cloud.google.com) を開き、以下を実行します。

```bash
git clone https://github.com/<あなたのユーザー名>/cloudmedic.git
cd cloudmedic/infra
export GITHUB_REPO="<あなたのユーザー名>/cloudmedic"
export BILLING_ACCOUNT="0129BB-69E434-CEFFD5"
bash setup.sh
```

スクリプトが最後に出力する3つの値を控えます。

### 2. GitHub Secrets の登録

リポジトリの Settings → Secrets and variables → Actions で以下を登録:

| Secret名 | 値 |
|---|---|
| `GCP_PROJECT_ID` | setup.sh の出力 |
| `GCP_SA_EMAIL` | setup.sh の出力 |
| `GCP_WIF_PROVIDER` | setup.sh の出力 |

### 3. デプロイ

main ブランチへ push（または Actions タブから `Deploy to Cloud Run` を手動実行）すると、
テスト → Cloud Run デプロイ → スモークテストまで自動で実行されます。

デプロイ後のURLは Actions のログ、または以下で確認できます:

```bash
gcloud run services describe cloudmedic --region asia-northeast1 --format 'value(status.url)'
```

## 認証方式について

GitHub Actions からの認証は **Workload Identity Federation（キーレス）** を使用しており、
サービスアカウントキー（JSON）を一切発行しません。リポジトリを限定する
`attribute-condition` 付きで構成しているため、他リポジトリからの成りすましも防げます。

## コスト

- Cloud Run: min-instances=1 / 512Mi で月額 約$10 前後（クーポン内で十分収まる想定）
- Vertex AI (gemini-2.5-flash): デモ利用の範囲では数ドル程度
