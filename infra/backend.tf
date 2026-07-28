# Remote state. Until 2026-07-28 terraform state was a LOCAL file on one laptop — 146 resources,
# not in git and not backed up anywhere. That quietly undercut R3 ("100% IaC, git is the source of
# truth"): the config was in git, but the state that maps it onto real resources was not. Lose the
# laptop and terraform no longer knows any of this infra exists — the next plan would try to
# CREATE all 146 resources on top of the live ones.
#
# It also made a CI drift gate impossible: GitHub Actions started from an empty state and planned
# to create everything, which is exactly what the first deploy run reported.
#
# The bucket is versioned, so a corrupted or truncated state can be rolled back to any prior
# object generation. Public access is prevented and uniform bucket-level access is on.
terraform {
  backend "gcs" {
    bucket = "video-archival-and-content-gen-tfstate"
    prefix = "perkins-platform"
  }
}
