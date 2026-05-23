variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "gcs_bucket_name" {
  description = "Cloud Storage bucket for BRD artifacts"
  type        = string
  default     = "brd-agent-artifacts"
}

variable "bq_dataset" {
  type    = string
  default = "brd_agent"
}

variable "bq_context_table" {
  type    = string
  default = "context_fragments"
}

variable "bq_decisions_table" {
  type    = string
  default = "decision_log"
}

variable "gemini_model" {
  type    = string
  default = "gemini-2.0-flash-001"
}

variable "force_destroy_bucket" {
  description = "Allow Terraform to destroy bucket with objects"
  type        = bool
  default     = false
}

variable "deploy_cloud_run" {
  description = "Deploy Cloud Run service (requires pre-built container image)"
  type        = bool
  default     = false
}

variable "container_image" {
  description = "Container image for Cloud Run"
  type        = string
  default     = "gcr.io/cloudrun/hello"
}

variable "cloud_run_service_name" {
  type    = string
  default = "brd-generation-agent"
}

variable "cloud_run_max_instances" {
  type    = number
  default = 10
}

variable "cloud_run_allow_unauthenticated" {
  type    = bool
  default = false
}
