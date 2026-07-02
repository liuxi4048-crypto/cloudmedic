#!/usr/bin/env bash
# CloudMedic — GCPプロジェクトの初期セットアップスクリプト
#
# 使い方（Cloud Shell 推奨: https://shell.cloud.google.com ）:
#   export GITHUB_REPO="<GitHubユーザー名>/cloudmedic"   # 例: taro/cloudmedic
#   export BILLING_ACCOUNT="0129BB-69E434-CEFFD5"        # ハッカソンのクーポン課金アカウント
#   bash setup.sh
#
# 実行内容:
#   1. GCPプロジェクト作成・課金アカウント紐付け
#   2. 必要なAPIの有効化（Cloud Run / Cloud Build / Vertex AI ほか）
#   3. デプロイ用・ランタイム用サービスアカウント作成と権限付与
#   4. GitHub Actions 用 Workload Identity Federation（キーレス認証）の構成
#   5. GitHub Secrets に設定する値を出力

set -euo pipefail

: "${GITHUB_REPO:?GITHUB_REPO を 'owner/repo' 形式で指定してください}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-0129BB-69E434-CEFFD5}"
PROJECT_ID="${PROJECT_ID:-cloudmedic-$(date +%m%d)-$RANDOM}"
REGION="${REGION:-asia-northeast1}"

echo "== 1/5 プロジェクト作成: $PROJECT_ID"
gcloud projects create "$PROJECT_ID" --name="CloudMedic Hackathon"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
gcloud config set project "$PROJECT_ID"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

echo "== 2/5 API有効化"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  iamcredentials.googleapis.com \
  iam.googleapis.com \
  logging.googleapis.com

echo "== 3/5 サービスアカウント作成"
gcloud iam service-accounts create cloudmedic-deployer \
  --display-name="CloudMedic CI/CD deployer"
gcloud iam service-accounts create cloudmedic-runtime \
  --display-name="CloudMedic Cloud Run runtime"

DEPLOYER="cloudmedic-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME="cloudmedic-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

# デプロイSA: Cloud Run + Cloud Build(--source デプロイ) に必要な権限
for role in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.admin roles/storage.admin \
            roles/iam.serviceAccountUser roles/serviceusage.serviceUsageConsumer \
            roles/logging.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$DEPLOYER" --role="$role" --condition=None -q > /dev/null
done

# ランタイムSA: Vertex AI (Gemini) 呼び出しとログ書き込み
for role in roles/aiplatform.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$RUNTIME" --role="$role" --condition=None -q > /dev/null
done

echo "== 4/5 Workload Identity Federation 構成 (GitHub: $GITHUB_REPO)"
gcloud iam workload-identity-pools create github-pool \
  --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github-pool \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${GITHUB_REPO}"

WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"

echo
echo "== 5/5 セットアップ完了 🎉"
echo
echo "GitHubリポジトリ (https://github.com/${GITHUB_REPO}/settings/secrets/actions) に"
echo "以下の Actions Secrets を登録してください:"
echo
echo "  GCP_PROJECT_ID   = ${PROJECT_ID}"
echo "  GCP_SA_EMAIL     = ${DEPLOYER}"
echo "  GCP_WIF_PROVIDER = ${WIF_PROVIDER}"
echo
echo "登録後、main ブランチへ push すると GitHub Actions が Cloud Run へ自動デプロイします。"
