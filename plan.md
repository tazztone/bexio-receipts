# 🔴 Critical Gaps

1. **`extraction.py` has no retry/timeout handling**
   - Import `retry` from `tenacity` and wrap `agent.run` with retry handling similar to `bexio_client.py` (e.g. `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(Exception))`).
   - Pass an explicit timeout to `httpx.AsyncClient` when initializing the Provider for Pydantic AI.

2. **`server.py` has no authentication**
   - Implement HTTP Basic Authentication in `server.py` using `fastapi.security.HTTPBasic`. Protect all endpoints (`/`, `/stats`, `/review/{review_id}`, `/image/{review_id}`, `/push/{review_id}`, `/discard/{review_id}`). Add a simple username/password validation logic based on a `review_password` setting (default to something or loaded from `.env`).

3. **`server.py` `/push` hardcodes `mime_type="image/png"`**
   - Import `mimetypes`. Inside `push_to_bexio`, use `mimetypes.guess_type(img_path)` to determine the mime type. Fallback to `"application/octet-stream"` if it cannot be determined.

# 🟠 Significant Gaps

4. **`database.py` has no `get_stats` financial data**
   - Add new columns to `processed_receipts`: `total_incl_vat REAL`, `merchant_name TEXT`, `vat_amount REAL`. Add an `ALTER TABLE` to `_init_db` to safely add these if they don't exist.
   - Update `mark_processed` to save these details.
   - Update `get_stats()` to compute and return sums: `total_booked_amount`, `total_reclaimed_vat`, and group by `merchant_name` to return a list of top merchants.
   - Update `stats.html` template to display the new financial data.

5. **`models.py` has no `supplier_name` normalization**
   - Add a Pydantic `model_validator` or `@field_validator('merchant_name')` in `models.py` that strips whitespace, converts the name to a consistent case (e.g., Title Case), and removes common suffixes like "AG", "GMBH", "Ltd.", etc., so that "Migros", "MIGROS", and "Migros AG" all become "Migros".

6. **`bexio_client.py` — `_owner_id` is incorrectly set**
   - Update `bexio_client.py`. Add a setting `bexio_owner_id: int = 1` in `Settings`. Use `settings.bexio_owner_id` (or default to 1) instead of setting `_owner_id = profile.get("id")`. In bexio, an `owner_id=1` is typically the main admin user, and using the API token's user id often creates contacts under a restricted user in multi-user accounts. Wait, we can fetch the `owner_id` from the company profile: Bexio has an endpoint `/2.0/company_profile`, which returns `owner_id` representing the tenant's primary owner. I will fetch the `owner_id` correctly from the company profile instead of the current user's profile.

# 🟡 Minor / Quality Gaps

7. **Tests don't cover the pipeline or server**
   - Create `tests/test_pipeline.py` and `tests/test_server.py`. Write integration tests that mock the external dependencies (bexio client, LLM extraction) and test the full flow and server endpoints.

8. **`validation.py` date check will crash on `None` date**
   - Add a `None` guard in `validation.py` before doing `r.date > date.today()`. Although Pydantic validation should ensure it's a date, if it somehow gets passed as `None` or an exception occurs, it's safer to guard it.

9. **`database.py` — no connection pooling**
   - Update `database.py` to enable WAL mode: `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;` inside `_init_db`.
   - Update to use a single persistent connection with `check_same_thread=False` and a `threading.Lock` to synchronize writes, or use `aiosqlite` for async connection pooling, or keep short-lived connections but with an increased `timeout=10.0` parameter in `sqlite3.connect`. Using `timeout=10.0` and `PRAGMA journal_mode=WAL` will resolve contention.

10. **No `CHANGELOG` or version tagging**
    - Create a `CHANGELOG.md` file describing the changes, bugfixes, and new features introduced in this release.

11. **Pre-commit step**
    - Complete pre commit steps to ensure proper testing, verification, review, and reflection are done before submission.
