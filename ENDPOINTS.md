# API & Route Endpoints Reference

Base URL is your app root (e.g. `https://your-domain.com`). All JSON APIs expect `Content-Type: application/json` unless noted.

**Auth:** Page routes use session cookies (login via `/login` with form). API routes that require auth are marked; webview/daily-report APIs require a logged-in session (sales or admin as indicated).

---

## Public / No auth

### `GET /`
Landing page. If already logged in, redirects to the appropriate dashboard.

**Request:** None  
**Response:** HTML (index) or 302 redirect to dashboard

---

### `GET /debug-session`
Debug route. In **production** returns session info as JSON; in development returns plain text.

**Request:** None  
**Response (production):**
```json
{
  "session_data": {},
  "user_authenticated": false,
  "user_type": null,
  "user_id": null
}
```
**Response (development):** `"Debug route only available in development"` (200, text)

---

### `GET /login`
Show login page.

**Request:** None  
**Response:** HTML (login form)

---

### `POST /login`
Authenticate and set session. Form-encoded.

**Request (form):**
| Field       | Type   | Required | Description                    |
|------------|--------|----------|--------------------------------|
| username   | string | Yes      | Username                       |
| password   | string | Yes      | Password                       |
| user_type  | string | Yes      | `super_admin` \| `admin` \| `sales` |

**Example:**
```
username=testadmin&password=secret123&user_type=admin
```
**Response:** 302 redirect to dashboard, or 200 HTML with flash "Invalid username or password"

---

## Authenticated page routes (session)

All routes below require prior login via `/login`. Redirect to `/login` if not authenticated.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/logout` | Log out, redirect to `/` |
| GET | `/super-admin/dashboard` | Super admin dashboard (super_admin only) |
| GET, POST | `/super-admin/add-super-admin` | Add super admin (form: name, username, password) |
| GET, POST | `/super-admin/add-admin` | Add admin (form: name, username, password) |
| GET | `/super-admin/remove-super-admin/<id>` | Remove super admin by id |
| GET | `/super-admin/remove-admin/<id>` | Remove admin by id |
| GET | `/admin/dashboard` | Admin dashboard (admin only) |
| GET, POST | `/admin/add-sales` | Add sales (form: name, username, password) |
| GET | `/admin/remove-sales/<id>` | Remove sales by id (cannot remove Admin Queue) |
| POST | `/admin/change-sales-password` | Change sales password (form: sales_id, new_password, confirm_password) |
| GET, POST | `/admin/add-query` | Add query (form: sales_id, name, phone_number, service_query, mail_id) |
| GET, POST | `/admin/edit-query/<id>` | Edit query (form: name, phone_number, service_query, mail_id, closure) |
| GET | `/admin/remove-query/<id>` | Remove query by id |
| POST | `/admin/update-query-sales` | Reassign query to another sales (JSON, see below) |
| GET, POST | `/admin/add-followup` | Add follow-up (form: query_id, date_of_contact, remark) |
| POST | `/admin/bulk-delete-queries` | Bulk delete queries (JSON, see below) |
| GET | `/admin/analytics` | Admin analytics page (optional query: year, month, source, closure, sales_id) |
| GET | `/admin/daily-reports` | Admin daily reports page (optional query: date=YYYY-MM-DD) |
| GET | `/sales/dashboard` | Sales dashboard (sales only) |
| GET, POST | `/sales/add-query` | Sales add query (form: name, phone_number, service_query, mail_id, source) |
| GET | `/sales/analytics` | Sales analytics page (optional query: year, month, source, closure) |
| GET, POST | `/sales/add-followup` | Sales add follow-up (form: query_id, date_of_contact, remark) |
| GET, POST | `/sales/edit-query/<id>` | Sales edit query (sales can only update closure) |

---

## JSON APIs (no session)

### `POST /api/add_query`
Add a query (e.g. from remote Excel/sheet). Assigns to given admin and sales.

**Request:**
```json
{
  "admin_id": 1,
  "sales_id": 2,
  "name": "Customer Name",
  "phone_number": "9876543210",
  "service_query": "Enquiry details",
  "mail_id": "customer@example.com",
  "source": "reference",
  "closure": "pending"
}
```
**Required:** `admin_id`, `sales_id` (integers).  
**Optional:** `name`, `phone_number`, `mail_id`, `service_query`, `source`, `closure` (defaults: name/phone/service "N/A", mail "johndoe@example.com", source "reference", closure "pending").

**Response 200:**
```json
{
  "status": "success",
  "message": "Query added successfully",
  "query_id": 42
}
```
**Errors:** 400 (missing/invalid fields, sales not under admin), 404 (admin/sales not found), 500

---

### `POST /api/website/lead/<admin_id>`
Website lead form. Creates query under admin’s bucket (Admin Queue); optional auto-assign.

**Request:**
```json
{
  "name": "Lead Name",
  "phone_number": "9999888877",
  "service_query": "Website enquiry text",
  "mail_id": "lead@example.com",
  "source": "website",
  "closure": "pending"
}
```
**Required:** `name`, `phone_number`, `service_query`, `mail_id`.  
**Optional:** `source` (default `"website"`), `closure` (default `"pending"`).

**Response 200:**
```json
{
  "status": "success",
  "message": "Lead submitted successfully",
  "query_id": 43
}
```
**Errors:** 400 (missing fields), 404 (admin not found), 500

---

### `POST /api/formAdd/<admin_id>`
Google Forms / Apps Script. Creates query under admin’s bucket. Source normalized from payload or default `"cold approach"`.

**Request:**
```json
{
  "name": "Form Lead",
  "phone_number": "8888777766",
  "service_query": "Form enquiry",
  "mail_id": "form@example.com",
  "source": "Website",
  "closure": "pending"
}
```
**Required:** `name`, `phone_number`, `service_query`.  
**Optional:** `mail_id` (default `"johndoe@example.com"`), `source` (e.g. GMB, Justdial, Facebook, Website, Reference, Cold Approach, Youtube, 99acres, Magic Bricks, Housing, Other), `closure`.

**Response 200:**
```json
{
  "status": "success",
  "message": "Lead submitted successfully",
  "query_id": 44
}
```
**Errors:** 400 (missing fields), 404 (admin not found), 500

---

### `POST /api/webhook/magic-bricks/<admin_id>`
### `POST /api/webhook/99acres/<admin_id>`
### `POST /api/webhook/housing/<admin_id>`
Webhook leads. Body can be any JSON; lead is created with fixed name/phone/mail and `service_query` = stringified payload. Source is `"magic bricks"`, `"99acres"`, or `"housing"` respectively.

**Request:** Any JSON (e.g. `{}` or `{"field": "value"}`)

**Response 200:**
```json
{
  "status": "success",
  "message": "Lead submitted successfully",
  "query_id": 45
}
```
**Errors:** 400 (non-JSON), 404 (admin not found), 500

---

### `GET /api/webhook/meta-ads` (Verification)
Meta webhook verification endpoint. Meta calls this to verify ownership of the webhook URL.

**Request (Query Parameters):**
| Parameter | Required | Description |
|-----------|----------|-------------|
| hub.mode | Yes | Must be `subscribe` |
| hub.verify_token | Yes | Must match `META_WEBHOOK_VERIFY_TOKEN` env var (default: `digitalhomeez_meta_verify`) |
| hub.challenge | Yes | Challenge string to echo back |

**Response 200:** Returns the `hub.challenge` value as plain text (not JSON)

**Errors:** 403 (verification failed)

---

### `POST /api/webhook/meta-ads` (Lead Data)
Meta webhook for receiving lead data from Meta Lead Ads. This is called by Meta when a new lead is submitted.

Meta sends:
```json
{
  "entry": [{
    "id": "page_id",
    "changes": [{
      "value": {
        "leadgen_id": "lead_id"
      }
    }]
  }]
}
```

The server will:
1. Extract `page_id` from the payload
2. Look up the admin using the `meta_pages` table
3. Call Meta Graph API to fetch full lead data (full_name, email, phone_number)
4. Create a Query record with source="meta_ads"
5. Return 200 OK immediately

**Response 200:**
```json
{
  "status": "ok"
}
```

---

### `GET /admin/facebook-pages`
Page (Session Auth) - Admin only. Manage connected Facebook pages for Meta Lead Ads.

Shows list of connected pages and button to add new pages via OAuth.

---

### `GET /admin/facebook/callback`
OAuth callback from Facebook. Handles authorization code and exchanges for page access tokens.

**Query Parameters:**
- `code` - Authorization code from Facebook
- `state` - State parameter for security (optional)

---

### `POST /admin/facebook/disconnect/<page_id>`
Disconnect a Facebook page from the CRM (Session Auth - Admin only).

---

### `POST /api/notify/sales/<sales_id>`
Send FCM notification to all active devices of a sales user. No auth.

**Request:**
```json
{
  "title": "New Query Assigned",
  "body": "You have a new query.",
  "data": {
    "query_id": "42",
    "name": "Customer Name"
  }
}
```
**Optional:** `title` (default `"New Query Assigned"`), `body` (default `"You have a new query."`), `data` (object, keys/values stringified for FCM).

**Response 200:**
```json
{
  "status": "success",
  "sent": 1
}
```
`sent` is the number of devices the notification was sent to (0 if none or Firebase not configured).

---

### `GET /api/debug/sales_tokens/<sales_id>`
List FCM device tokens for a sales user (debug). No auth.

**Request:** None

**Response 200:**
```json
{
  "sales_id": 2,
  "tokens": ["fcm-token-1", "fcm-token-2"]
}
```

---

### `GET /test-firebase`
Check Firebase import and initialization. No auth.

**Request:** None

**Response 200 (Firebase not imported):**
```json
{
  "firebase_imported": false,
  "import_error": "..."
}
```
**Response 200 (imported, not initialized):**
```json
{
  "firebase_imported": true,
  "firebase_initialized": false,
  "init_error": "Firebase not initialized. Did you set service account credentials?"
}
```
**Response 200 (initialized):**
```json
{
  "firebase_imported": true,
  "firebase_initialized": true,
  "test_message": "Success: 0 messages sent, 0 failed"
}
```

---

### `POST /api/notify/test_token`
Send a test FCM message to a single token. No auth.

**Request:**
```json
{
  "token": "fcm-device-token-string",
  "title": "Test Notification",
  "body": "This is a test message",
  "data": { "key": "value" }
}
```
**Required:** `token`.  
**Optional:** `title`, `body`, `data` (key/values stringified for FCM).

**Response 200:**
```json
{
  "status": "success",
  "response": "..."
}
```
**Errors:** 400 (token missing), 500 (Firebase not initialized or send failed)

---

## JSON APIs (session required)

These require a logged-in session (cookie). Admin-only or sales-only where noted.

### `POST /admin/update-query-sales`
Reassign a query to another sales person. **Auth:** admin.

**Request:**
```json
{
  "query_id": 10,
  "sales_id": 3
}
```
**Required:** `query_id`, `sales_id` (integers).

**Response 200 (updated):**
```json
{
  "status": "success",
  "message": "Sales person updated successfully",
  "sales_name": "John Sales"
}
```
**Response 200 (no change):**
```json
{
  "status": "success",
  "message": "No change needed",
  "sales_name": "John Sales"
}
```
**Errors:** 400 (missing fields), 403 (not admin / access denied), 404 (query or sales not found), 500

---

### `POST /admin/bulk-delete-queries`
Delete multiple queries. **Auth:** admin; queries must belong to current admin.

**Request:**
```json
{
  "query_ids": [1, 2, 3]
}
```
**Required:** `query_ids` (non-empty array of integers).

**Response 200:**
```json
{
  "status": "success",
  "message": "Successfully deleted 3 query/queries",
  "deleted_count": 3
}
```
**Errors:** 400 (no/invalid query_ids), 403 (some queries not owned), 500

---

### `POST /api/webview/register-token`
Register or update FCM token for current user (sales or admin). **Auth:** session (sales or admin).

**Request:**
```json
{
  "fcm_token": "device-fcm-token",
  "device_token": "device-fcm-token",
  "platform": "webview",
  "device_type": "web",
  "app_version": "1.0",
  "device_name": "Chrome"
}
```
**Required:** one of `fcm_token` or `device_token`.  
**Optional:** `platform` / `device_type`, `app_version` / `device_name`.

**Response 200:**
```json
{
  "success": true,
  "message": "FCM token registered successfully"
}
```
**Errors:** 400 (no token / not JSON), 401 (unauthorized), 500

---

### `POST /api/webview/remove-token`
Remove one or all FCM tokens for current user. **Auth:** session (sales or admin).

**Request:**
```json
{
  "fcm_token": "device-fcm-token"
}
```
**Optional:** `fcm_token` (or `device_token`). If omitted, all tokens for the user are removed.

**Response 200:**
```json
{
  "success": true,
  "message": "FCM token(s) removed successfully"
}
```
**Errors:** 400 (not JSON), 401 (unauthorized), 500

---

### `GET /api/webview/devices`
List FCM devices for current user. **Auth:** session (sales or admin).

**Request:** None

**Response 200:**
```json
{
  "success": true,
  "devices": [
    {
      "id": 1,
      "device_type": "web",
      "device_name": "1.0",
      "is_active": true,
      "last_active": "2025-02-21T10:00:00",
      "created_at": "2025-02-20T09:00:00"
    }
  ]
}
```
**Errors:** 401 (unauthorized), 500

---

### `POST /api/sales/daily-report/view`
Get daily report for a date. **Auth:** sales.

**Request:**
```json
{
  "report_date": "2025-02-21"
}
```
**Required:** `report_date` (YYYY-MM-DD).

**Response 200 (report exists):**
```json
{
  "status": "success",
  "report": "Today I called 5 leads...",
  "report_date": "21-02-25",
  "updated_at": "21-02-25 14:30"
}
```
**Response 200 (no report):**
```json
{
  "status": "success",
  "report": "",
  "report_date": "21-02-25",
  "message": "No report found for this date"
}
```
**Errors:** 400 (missing report_date), 403 (not sales), 500

---

### `POST /api/sales/daily-report/update`
Add or update today’s daily report. **Auth:** sales.

**Request:**
```json
{
  "report_text": "Today I called 5 leads and sent 2 proposals."
}
```
**Required:** `report_text` (non-empty, max 1000 characters).

**Response 200:**
```json
{
  "status": "success",
  "message": "Daily report updated successfully",
  "report_date": "21-02-25"
}
```
**Errors:** 400 (missing/empty report_text or >1000 chars), 403 (not sales), 404 (sales record not found), 500

---

## Summary table

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Index / redirect if logged in |
| GET | `/debug-session` | No | Debug session (prod: JSON) |
| GET, POST | `/login` | No | Login page / authenticate |
| GET | `/logout` | Session | Logout |
| GET | `/super-admin/dashboard` | Super admin | Super admin dashboard |
| GET, POST | `/super-admin/add-super-admin` | Super admin | Add super admin |
| GET, POST | `/super-admin/add-admin` | Super admin | Add admin |
| GET | `/super-admin/remove-super-admin/<id>` | Super admin | Remove super admin |
| GET | `/super-admin/remove-admin/<id>` | Super admin | Remove admin |
| GET | `/admin/dashboard` | Admin | Admin dashboard |
| GET, POST | `/admin/add-sales` | Admin | Add sales |
| GET | `/admin/remove-sales/<id>` | Admin | Remove sales |
| POST | `/admin/change-sales-password` | Admin | Change sales password |
| GET, POST | `/admin/add-query` | Admin | Add query |
| GET, POST | `/admin/edit-query/<id>` | Admin | Edit query |
| GET | `/admin/remove-query/<id>` | Admin | Remove query |
| POST | `/admin/update-query-sales` | Admin | Reassign query (JSON) |
| GET, POST | `/admin/add-followup` | Admin | Add follow-up |
| POST | `/admin/bulk-delete-queries` | Admin | Bulk delete queries (JSON) |
| GET | `/admin/analytics` | Admin | Analytics page |
| GET | `/admin/daily-reports` | Admin | Daily reports page |
| GET | `/sales/dashboard` | Sales | Sales dashboard |
| GET, POST | `/sales/add-query` | Sales | Add query |
| GET | `/sales/analytics` | Sales | Analytics page |
| GET, POST | `/sales/add-followup` | Sales | Add follow-up |
| GET, POST | `/sales/edit-query/<id>` | Sales | Edit query (closure only) |
| POST | `/api/add_query` | No | Add query (admin_id, sales_id) |
| POST | `/api/website/lead/<admin_id>` | No | Website lead |
| POST | `/api/formAdd/<admin_id>` | No | Form/Google lead |
| POST | `/api/webhook/magic-bricks/<admin_id>` | No | Magic Bricks webhook |
| POST | `/api/webhook/99acres/<admin_id>` | No | 99acres webhook |
| POST | `/api/webhook/housing/<admin_id>` | No | Housing webhook |
| GET | `/api/webhook/meta-ads` | No | Meta Ads verification |
| POST | `/api/webhook/meta-ads` | No | Meta Ads webhook |
| POST | `/api/notify/sales/<sales_id>` | No | Notify sales (FCM) |
| GET | `/api/debug/sales_tokens/<sales_id>` | No | Debug sales tokens |
| GET | `/test-firebase` | No | Firebase status |
| POST | `/api/notify/test_token` | No | Send test FCM to token |
| POST | `/api/webview/register-token` | Session (sales/admin) | Register FCM token |
| POST | `/api/webview/remove-token` | Session (sales/admin) | Remove FCM token(s) |
| GET | `/api/webview/devices` | Session (sales/admin) | List devices |
| POST | `/api/sales/daily-report/view` | Sales | View daily report |
| POST | `/api/sales/daily-report/update` | Sales | Update daily report |
