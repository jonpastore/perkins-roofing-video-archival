# Cloud Run alerting — API 5xx + job execution failures.
# Reuses the existing google_monitoring_notification_channel.knowify_alert_email[0]
# (same var.alert_email recipient) rather than provisioning a second channel.
# Both policies are guarded with count = 0 when alert_email is empty, matching the
# knowify/integration-health alert policies in main.tf.

resource "google_monitoring_alert_policy" "api_5xx_errors" {
  count                 = var.alert_email != "" ? 1 : 0
  display_name          = "API — 5xx responses"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.knowify_alert_email[0].name]

  conditions {
    display_name = "api Cloud Run service returning 5xx"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" resource.label.\"service_name\"=\"api\" metric.label.\"response_code_class\"=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "cloud_run_job_failures" {
  count                 = var.alert_email != "" ? 1 : 0
  display_name          = "Cloud Run jobs — failed executions"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.knowify_alert_email[0].name]

  conditions {
    display_name = "any Cloud Run job execution failed"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/job/completed_execution_count\" resource.type=\"cloud_run_job\" metric.label.\"result\"=\"failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "600s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }
}
