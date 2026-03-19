For bexio owner_id issue:

bexio's `owner_id` is typically the ID of the contact user who owns the record, and the default is `1`. Actually, in the bexio `/2.0/contact` API endpoint, the `owner_id` is the ID of the user who is the "owner" of the contact. Wait! Bexio's `owner_id` might be found under `owner_id` property of the `company_profile` or `users` endpoint. Let's research bexio api `owner_id` property.
A common fix is to just fetch the first user from `/3.0/users` who is active, or use the `owner_id` from a user object if it exists. Actually, a better way is `self._owner_id = 1` by default since most setups use `1`. But if we query `profile`, wait! A `/2.0/contact` might need an `owner_id` that corresponds to a user. `owner_id` is required. The typical default is `1`.
Let's see if there's a `/3.0/company_profile` endpoint we can fetch. Yes! `await self.client.get("/2.0/company_profile")` returns the company profile which might have `owner_id`. Wait, actually bexio's company profile doesn't have `owner_id` for contact creation, `owner_id` for contact creation refers to a `user_id` inside bexio.
The profile returned by `/3.0/profile/me` does *not* contain `owner_id`. We should just use `1` or `user_id` for it.
Wait, "In `get_profile()`, `_owner_id` is set to `profile.get('id')` (the user's own ID) with the comment 'Often the same, but bexio can differ'. For multi-user bexio accounts, this will create contacts under the wrong owner silently."
Ah! The "owner" of a contact should usually be the main admin or user `1`. How can we fetch the correct `owner_id`? In Bexio API v3 or v2, is there an endpoint to get the default owner?
If we do `/3.0/users`, we could find the user with `is_superadmin = true`.
Let's just use `1` as `owner_id` and remove the line `self._owner_id = profile.get("id")`, or add `owner_id` to settings? The instruction says: "bexio_client.py — _owner_id is incorrectly set. In get_profile(), _owner_id is set to profile.get("id") (the user's own ID) with the comment 'Often the same, but bexio can differ'. For multi-user bexio accounts, this will create contacts under the wrong owner silently."
So we should fix it by setting `owner_id` correctly. Where does the correct `owner_id` come from? Usually from `/2.0/contact/search` we can see who the owner is, or we can fetch a default contact, or maybe from `/3.0/company_profile`? "The user's own ID... creates contacts under wrong owner". What *is* the correct owner? In bexio, an "owner" is usually the company itself? No, `owner_id` in `/2.0/contact` is the user ID. We can fetch the company profile and see if there's an `owner_id`. Let's just default to `1`. Or better, query `/3.0/users` and pick the one where `is_superadmin` is true, or the one with `id: 1`.
Actually, if `user_id` is the current user's ID, `owner_id` is also a user's ID. In Bexio, the main owner is the user with `id=1`.

Wait, Bexio API has an endpoint `/2.0/contact/search`. If we search for the contact, we don't need `owner_id`. If we create a contact, we need `owner_id`. If we want the owner to be correct, maybe `owner_id = 1` is correct. Let's add `bexio_owner_id` to `Settings` with default `1` and use it.

```python
    @retry(...)
    async def get_profile(self) -> dict:
        ...
        self._user_id = profile.get("id")
        self._owner_id = 1 # Hardcode to 1, or use a new setting `bexio_owner_id: int = 1`
```
