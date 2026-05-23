output "gcs_bucket_name" {
  value       = google_storage_bucket.artifacts.name
  description = "Cloud Storage bucket for BRD artifacts"
}

output "gcs_bucket_url" {
  value = google_storage_bucket.artifacts.url
}

output "bigquery_dataset_id" {
  value = google_bigquery_dataset.brd_agent.dataset_id
}

output "context_table_id" {
  value = "${var.project_id}.${var.bq_dataset}.${var.bq_context_table}"
}

output "decisions_table_id" {
  value = "${var.project_id}.${var.bq_dataset}.${var.bq_decisions_table}"
}

output "service_account_email" {
  value = google_service_account.brd_agent.email
}

output "cloud_run_url" {
  value       = var.deploy_cloud_run ? google_cloud_run_v2_service.brd_agent[0].uri : null
  description = "Cloud Run service URL (if deployed)"
}
