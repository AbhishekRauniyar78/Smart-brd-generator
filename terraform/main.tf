terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# Cloud Storage bucket for inputs/outputs
resource "google_storage_bucket" "artifacts" {
  name                        = var.gcs_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.force_destroy_bucket

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# BigQuery dataset
resource "google_bigquery_dataset" "brd_agent" {
  dataset_id = var.bq_dataset
  location   = var.region

  description = "BRD Generation Agent — context fragments and decision logs"

  depends_on = [google_project_service.apis]
}

# Context fragments table
resource "google_bigquery_table" "context_fragments" {
  dataset_id = google_bigquery_dataset.brd_agent.dataset_id
  table_id   = var.bq_context_table

  schema = jsonencode([
    { name = "fragment_id", type = "STRING", mode = "REQUIRED" },
    { name = "request_id", type = "STRING" },
    { name = "modality", type = "STRING" },
    { name = "extracted_text", type = "STRING" },
    { name = "gcs_uri", type = "STRING" },
    { name = "metadata", type = "JSON" },
    { name = "ingested_at", type = "TIMESTAMP" },
  ])
}

# Decision log table
resource "google_bigquery_table" "decision_log" {
  dataset_id = google_bigquery_dataset.brd_agent.dataset_id
  table_id   = var.bq_decisions_table

  schema = jsonencode([
    { name = "decision_id", type = "STRING", mode = "REQUIRED" },
    { name = "request_id", type = "STRING", mode = "REQUIRED" },
    { name = "project_name", type = "STRING" },
    { name = "section", type = "STRING" },
    { name = "reasoning", type = "STRING" },
    { name = "confidence", type = "FLOAT" },
    { name = "source_fragment_ids", type = "STRING", mode = "REPEATED" },
    { name = "supporting_evidence", type = "STRING", mode = "REPEATED" },
    { name = "model_used", type = "STRING" },
    { name = "created_at", type = "TIMESTAMP" },
  ])
}

# Service account for Cloud Run
resource "google_service_account" "brd_agent" {
  account_id   = "brd-generation-agent"
  display_name   = "BRD Generation Agent"
  depends_on     = [google_project_service.apis]
}

resource "google_project_iam_member" "vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.brd_agent.email}"
}

resource "google_project_iam_member" "storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.brd_agent.email}"
}

resource "google_project_iam_member" "bq_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.brd_agent.email}"
}

resource "google_storage_bucket_iam_member" "sa_bucket_access" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.brd_agent.email}"
}

# Cloud Run service (optional — deploy image separately)
resource "google_cloud_run_v2_service" "brd_agent" {
  count    = var.deploy_cloud_run ? 1 : 0
  name     = var.cloud_run_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.brd_agent.email

    containers {
      image = var.container_image

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "VERTEX_AI_LOCATION"
        value = var.region
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "OFFLINE_MODE"
        value = "false"
      }

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = var.cloud_run_max_instances
    }
  }

  depends_on = [
    google_project_service.apis,
    google_project_iam_member.vertex_user,
    google_project_iam_member.storage_admin,
    google_project_iam_member.bq_editor,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.deploy_cloud_run && var.cloud_run_allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.brd_agent[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
