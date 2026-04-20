# Operations Guide (Runbook)

This guide covers initial production setup and ongoing maintenance tasks for
bexio-receipts.

## 🚀 Initial Production Setup

Follow these steps when switching from the local Mock Bexio environment to your
real Bexio account.

### 1. Environment Variables
Update your `.env` file with real credentials:

```bash
# Real Bexio API settings
BEXIO_API_TOKEN=your_actual_bexio_api_token
BEXIO_BASE_URL=https://api.bexio.com

# Production Security
REVIEW_USERNAME=your_secure_username
REVIEW_PASSWORD=your_secure_password
SECRET_KEY=generate_a_long_random_string_for_sessions
```

### 2. Default Account IDs
Set your real bexio account IDs for booking and bank payments in your `.env`:

```bash
DEFAULT_BOOKING_ACCOUNT_ID=4000  # e.g., Materialaufwand
DEFAULT_BANK_ACCOUNT_ID=1020     # e.g., Bank
```

### 3. Verify Connection
1. Restart your containers: `make up` (or `docker compose restart`)
2. Visit `http://localhost:8000/setup` to verify the connection.
3. The Setup Wizard will show the name of your real Bexio company profile upon
   successful connection.

### ⚠️ Security Checklist
- [ ] `SECRET_KEY` is randomized and not the default.
- [ ] `REVIEW_PASSWORD` is strong.
- [ ] Dashboard is restricted behind a VPN or reverse proxy if exposed to the
  internet.
- [ ] `BEXIO_API_TOKEN` is kept secret and not committed to git.

---

## Daily Operations

### Monitoring the Pipeline
The pipeline status can be monitored via:
- **CLI**: Check logs for `booked` or `review` statuses.
- **Dashboard**: Visit `/stats` to see processing volume.
- **Metrics**: Prometheus metrics are available at `/metrics`.

### Processing the Review Queue
All receipts processed by the automated pipeline stop in the **Review
Dashboard** for final verification. This ensures 100% accuracy for your
financial data.

1. Log in with your `REVIEW_PASSWORD`.
2. Review the extracted fields against the receipt image.
3. **Check Booking Accounts**: The system automatically suggests accounts
   per VAT rate based on the last saved mapping or AI classification (Step 3).
   AI suggestions include a **Reasoning** hint and a **Confidence** level.
4. Correct any minor extraction artifacts (e.g., date format, VAT rate).
5. Click **"Apply & Push"** to send the verified entry to bexio. This also
   persists any account corrections to the learning loop for future automation.

## Maintenance Tasks

### API Token Rotation
1. Generate a new PAT in bexio.
2. Update `BEXIO_API_TOKEN` in your `.env`.
3. Restart the service: `docker compose restart`.

### Database Maintenance
The SQLite database (`processed_receipts.db`) grows slowly. No active
maintenance is required, but a weekly backup is recommended.

To perform a safe backup (even while the app is running):
```bash
sqlite3 processed_receipts.db ".backup backup_$(date +%Y%m%d).db"
```

## Disaster Recovery

### "My Pipeline is Stuck"
If the folder watcher stops picking up files:
1. Check for `Permission Denied` errors on the `inbox/` directory.
2. Restart the process: `docker compose restart`.
3. Check the `logs` for any `DuplicateDetector` lock errors.

### Moving to a New Server
1. Copy the `.env` and `processed_receipts.db`.
2. Ensure vLLM/SGLang is running and extraction models are pulled.
3. Run `docker compose up -d`.
   - **Important**: Keeping the database file ensures you don't double-book old
     receipts!
