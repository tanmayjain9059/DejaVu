# Private object storage operations

LostLink supports a local filesystem backend (default) and an S3-compatible backend.
Both store opaque object keys in the database. The application never returns bucket
URLs or presigned URLs to students; reads pass through authenticated API routes.

## Configure a private bucket

Create a bucket with:
- Public access blocked at the account and bucket levels.
- Server-side encryption enabled (the application also requests AES256 on writes).
- TLS-only access and a dedicated least-privilege application identity.
- Versioning or an independently approved replication/backup policy.
- Lifecycle/retention settings aligned with the institution-approved retention policy.

Set the following deployment environment values:

```dotenv
UPLOAD_STORAGE_BACKEND=s3
S3_BUCKET=lostlink-private
S3_PREFIX=lostlink-private
S3_REGION=ap-south-1
# Set S3_ENDPOINT_URL for MinIO or another compatible provider.
S3_ENDPOINT_URL=
S3_ACCESS_KEY_ID=<secret>
S3_SECRET_ACCESS_KEY=<secret>
```

Do not put credentials in source control. The application writes objects as private
objects and uses server-side encryption. Do not grant public-read permissions or
enable static website hosting for this bucket.

## Migrate existing local uploads

1. Back up PostgreSQL/SQLite and the complete local uploads directory.
2. Configure the destination bucket and credentials, but leave local uploads intact.
3. Run a dry run:

   ```bash
   UPLOAD_STORAGE_BACKEND=s3 S3_BUCKET=... python scripts/migrate_uploads_to_s3.py
   ```

4. Copy referenced report photos and claim evidence:

   ```bash
   UPLOAD_STORAGE_BACKEND=s3 S3_BUCKET=... python scripts/migrate_uploads_to_s3.py --apply
   ```

5. Verify the copied/missing counts, object count, checksums, private bucket policy,
   report image access, claim evidence access, image enrichment, and matching.
6. Only then deploy with `UPLOAD_STORAGE_BACKEND=s3`. Keep the local directory and
   original database backup until the coordinated restore drill passes.

The migration tool is dry-run by default, copies only database-referenced keys, does
not rewrite database keys, and never deletes local source files. It returns a nonzero
exit status if referenced local files are missing.

## Backups and recovery

The existing `backup_uploads.py` and Compose upload-volume backup utilities cover
the local filesystem backend only. They do not back up S3 objects. For S3, configure
provider versioning/replication or a separate encrypted backup process, record the
bucket/prefix and object count with each database backup, and rehearse restoring both
the database and its corresponding object version set into an isolated environment.

Do not switch a populated deployment back to local storage without restoring the
matching object set. Database records retain the same opaque key, but the selected
backend determines where that key is read.

## Runtime behaviour

- Report photos and claim evidence are private objects; all retrieval remains behind
  existing authentication, ownership, office-role, sensitive-category, watermark,
  and no-store checks.
- BLIP enrichment reads object bytes through the storage adapter.
- CLIP reads candidate photos through a storage callback and retains batched inference
  and persistent embedding caching; it does not materialize the full photo shortlist
  on local disk.
- S3 failures are not silently converted into public URLs. A failed object read
  should fail the authenticated image operation.
- The object-store provider, bucket policy, credentials, monitoring, retention and
  disaster recovery remain deployment responsibilities and must be verified in
  staging before real student data is used.
