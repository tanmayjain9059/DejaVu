# LostLink data-retention policy template

**Status: incomplete — do not treat this template as an approved policy.** The campus data owner, privacy/security lead, and records owner must agree on retention periods and legal holds before automated deletion is enabled. Do not invent retention periods in application code.

## Decisions required before launch

| Data class | Purpose | Retention period | Deletion trigger | Owner / approval |
|---|---|---|---|---|
| Student accounts and sign-in metadata | Access control and abuse prevention | **Set by institution** | Account deactivation / approved request | Campus IT |
| Lost/found reports | Resolve property claims | **Set by institution** | Report closure plus approved retention window | Lost & Found office |
| Claim evidence text and images | Verify ownership and resolve disputes | **Set by institution** | Claim finalization plus dispute/appeal window | Privacy lead + office |
| Report images | Identify and match items | **Set by institution** | Report closure plus approved retention window | Lost & Found office |
| Audit events | Accountability and incident investigation | **Set by institution** | Approved audit retention expiry | Security/records owner |
| Notifications | Inform users of workflow changes | **Set by institution** | Read/expiry and approved retention rules | Product owner |
| Rewards and certificates | Contribution history | **Set by institution** | Account closure and records policy | Product owner |
| Backups | Recovery from loss/corruption | **Set by institution** | Backup expiry, including replicas | Infrastructure owner |

## Minimum operating requirements

- Record the lawful purpose, retention period, data owner, deletion trigger, and any legal-hold exception for each class.
- Define how account deletion interacts with open claims, audit integrity, certificates, and legal holds.
- Delete database rows and referenced private image files together, using an idempotent process with a dry-run report and an auditable deletion summary.
- Define backup expiration separately; deletion from the live database does not instantly remove data from retained backups.
- Restrict and audit access to private evidence and backup decryption keys.
- Test deletion and recovery on synthetic data first; verify referential integrity and absence of orphaned files.
- Document the process for data-subject requests, disputes, incident preservation, and failed deletions.

## Implementation gate

Automated deletion must remain disabled until all retention periods and exceptions above are approved. After approval, implement a scheduled dry-run report first, review the output with the data owner, then enable destructive execution with least-privilege credentials, alerting, and tested recovery.
