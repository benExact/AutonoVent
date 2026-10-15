# Autonovent

The public site is static HTML, CSS, and JavaScript. The API is a separate Python service. This milestone is the database and API foundation only. Checkout, PayFast, courier booking, and the admin portal are not implemented.

## What is already decided

- PostgreSQL stores orders and related records.
- FastAPI provides the HTTP API under `/api/v1`.
- Money is stored as integer cents. Floating-point amounts are not used.
- Product price, SKU, parcel size, parcel weight, and the collection address are not invented. Those columns stay empty until they are confirmed.
- The browser is not the order database.

## Local setup on Windows

These commands were run on this machine with Python 3.14.7 and Docker Engine 29.7.2. The pinned backend packages installed and imported on that Python. PostgreSQL is not installed as a Windows service; Docker Compose provides it. The `psql` client is not required.

Start Docker Desktop and wait until the engine is running before the database commands. This setup uses only the local database in `docker-compose.yml`.

### 1. Start PostgreSQL

From `C:\Projects\AutonoVent`:

```powershell
docker compose up -d
docker compose ps
```

`docker compose ps` should show `autonovent-postgres-1` as healthy, with `127.0.0.1:5432->5432/tcp`. That bind address does not publish PostgreSQL beyond this computer.

### 2. Backend environment

From `C:\Projects\AutonoVent\backend`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy ..\.env.example .env
```

`backend/.env` is ignored by `.gitignore`. `.env.example` is not. The virtual environment used for the checks below already existed at `backend\.venv`.

### 3. Apply migrations

From `C:\Projects\AutonoVent\backend`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

`current` prints `20261014_0001 (head)`. Running `upgrade head` again reports nothing further to apply. The migration creates `products`, `orders`, `order_items`, `payments`, `shipments`, `order_status_events`, and `admin_users`. It does not insert a product, price, SKU, shipment, or admin user.

### 4. Start FastAPI

From `C:\Projects\AutonoVent\backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Port 8000 was already taken on this machine by another local application, so the verified server used port 8001. Use 8000 when it is free.

- Liveness: `http://127.0.0.1:8001/api/v1/health` returns `{"status":"ok","service":"autonovent-api"}`.
- Readiness: `http://127.0.0.1:8001/api/v1/health/ready` returns `{"status":"ok","database":"reachable"}` when PostgreSQL is up.

Readiness returns 503 when `DATABASE_URL` is empty or PostgreSQL refuses the connection.

The product page reads the public catalogue from `js/config.js`. That file holds only the API base URL:

```javascript
window.AUTONOVENT_API_BASE_URL = "http://127.0.0.1:8001";
```

Change that value when the API is served somewhere else. On this machine port 8000 is already used by another local application, so the verified API address is port 8001. The setting must not contain a database password or any other secret.

`GET /api/v1/products` returns `{"products":[]}` until a product is active and has a confirmed price in PostgreSQL. Inactive products, and active products without a price, are left out. The page shows a loading line, then that empty state. If the API cannot be reached, it shows an error and a Try again button. It does not display a made-up price.

### 5. Run tests

From `C:\Projects\AutonoVent\backend`, with PostgreSQL running:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The database tests create an isolated local database named `autonovent_test` and do not write to a database outside this machine.

### 6. Stop the local database

From `C:\Projects\AutonoVent`:

```powershell
docker compose down
```

This stops the container and keeps the Docker volume. `docker compose down -v` also deletes that volume and the migrated data.

## Order creation

No public endpoint accepts an order yet. Creating one still depends on a confirmed selling price, a confirmed SKU if one will be used, a decision on whether stock is tracked, and a server-side shipping rule. Payment collection, courier booking, and the admin portal stay out of this step.

When order creation is implemented, it will follow these rules:

- `POST /api/v1/orders` accepts the customer’s contact details, a South African delivery address, and product quantities. The browser does not send prices.
- The server loads each product from PostgreSQL. A line is accepted only when that product is active and `unit_price_cents` is set. Unknown, inactive, or unpriced products reject the request.
- Quantities are positive integers. The server calculates each line total, the subtotal, and `total_cents = subtotal_cents + shipping_cents`. Amounts stay in integer cents.
- Until a shipping rule exists, the endpoint stays closed. The browser must not supply `shipping_cents`.
- Each order item stores the product name, SKU, unit price, quantity, and line total as they were at creation.
- `payment_status` starts as `pending`. `fulfilment_status` starts as `unfulfilled`.
- The order, its items, and the opening status events are written in one transaction. An invalid request rolls back and leaves no partial order.
- The client sends an `Idempotency-Key`. Migration `20261014_0002` stores that key and a fingerprint of the request. The same key and the same request return the original order. The same key with a different request does not create a second order. A missing key is rejected.
- The response contains the order id and order number only. There is no public list or detail endpoint for orders, payments, addresses, or admin users.

## Order management

There is no public order endpoint. `GET /api/v1/orders` and `POST /api/v1/orders` are not registered. Customer details are not returned by the catalogue or health routes.

The internal order service records an order, its item snapshots, and the opening status events in one transaction. Item prices are read from `products.unit_price_cents`. A line is rejected when the product is missing, inactive, or has no price, and that rejection leaves no partial order. Shipping is stored only when the server supplies `shipping_cents`. The service does not default it to zero and does not call Bob Go.

Repeated creation with the same idempotency key and the same request returns the original order. The same key with a different request raises a conflict and does not insert another order. The key and its fingerprint are stored on `orders` by migration `20261014_0002`.

Fulfilment changes append a timestamped `order_status_events` row. The service has no operation that sets `payment_status` to `paid`. Payment status stays `pending` until a verified payment notification, or a later audited administrative process, is approved.

The private order screens are `owner/orders.html` and `owner/order.html`. They call the authenticated order routes below. Public order submission is still closed.

## Owner authentication

Owner sign-in is `POST /api/v1/auth/login`. Logout is `POST /api/v1/auth/logout`. The current owner is `GET /api/v1/auth/me`, which returns only the email and role. There is no registration route.

Passwords are stored with Argon2id through `argon2-cffi`. The session cookie `autonovent_session` is `HttpOnly` and `SameSite=Lax`. PostgreSQL stores only a SHA-256 hash of the session id, plus expiry, last-seen time, and revocation time. A session lasts 12 hours and is dropped after 2 hours without use. Login creates a new session and revokes the previous one.

State-changing authentication requests must send the `X-CSRF-Token` header that matches the `autonovent_csrf` cookie and the hash stored with the session. Login first calls `GET /api/v1/auth/csrf`. Failed passwords and unknown emails return the same message. After 5 failures in 15 minutes, from the same email or source address, login returns 429.

The session cookie is `Secure` only when `APP_ENV=production`. Local HTTP development leaves it unset so the browser will keep the cookie. Do not use that exception on a public HTTPS site.

The static page and the API must use the same host, normally `127.0.0.1`, because the site is `http://127.0.0.1:8765` and the API is `http://127.0.0.1:8001`. CORS allows those origins and sends cookies. Open `http://127.0.0.1:8765/owner/login.html`.

Create the first owner from `backend`, with the virtual environment active. The command prompts for the email and password and does not accept them as arguments. It refuses to run when an owner already exists, and it refuses a database that is not on this machine.

```powershell
.\.venv\Scripts\python.exe -m app.admin.bootstrap
```

No default password is stored in the repository.

Signed-in order routes require the owner session. Fulfilment changes also require `X-CSRF-Token`.

- `GET /api/v1/orders/summary` returns counts only.
- `GET /api/v1/orders` returns a page of orders. `limit` is 1 to 50 and `offset` starts at 0.
- `GET /api/v1/orders/{id}` returns the customer, delivery address, item snapshots, amounts, payment status, payment reference when one exists, fulfilment status, and status history.
- `PATCH /api/v1/orders/{id}/fulfilment` accepts `{"status": "processing"}` and the later steps `shipped`, `delivered`, or `cancelled` where that change is allowed. It appends a history row in the same transaction and records the owner email as the actor. It does not change payment status.

There is still no route that marks an order paid. `POST /api/v1/orders` remains closed.

Owner product routes are under `/api/v1/admin`. Listing and the readiness checklist require the owner session. Creating or editing a product also requires `X-CSRF-Token`.

- `GET /api/v1/admin/products` returns every saved product, including inactive products and products with no price.
- `POST /api/v1/admin/products` and `PATCH /api/v1/admin/products/{id}` save the name, slug, description, optional SKU, price in integer cents, currency `ZAR`, and active flag. An empty price is stored as no price. Negative prices, fractional prices, and other currencies are rejected.
- The public catalogue is unchanged: only an active product with a price is returned. Changing a product does not change prices already copied onto an order.
- `GET /api/v1/admin/readiness` reports whether a selling price is saved and states that the collection address, packed parcel size, Bob Go rate test, and payment setup are still missing. It never returns a token. `checkout_enabled` stays false.
- `GET /api/v1/admin/products/{id}/audit` returns the owner email, time, and previous and new values for product fields. It is not public. Order fulfilment history stays in `order_status_events` and is not reused for products.

Migration `20261015_0003` adds `product_audit_events`. A product save and its audit row commit together. The log stores only product fields: name, slug, description, SKU, price in cents, currency, and active flag.

Open `http://127.0.0.1:8765/owner/products.html` and `http://127.0.0.1:8765/owner/readiness.html` after signing in. No product or price is seeded.

Migration `20261015_0002` widens `order_status_events.actor` from 160 to 254 characters so the owner email fits. It does not insert orders.

After signing in at `http://127.0.0.1:8765/owner/login.html`, the browser opens `http://127.0.0.1:8765/owner/orders.html`. The API stays on `http://127.0.0.1:8001`. Use the same host for both. An empty database shows zero counts and “No orders have been recorded.”

## Bob Go sandbox rates

Rate quotes use Bob Go API v2 sandbox only: `https://api.sandbox.bobgo.co.za/v2`. The official collection authenticates with a bearer token and requests courier rates at `POST /rates`. Production (`https://api.bobgo.co.za/v2`) is rejected. The client does not create shipments.

`POST /rates-at-checkout` is not used. That endpoint requires an item price, and no selling price has been confirmed.

The product’s unit size is 187 × 150 × 41 mm and its unit weight is 2 kg. Those are not confirmed packed parcel measurements, so they are not sent as shipping dimensions. A quote also needs the Rhino Canopies warehouse street address, suburb, province or zone, and postal code. None of those address fields has been supplied. Put the sandbox token in `backend/.env` as `BOBGO_API_TOKEN`. The example file leaves it empty.

## Public website

From the repository root:

```powershell
python -m http.server 8765 --bind 127.0.0.1
```

Open `http://127.0.0.1:8765/`. The product page calls `GET /api/v1/products`. The other pages do not.

## Database backup and restore

Backups are not automated and are not copied off this machine. A dump can contain customer and order details once those exist, so keep it outside the Git repository. The `backups/` directory is ignored. Do not email a dump or commit it. On Windows, limit the folder to your user account.

These commands use the local Docker PostgreSQL service. They do not print the database password. `pg_dump` runs inside the container. Restore only into a new database name. Do not restore over `autonovent`.

From the repository root, create a custom-format dump of the working database:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T postgres pg_dump -U autonovent -d autonovent --format=custom --no-owner --no-acl --file=/tmp/autonovent.dump
docker compose cp postgres:/tmp/autonovent.dump backups/autonovent.dump
docker compose exec -T postgres rm -f /tmp/autonovent.dump
```

To rehearse a restore, create an empty database and load the dump there:

```powershell
docker compose exec -T postgres psql -U autonovent -d postgres -c "CREATE DATABASE autonovent_restore"
docker compose cp backups/autonovent.dump postgres:/tmp/autonovent-restore.dump
docker compose exec -T postgres pg_restore -U autonovent -d autonovent_restore --no-owner --no-acl /tmp/autonovent-restore.dump
docker compose exec -T postgres psql -U autonovent -d autonovent_restore -c "SELECT version_num FROM alembic_version"
docker compose exec -T postgres rm -f /tmp/autonovent-restore.dump
```

Compare `version_num` with `alembic current` from `backend`. Check that the restored table list matches the source and that a known synthetic row is present. Drop the rehearsal database when finished:

```powershell
docker compose exec -T postgres psql -U autonovent -d postgres -c "DROP DATABASE autonovent_restore"
```

If a connection blocks the drop, disconnect it from `postgres` and run the drop again. Do not run `DROP DATABASE autonovent`.

## Hosting, when deployment is approved

Nothing in this milestone is deployed.

- Publish the existing HTML, CSS, JavaScript, and assets as a static site. The current `netlify.toml` only publishes those files. It does not run the API.
- Run the FastAPI process behind HTTPS. A small virtual machine with a reverse proxy, or a container host, is enough. The API process should not be exposed without TLS.
- Run PostgreSQL on a private network reachable only by the API. Do not publish port 5432 to the internet.
- Set `CORS_ORIGINS` to the real website origin. Wildcard CORS is rejected.
- Accounts that will be needed later, and are not created here: the static host, the API host, a PostgreSQL service, a domain and certificate, a PayFast merchant account, and Bob Go API access.

## Not in this milestone

Public checkout, payment capture, live courier booking, stock tracking, and production deployment are intentionally absent. Backups are manual and local only.
