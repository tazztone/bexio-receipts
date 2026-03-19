# Operations Guide (Runbook)

## Daily Operations

### Monitoring the Pipeline
The pipeline runs as a background process or Docker container. Status can be monitored via:
- **CLI**: Check logs for `booked` or `review` statuses.
- **Dashboard**: Visit `/stats` to see processing volume.

### Processing the Review Queue
Receipts with low OCR confidence or validation errors stop in the **Review Dashboard**.
1. Log in with your `REVIEW_PASSWORD`.
2. Review the extracted fields against the receipt image.
3. Click **"Apply & Push"** to send to bexio.

## Maintenance Task

### API Token Rotation
1. Generate a new PAT in bexio.
2. Update `BEXIO_API_TOKEN` in your `.env`.
3. Restart the service.

### Database Maintenance
The SQLite database (`processed_receipts.db`) grows slowly. No active maintenance is required, but a weekly backup is recommended.

## Disaster Recovery

### "My Pipeline is Stuck"
If the folder watcher stops picking up files:
1. Check for `Permission Denied` errors on the `inbox/` directory.
2. Restart the process: `docker compose restart`.
3. Check the `logs` for any `DuplicateDetector` lock errors (usually self-resolving after restart).

### Moving to a New Server
1. Copy the `.env` and `processed_receipts.db`.
2. Ensure Ollama is installed and models are pulled.
3. Run `docker compose up -d`.
   - **Important**: Keeping the database file ensures you don't double-book old receipts!
