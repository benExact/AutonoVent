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
- The client sends an `Idempotency-Key`. A later migration will add a unique `orders.idempotency_key`. The same key and the same request return the original order reference. The same key with a different request returns 409. A missing key is rejected so a retry cannot create a second order.
- The response contains the order id and order number only. There is no public list or detail endpoint for orders, payments, addresses, or admin users.

## Public website

From the repository root:

```powershell
python -m http.server 8765 --bind 127.0.0.1
```

Open `http://127.0.0.1:8765/`. The product page calls `GET /api/v1/products`. The other pages do not.

## Hosting, when deployment is approved

Nothing in this milestone is deployed.

- Publish the existing HTML, CSS, JavaScript, and assets as a static site. The current `netlify.toml` only publishes those files. It does not run the API.
- Run the FastAPI process behind HTTPS. A small virtual machine with a reverse proxy, or a container host, is enough. The API process should not be exposed without TLS.
- Run PostgreSQL on a private network reachable only by the API. Do not publish port 5432 to the internet.
- Set `CORS_ORIGINS` to the real website origin. Wildcard CORS is rejected.
- Accounts that will be needed later, and are not created here: the static host, the API host, a PostgreSQL service, a domain and certificate, a PayFast merchant account, and Bob Go API access.

## Not in this milestone

PayFast checkout, payment notifications, courier rates, owner login, and admin order screens are intentionally absent.
