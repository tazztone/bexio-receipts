# Production Deployment Guide (Real Bexio API)

This guide explains how to switch from the local Mock Bexio environment to your real Bexio account.

## 1. Environment Variables
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

## 2. Docker Configuration
In `docker-compose.yml`, ensure the `BEXIO_BASE_URL` is passed through and matches the production endpoint. You can also disable the `mock-bexio` and `mock-imap` services if they are no longer needed.

## 3. Account IDs
Find your real bexio account IDs for:
- **Booking Account**: e.g., `4000` (Materialaufwand)
- **Bank Account**: e.g., `1020` (Bank)

Set these in your `.env`:
```bash
DEFAULT_BOOKING_ACCOUNT_ID=4000
DEFAULT_BANK_ACCOUNT_ID=1020
```

## 4. Initial Setup
1. Restart your containers: `make up`
2. Visit `/setup` to verify the connection.
3. The Setup Wizard will show the name of your real Bexio company profile upon successful connection.

## ⚠️ Security Checklist
- [ ] `SECRET_KEY` is randomized and not the default.
- [ ] `REVIEW_PASSWORD` is strong.
- [ ] Dashboard is restricted behind a VPN or reverse proxy if exposed to the internet.
- [ ] `BEXIO_API_TOKEN` is kept secret and not committed to git.
