# Bexio API reference

This document provides a reference for the Bexio API endpoints and data
structures used in the `Gemini CLI` project. It includes excerpts from the
official Bexio documentation relevant to receipt processing, expense
management, and contact synchronization.

For full details, refer to the [official Bexio API documentation](https://docs.bexio.com/).

## Authentication

The project uses Personal Access Tokens (PAT) for authentication. You must
include the token in the `Authorization` header of every request.

<!-- prettier-ignore -->
> [!IMPORTANT]
> Ensure your PAT has the necessary scopes for the resources you are accessing,
> such as `contact_show`, `contact_edit`, `kb_purchase_bill_show`,
> `kb_purchase_bill_edit`, and `file_show`.

### Headers
```http
Authorization: Bearer {your_access_token}
Accept: application/json
```

## File management

Receipts are uploaded to Bexio as files before being attached to expenses or
purchase bills.

### POST /3.0/files
Uploads a binary file to the Bexio storage.

- **Endpoint:** `https://api.bexio.com/3.0/files`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`

**Request Body:**
- `file`: The binary content of the file.

**Success Response (200):**
```json
{
  "id": 1,
  "uuid": "474cc93a-2d6f-47e9-bd3f-a5b5a1941314"
}
```

## Contact management

The system searches for or creates contacts to represent merchants/suppliers.

### POST /2.0/contact/search
Searches for contacts based on specific criteria.

- **Endpoint:** `https://api.bexio.com/2.0/contact/search`
- **Method:** `POST`

**Request Example:**
```json
[
  {
    "field": "name_1",
    "value": "Merchant Name",
    "criteria": "="
  }
]
```

### POST /2.0/contact
Creates a new contact if one is not found during search.

- **Endpoint:** `https://api.bexio.com/2.0/contact`
- **Method:** `POST`

**Required Fields:**
- `contact_type_id`: `1` for company, `2` for person.
- `name_1`: Company name or last name.
- `user_id`: ID of the assigned user.
- `owner_id`: ID of the owner.

## Expense management (v4)

Simple expenses are used for receipts with a single VAT rate.

### POST /4.0/expenses
Creates a new expense record.

- **Endpoint:** `https://api.bexio.com/4.0/expenses`
- **Method:** `POST`

**Key Fields:**
- `paid_on`: Date the expense was paid (YYYY-MM-DD).
- `amount`: Total amount.
- `currency_code`: e.g., "CHF", "EUR".
- `tax_id`: ID of the tax rate.
- `attachment_ids`: Array of file UUIDs.
- `booking_account_id`: ID of the booking account.
- `bank_account_id`: ID of the bank account.

## Purchase bills (v4)

Purchase bills are used for complex receipts with multiple line items or VAT
rates.

### POST /4.0/purchase/bills
Creates a new purchase bill.

- **Endpoint:** `https://api.bexio.com/4.0/purchase/bills`
- **Method:** `POST`

**Key Fields:**
- `supplier_id`: ID of the contact.
- `bill_date`: Date of the bill.
- `due_date`: Due date for payment.
- `line_items`: Array of objects containing `amount`, `tax_id`, and
  `booking_account_id`.
- `attachment_ids`: Array of file UUIDs.

## Lookups and configuration

The following endpoints are used to populate caches and validate data.

- **Taxes:** `GET /3.0/taxes` - Fetches available tax rates and their IDs.
- **Accounts:** `GET /2.0/accounts` - Fetches the chart of accounts.
- **User Profile:** `GET /3.0/users/me` - Retrieves the authenticated user's ID.
- **Company Profile:** `GET /2.0/company_profile` - Retrieves tenant-level info.

## Error handling

The API returns standard HTTP status codes:
- **401 Unauthorized:** Missing or invalid token.
- **403 Forbidden:** Insufficient permissions/scopes.
- **422 Unprocessable Entity:** Validation errors (check response body for
  details).
- **429 Too Many Requests:** Rate limit exceeded.

## Rate limiting

The Bexio API implements rate limiting. If you receive a `429` status code, wait
before retrying. The project uses `tenacity` for exponential backoff.
