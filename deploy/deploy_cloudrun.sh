#!/usr/bin/env bash
# One-command Cloud Run deploy for the SAMAY demo. NEVER auto-run.
# Requires an explicit confirmation. Owner runs this AFTER a security review.
#
# Bill safety: --max-instances caps autoscaling (a DoS cannot scale the bill to
# the moon); --min-instances 0 scales to zero (free when idle). The app itself
# caps instance size, solver time, concurrency, and rate per IP.
set -euo pipefail

PROJECT="${PROJECT:-dmjone}"
REGION="${REGION:-asia-east1}"
SERVICE="${SERVICE:-samay}"
CORS="${CORS:-https://pqcsched.dmj.one,https://dmj.one}"

if [ "${1:-}" != "--yes" ]; then
  echo "This will deploy '$SERVICE' to Cloud Run (project=$PROJECT region=$REGION)."
  echo "It is a billable cloud action. Re-run with --yes to proceed:"
  echo "    bash deploy/deploy_cloudrun.sh --yes"
  exit 1
fi

cd "$(dirname "$0")/.."
gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi --cpu 2 \
  --concurrency 8 \
  --max-instances 3 \
  --min-instances 0 \
  --timeout 30 \
  --set-env-vars "^@^PQCSCHED_CORS_ORIGINS=${CORS}"
  # ^@^ = gcloud custom delimiter so the comma in the multi-origin CORS value is
  # literal (default comma would be parsed as separate env-var entries).

echo
echo "Deployed. Next (manual — Claude cannot edit Cloudflare DNS):"
echo "  Map the custom domain:  gcloud beta run domain-mappings create --service $SERVICE --domain pqcsched.dmj.one --region $REGION"
echo "  then add the Cloudflare CNAME it prints (pqcsched -> ghs.googlehosted.com), DNS-only first for cert issuance."
