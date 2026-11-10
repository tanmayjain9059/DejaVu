# LostLink — proposed retention and consent policy for college approval

**DRAFT ONLY · Not legally reviewed · Not approved by CVR College of Engineering · Not implemented in code.**

The periods below are **proposals**, not claims about college policy or applicable law. The college data owner, campus office, privacy/security lead and records owner must approve or replace every period and document any legal hold, dispute and backup exception before deletion is enabled. See `RETENTION_POLICY_TEMPLATE.md` for the approval checklist.

## Proposed retention schedule

| Data class | Starting event | Proposed maximum normal retention | Approval / exception |
|---|---|---|---|
| Open Lost and Found reports | Report creation | While active; review open cases every 180 days | Campus office must decide closure and exception handling |
| Closed reports and case attributes | Final closure / returned status | 180 days after closure | Retain longer only for documented dispute, custody or legal hold |
| Public claimant phone, contact details and supporting evidence | Claim finally resolved and appeal period ended | 90 days after final resolution | Privacy lead and office to confirm minimum dispute window |
| Privately stored report/evidence photographs | Case closure and any dispute resolved | 90 days after closure | Explicit legal holds and safety investigations override |
| Generated image captions and cached image vectors | Consent withdrawal | Clear promptly on withdrawal regardless of report retention | Verify existing consent withdrawal cleans derived data in live storage |
| Office custody / handover audit events | Final office event | 1 year | Records owner to approve a defensible audit period |
| Office login and session metadata | Session expiry / staff departure | Sessions expire per current auth config; propose 30 days for detached logs | IT / identity-provider deletion may need separate action |
| Read notifications | Read / event resolved | 90 days | Office and privacy owner |
| Rewards and certificates | Issuance | Propose 1 year after related case closure, with minimal non-identifying public display | Institution may prefer anonymisation to deletion |
| Rate-limit digests | Creation | 24 hours (current cleanup design) | Security owner to validate against abuse-monitoring needs |
| Database and object-storage backups | Backup creation | Proposed rolling 30-day expiry | Infrastructure owner must verify provider retention, replicas and restore tests |

**Unresolved questions:** Which office legally owns case records? What is the formal claim appeal/dispute period? What records must survive completed handover? Are any records needed for institutional audits, investigations, litigation or disciplinary action? What is Supabase/Render/Cloudflare backup retention? Who authorises irreversible deletion, and how are failed deletions retried?

## Proposed plain-language privacy and AI consent notice

**How LostLink uses information.** You can report lost or found property without creating a student account. We collect your college roll number for attribution and in-person office verification, report details, and optional contact information. We keep private evidence, custody notes, Tag IDs and claim records away from public listings. The campus office reviews ownership claims and verifies identity in person before handing over an item.

**AI-assisted matching.** LostLink can suggest possible matches from item attributes and text. These suggestions may be incomplete or incorrect and never prove ownership or automatically approve a claim. The office decides claims and records the physical handover.

**Optional photo AI processing.** If photo upload is enabled and you explicitly opt in, LostLink may process your report photo to generate matching features or captions that help suggest possible matches. You may submit a report without consenting to AI photo processing. The photo may still be held privately for authorised office verification. You may withdraw AI photo consent through your private case-tracking flow; the app is intended to clear generated captions and cached image vectors on withdrawal. Actual production processing and deletion behavior must be verified before enabling or advertising this feature.

**Access and correction.** Keep your private tracking receipt secure. You can use verified case access to request a data copy, correction or erasure review. Some records may need to be retained for unresolved custody, disputes or legal obligations. The office must explain and audit any decision to retain them. Deleting a live record does not instantly delete historical backups.

**Choice.** AI photo consent must be unchecked by default and is independent of the core reporting service. Withdrawing consent must not cause a penalty in claim evaluation or office service.

## Approval and implementation gate

- **CVR data owner:** approve each retention duration and public notice.
- **Office/records owner:** approve physical custody, dispute and handover exceptions.
- **Privacy/security lead:** approve access restrictions, withdrawal, erasure reviews and auditing.
- **Infrastructure owner:** approve backup/replica expiry and provider-side identity deletion.
- **Engineering:** only after written approvals, design a dry-run, idempotent, audited cleanup with rollback/recovery testing on synthetic data before enabling destructive behavior.

Until those approvals exist: **no automatic deletion, no period added to application configuration, no production purge.**
