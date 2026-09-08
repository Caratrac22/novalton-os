export const PUBLICATION_AUTHORITY_FIELDS = ["repository", "owner", "token", "base_branch", "prepared_remote_base_sha", "local_commit_sha", "local_tree_sha", "paths", "branch", "fingerprint", "policy_effect", "actor", "remote_commit_sha", "pr_number"] as const;

export function buildPublicationRequest(title: string, body: string): { title: string; body: string } {
  if (title.length < 1 || title.length > 160) throw new Error("title_out_of_bounds");
  if (body.length > 16_384) throw new Error("body_out_of_bounds");
  return { title, body };
}

export function publicationVisibleForCommit(status: string | null | undefined): boolean { return status === "APPLIED"; }
