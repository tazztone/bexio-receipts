from fastapi import FastAPI, Header, HTTPException, Request
from typing import Optional
import uvicorn

app = FastAPI(title="Mock Bexio API")

@app.get("/2.0/company_profile")
async def get_company_profile(authorization: Optional[str] = Header(None)):
    return {"owner_id": 1, "name": "Mock Company"}

@app.get("/3.0/profile/me")
async def get_profile_me(authorization: Optional[str] = Header(None)):
    return {"id": 1, "name": "Mock User"}

@app.get("/3.0/taxes")
async def get_taxes(authorization: Optional[str] = Header(None)):
    return [{"id": 1, "value": 8.1}, {"id": 2, "value": 2.6}, {"id": 3, "value": 3.8}]

@app.get("/2.0/accounts")
async def get_accounts(authorization: Optional[str] = Header(None)):
    return [
        {"id": 100, "account_no": "6000", "name": "Testing Account"},
        {"id": 200, "account_no": "1020", "name": "Bank Account"}
    ]

@app.post("/3.0/files")
async def upload_file(request: Request, authorization: Optional[str] = Header(None)):
    return {"id": "mock-file-uuid", "name": "mock-file.png"}

@app.post("/2.0/contact/search")
async def search_contact(request: Request, authorization: Optional[str] = Header(None)):
    return []

@app.post("/2.0/contact")
async def create_contact(request: Request, authorization: Optional[str] = Header(None)):
    return {"id": 555}

@app.post("/4.0/purchase/bills")
async def create_bill(request: Request, authorization: Optional[str] = Header(None)):
    return {"id": 999}

@app.post("/4.0/expenses")
async def create_expense(request: Request, authorization: Optional[str] = Header(None)):
    return {"id": 888}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
