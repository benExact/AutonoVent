# AutonoVent local development guide

This guide explains how to run AutonoVent on this Windows PC. It matches the project as it is in `C:\Projects\AutonoVent` on 15 October 2026.

The public website, the owner portal, the API, and the database are separate programs. You usually need more than one PowerShell window.

Do not put passwords, API tokens, or database connection strings in this file, in Git, or in a chat. Read those values from your own `backend\.env` or from `docker-compose.yml` when a program asks for them.

## 1. Project overview

AutonoVent is a small local system with a public website and a private owner area.

| Part | What it is | Folder |
| --- | --- | --- |
| Public website | Pages the customer sees. They are plain HTML, CSS, and JavaScript. A simulated checkout page is available only when the API is in development simulation mode. | `index.html`, `product.html`, `checkout.html`, `how-it-works.html`, `installation.html`, `faq.html`, `css\`, `js\` |
| Owner portal | Private pages for the owner: sign-in, orders, products, and a readiness checklist. | `owner\` |
| Backend | A Python program built with FastAPI. It answers API requests. | `backend\app` |
| Database | PostgreSQL 16, started by Docker Compose. | `docker-compose.yml` |
| Migrations | Alembic updates the database structure in numbered steps. | `backend\alembic` |
| ShipLogic client | Code that can ask the ShipLogic **sandbox** for courier rates. It does not book shipments. | `backend\app\shipping` |
| Tests | Automated checks. They use a separate database named `autonovent_test`. | `backend\tests` |
| GitHub | The remote copy of the project. | `https://github.com/benExact/AutonoVent.git` |

What must be running:

| You want to… | Start these |
| --- | --- |
| Read the public pages only | The static website on port `8765`. The product page also needs the API if you want the live catalogue. |
| Use the catalogue, owner sign-in, orders, or products | PostgreSQL, the API on port `8001`, and the static website on port `8765`. |
| Change the database structure | PostgreSQL, then Alembic from `backend`. |
| Run automated tests | PostgreSQL. The tests start their own database. They do not need the website. |
| Look at tables | PostgreSQL, then DBeaver. The website and API can be stopped. |

The API address used by the website is set in `js\config.js`:

`http://127.0.0.1:8001`

Port `8000` is already used by another application on this PC. Do not start AutonoVent on port `8000`.

## 2. Software prerequisites

Install these once. Daily startup does not install them again.

| Software | Why | How to check in PowerShell | Official install page |
| --- | --- | --- | --- |
| Windows PowerShell | Every command in this guide is for PowerShell. | You are already in it if the prompt looks like `PS C:\...>` | Included with Windows |
| Python 3.14 | The API and the static file server. This checkout was verified with **Python 3.14.7**, both for `python` and for `backend\.venv`. | `python --version` | https://www.python.org/downloads/ |
| Docker Desktop, with Docker Compose | Runs PostgreSQL. Verified here: Docker 29.7.2 and Docker Compose v5.4.0. | `docker --version` and `docker compose version` | https://docs.docker.com/desktop/setup/install/windows-install/ |
| Git | Saves and publishes project files. Verified here: git version 2.54.0.windows.1. | `git --version` | https://git-scm.com/download/win |
| DBeaver Community Edition | Looks at the database in a window. **Not confirmed as installed on this PC while this guide was written.** | Open it from the Start menu. There is no project command that checks it. | https://dbeaver.io/download/ |
| A web browser | Opens the website and the owner portal. | Chrome, Edge, or Firefox is fine. | Use the browser you already have |

GitHub sign-in is needed only when you download or publish the repository. This PC already has a checkout whose `origin` is `https://github.com/benExact/AutonoVent.git` on branch `main`. Push authentication was **not** tried again while writing this guide. On Windows, Git usually asks through Git Credential Manager the first time you push.

### If Docker Desktop is installed but not running

1. Open the Start menu.
2. Start **Docker Desktop**.
3. Wait until the whale icon is steady and Docker says it is running. The first start can take a minute.
4. In PowerShell, run:

```powershell
docker info
```

If that command prints server information, Docker is running. If it says it cannot connect to the docker daemon, Docker Desktop is still starting or is not running. Wait, then try again. Do not delete the database because Docker was stopped.

## 3. Project directory structure

The project root is `C:\Projects\AutonoVent`.

```text
C:\Projects\AutonoVent
├── index.html              Public home page
├── product.html            Public product page and catalogue
├── how-it-works.html
├── installation.html
├── faq.html
├── css\                    Shared visual styles
├── js\                     Website and owner-portal scripts
├── owner\                  Private owner pages
├── assets\                 Images
├── docker-compose.yml      Local PostgreSQL only
├── .env.example            Template for the API settings
├── README.md               Project notes
├── LOCAL_DEVELOPMENT_GUIDE.md
└── backend\
    ├── app\                FastAPI application code
    ├── alembic\            Migration scripts
    ├── tests\              Automated tests
    ├── .venv\              Python packages for this project
    ├── .env                Your local settings. Not in Git.
    ├── requirements.txt    Python package list
    ├── alembic.ini         Alembic file layout
    └── pytest.ini          Test settings
```

Owner pages that exist today:

- `owner\login.html`
- `owner\orders.html`
- `owner\order.html`
- `owner\products.html`
- `owner\readiness.html`

The settings template is **`.env.example` in the project root**, not `backend\.env.example`. That second path does not exist. The working copy is `backend\.env`.

### What you normally edit

- Public pages, `css\`, and `js\`, when you are changing the website.
- `owner\`, when you are changing the private portal.
- `backend\app\`, when you are changing the API.
- A **new** file under `backend\alembic\versions\`, when you are changing the database structure.
- `backend\tests\`, when you are adding checks.
- `backend\.env` on your PC only. Never commit it.

### What you should not edit by hand

- `backend\.venv\`. Recreate it with Python if it breaks. Do not commit it.
- Migration files that have already been applied. Add a new migration instead.
- Table structure inside DBeaver. Use Alembic.
- `alembic.ini`’s database URL. Alembic replaces it from `backend\.env` when you run a migration. The value in `alembic.ini` is only a placeholder.
- Docker’s data volume. Stopping PostgreSQL is described in section 13. Deleting the volume deletes the data.

## 4. First-time local setup

Use this section when the folder is already on the PC and you are preparing it. Do not drop, reset, or recreate the existing `autonovent` database.

This checkout already has `backend\.venv`, `backend\.env`, and a migrated database. If those are present, skip the create steps and use section 5 for daily startup.

### 1. Open PowerShell

Open the Start menu, type `PowerShell`, and open **Windows PowerShell**.

### 2. Go to the project

```powershell
cd C:\Projects\AutonoVent
```

### 3. Check Git status

```powershell
git status
```

This lists files that differ from the last commit. It does not change the database. Do not commit during setup unless you intend to save work.

### 4. Create `backend\.env` only if it is missing

This command does nothing if `backend\.env` already exists. It will not overwrite it.

```powershell
if (-not (Test-Path .\backend\.env)) { Copy-Item .\.env.example .\backend\.env }
```

Open `backend\.env` in an editor and check these names. Do not paste the file into Git or into a message.

| Name | Local meaning |
| --- | --- |
| `APP_ENV` | Leave this as `development` on this PC. `production` turns on the secure-cookie flag, which local HTTP cannot use. |
| `DATABASE_URL` | Must point at host `127.0.0.1`, port `5432`, and database `autonovent`. The user and password must match `POSTGRES_USER` and `POSTGRES_PASSWORD` in `docker-compose.yml`. |
| `CORS_ORIGINS` | Includes `http://127.0.0.1:8765`. Do not use `*`. |
| `SHIPLOGIC_MODE` | `sandbox` when testing ShipLogic. Leave empty while simulated checkout is on. Live mode is rejected. |
| `SHIPLOGIC_API_TOKEN` | Empty until you create a sandbox token. Never commit a real token. |
| `SHIPLOGIC_SANDBOX_BASE_URL` | Must stay `https://api.shiplogic.com`. |
| `SHIPLOGIC_TIMEOUT_SECONDS` | How long a sandbox request may wait. The example value is `20`. |
| `CHECKOUT_SIMULATION_ENABLED` | `false` unless you are testing the simulated checkout. Must stay false when `APP_ENV` is `production`. |
| `CHECKOUT_SIMULATION_RATES` | Test delivery amounts in cents, such as `standard:8500,express:14500`. These are not ShipLogic prices. |
| `CHECKOUT_SIMULATION_REGION_EXTRAS` | Optional extra test cents by province name, such as `Western Cape:2000`. |
| `CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS` | Optional development-only test price in cents. Used only when a product has no confirmed `unit_price_cents`. It does not change the product record. Leave it empty in production. |
| `EMAIL_TRANSPORT` | `capture`, `smtp`, or `resend`. `capture` does not open a network connection. Production must use `smtp` or `resend`. |
| `SMTP_HOST` / `SMTP_PORT` | SMTP server. Local Mailpit uses `127.0.0.1` and `1025`. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Optional SMTP credentials. Leave empty for Mailpit. Do not commit real credentials. |
| `SMTP_USE_TLS` | `true` when the SMTP server requires STARTTLS. |
| `EMAIL_FROM` | From address, for example `Autonovent <orders@example.com>`. Resend testing can use `onboarding@resend.dev` only for the account address until a domain is verified. |
| `RESEND_API_KEY` | Resend API key. Leave empty unless `EMAIL_TRANSPORT=resend`. Do not commit it. |
| `EMAIL_LOGO_URL` | Optional absolute logo URL. Leave empty to use the text wordmark. |
| `EMAIL_MAX_ATTEMPTS` | How many times a queued notification may be attempted. |

The shape of `DATABASE_URL`, with the secret left out, is:

```text
postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/autonovent
```

### Simulated checkout

The customer test journey is off until `backend\.env` contains `APP_ENV=development` and `CHECKOUT_SIMULATION_ENABLED=true`, plus test delivery amounts such as `CHECKOUT_SIMULATION_RATES=standard:8500,express:14500`. Those amounts are for the demonstration. They are not ShipLogic prices. Restart the API after changing the file.

`CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS` is a separate local setting, also in `backend\.env`. It lets an active product with an empty selling price appear in the shop during development. The shop labels it as a test price. The value is snapshotted onto the order and is never written into `products.unit_price_cents`. A product that already has a selling price always uses that selling price. Leave the setting empty unless you are testing checkout. Production refuses to start if it is set.

Open `http://127.0.0.1:8765/product.html`, add the listed product, and continue on `http://127.0.0.1:8765/checkout.html`. The owner order list marks these rows as simulated test orders.

If `APP_ENV=production` and `CHECKOUT_SIMULATION_ENABLED=true` together, the API refuses to start. Keep the flag false for any production configuration. With the flag false, the quote and payment addresses respond with “not available”.

## ShipLogic and PayFast sandbox

Sandbox checkout is separate from the simulated checkout. Set `CHECKOUT_SIMULATION_ENABLED=false`, `COURIER_PROVIDER=shiplogic`, `SHIPLOGIC_MODE=sandbox`, and `PAYMENT_PROVIDER=payfast`. Also set `PAYFAST_MODE=sandbox`, the sandbox merchant ID, merchant key, passphrase, return URL, cancel URL, and an `https` `PAYFAST_NOTIFY_URL`. The API refuses to start if those PayFast or ShipLogic sandbox settings are missing, if simulation stays on, or if `APP_ENV=production`.

ShipLogic rates also need the confirmed collection street address, suburb, city, zone, and postal code, plus the confirmed packed parcel description, length, width, height, and weight. Those fields stay empty until they are confirmed. The product size of 187 × 150 × 41 mm and 2 kg is not sent as the packed parcel. A missing value stops the quote with a message naming the missing field. The checkout does not substitute a simulated price.

PayFast cannot call `http://127.0.0.1`. For the notification, run a tunnel that forwards only to the API and put that public `https` URL, ending in `/api/v1/payments/payfast/itn`, in `PAYFAST_NOTIFY_URL`. Do not commit the URL. If the tunnel connects from this computer, set `PAYFAST_FORWARDED_IP_HEADER` to the header that carries PayFast’s IP, such as `CF-Connecting-IP`. The API still checks that IP against PayFast’s published ranges, checks the signature, and asks the PayFast sandbox to validate the notification. Opening the return page does not mark the order paid.

Shipment booking is not called. The ShipLogic docs describe `POST /shipments`, label download, tracking, and cancellation, but this checkout only requests rates. No shipment, label, or tracking number is created.

The local checkout page is `http://127.0.0.1:8765/checkout.html`. Owner orders are at `http://127.0.0.1:8765/owner/orders.html`.

### Customer order emails

A successful payment queues one confirmation. An owner fulfilment change queues one status email to the address saved on the order. Failed, cancelled, and pending payments do not send a payment confirmation. The order change is saved first. Email delivery runs after that commit, so a mail-server failure does not undo the order.

For local inspection, start Mailpit without touching the database volume:

```
docker compose up -d mailpit
```

Set `EMAIL_TRANSPORT=smtp`, `SMTP_HOST=127.0.0.1`, and `SMTP_PORT=1025` in `backend\.env`, then restart the API. Open captured messages at http://127.0.0.1:8025. Leave `EMAIL_TRANSPORT=capture` when you do not want the API to connect to SMTP. To use Resend instead, set `EMAIL_TRANSPORT=resend`, `RESEND_API_KEY`, and `EMAIL_FROM`, then restart the API. Switch back to Mailpit by setting `EMAIL_TRANSPORT=smtp` again. The Mailpit host settings stay in the file. Production refuses to start when `EMAIL_TRANSPORT=capture`.

A later real provider uses the same queue. Put its SMTP host, port, from address, and credentials in the environment. Do not commit those credentials. Acceptance by SMTP is recorded as accepted, not as a confirmed delivery.

### 5. Start Docker Desktop

Use the steps in section 2 if the whale icon is not running.

### 6. Start PostgreSQL

From `C:\Projects\AutonoVent`:

```powershell
docker compose up -d
```

Check it:

```powershell
docker compose ps
```

You want the service `postgres`, image `postgres:16`, status healthy, and the port shown as `127.0.0.1:5432->5432/tcp`. On this PC the container name is `autonovent-postgres-1`. That name was verified while this guide was written.

`docker compose up -d` starts the existing database. It does not wipe it.

### 7. Create the virtual environment only if it is missing

```powershell
cd C:\Projects\AutonoVent\backend
if (-not (Test-Path .\.venv\Scripts\python.exe)) { python -m venv .venv }
```

You do not have to activate the environment. The commands below call its Python directly. If you prefer a prompt that shows `(.venv)`, run:

```powershell
.\.venv\Scripts\Activate.ps1
```

If Windows blocks that script, you can keep using `.\.venv\Scripts\python.exe` and ignore activation.

### 8. Install the Python packages

From `C:\Projects\AutonoVent\backend`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

That installs the versions pinned in `requirements.txt`, including FastAPI, Uvicorn, SQLAlchemy, Alembic, psycopg, pytest, httpx, and argon2-cffi.

### 9. Apply database migrations

From `C:\Projects\AutonoVent\backend`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Then:

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

While this guide was written, that command printed:

```text
20261015_0003 (head)
```

A later migration can change that revision. `head` means “the newest migration in this folder.”

### 10. Check that the database answers

Start the API with the daily command in section 5, then open:

- `http://127.0.0.1:8001/api/v1/health`
- `http://127.0.0.1:8001/api/v1/health/ready`

Healthy responses, verified on this PC while the API was already running, are:

```json
{"status":"ok","service":"autonovent-api"}
```

```json
{"status":"ok","database":"reachable"}
```

`/api/v1/products` can return `{"products":[]}` when no product is both active and priced. An empty list is a valid catalogue. It is not a database failure.

## 5. Daily startup

You need **two** PowerShell windows, plus Docker Desktop.

### Window A — database

```powershell
cd C:\Projects\AutonoVent
docker compose up -d
docker compose ps
```

If Docker says it cannot connect, start Docker Desktop and wait, then run the same commands again.

### Window B — API

```powershell
cd C:\Projects\AutonoVent\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Leave this window open. It is ready when it says it is running on `http://127.0.0.1:8001`. Stop it later with `Ctrl+C` in this same window.

### Window C — website

Open a third PowerShell window:

```powershell
cd C:\Projects\AutonoVent
python -m http.server 8765 --bind 127.0.0.1
```

Leave this window open too. The command must be run from the project root so `index.html` is the front page. Stop it later with `Ctrl+C`.

### Check the API

In a browser, open:

- `http://127.0.0.1:8001/api/v1/health`
- `http://127.0.0.1:8001/api/v1/health/ready`
- `http://127.0.0.1:8001/api/v1/products`

### Open the site and the owner portal

Use `127.0.0.1` in every address. Do not open the site as `localhost` while the API stays on `127.0.0.1`. Those are different sites for cookies, so owner sign-in would fail even with the right password.

- Public home: `http://127.0.0.1:8765/`
- Public product page: `http://127.0.0.1:8765/product.html`
- Owner sign-in: `http://127.0.0.1:8765/owner/login.html`

After a successful sign-in, the portal opens `http://127.0.0.1:8765/owner/orders.html`. From there you can open Products and Readiness.

Other public pages, if you want them:

- `http://127.0.0.1:8765/how-it-works.html`
- `http://127.0.0.1:8765/installation.html`
- `http://127.0.0.1:8765/faq.html`

## 6. Owner account setup

There is no public registration page. The first owner is created once, from `C:\Projects\AutonoVent\backend`, while PostgreSQL is running:

```powershell
cd C:\Projects\AutonoVent\backend
.\.venv\Scripts\python.exe -m app.admin.bootstrap
```

The command then asks:

1. `Owner email:`
2. `Password:`
3. `Confirm password:`

Type the password at those prompts. Do not put the email or password after the command. If you add any argument, the command refuses to run.

The password must be 12 to 200 characters. The confirmation must match. Nothing in this guide creates an account for you, and writing this guide did not create or change an owner.

The command refuses to run when:

- Any owner row already exists. It prints `An owner account already exists.` Sign in with that account. This command cannot add a second owner.
- `DATABASE_URL` does not point at `127.0.0.1` or `localhost`.
- The API database is not running.

Sign-in still needs the API on port `8001` and the website on port `8765`, both using `127.0.0.1`.

## 7. Connecting DBeaver to PostgreSQL

DBeaver is a separate program. It was **not** opened on this PC while this guide was written, so the click labels below are the usual DBeaver Community Edition labels. If a menu name differs slightly, use the PostgreSQL choice and the host, port, and database below.

PostgreSQL must already be healthy (`docker compose ps`) before you test the connection.

### 1. Open DBeaver

Start **DBeaver** from the Start menu. Community Edition is the free download from https://dbeaver.io/download/.

### 2. Start a new connection

Choose **Database**, then **New Database Connection**. You can also use the plug icon with a plus sign.

### 3. Choose PostgreSQL

Pick **PostgreSQL** and continue.

### 4. Enter the local settings

On the **Main** tab:

| Field | Value |
| --- | --- |
| Host | `127.0.0.1` |
| Port | `5432` |
| Database | `autonovent` |
| Username | The `POSTGRES_USER` value in `C:\Projects\AutonoVent\docker-compose.yml` |
| Password | The `POSTGRES_PASSWORD` value in that same file, or the password inside `DATABASE_URL` in `backend\.env` |

Those two files must agree. Show the password only long enough to type it. Do not save a screenshot of this window.

Leave the connection on this computer. Do not enable SSH unless you are deliberately using a tunnel. This database is already on `127.0.0.1`.

### 5. Download the driver if DBeaver asks

The first PostgreSQL connection often asks to download a driver. Allow that download. It is DBeaver’s Java driver, not a change to AutonoVent.

### 6. Test the connection

Click **Test Connection**. Success means DBeaver could log in and see the server. If it fails, use section 12. Do not create another database to “fix” a refused connection.

### 7. Save and open it

Click **Finish**. Double-click the new connection if it is not already open. A red mark means it is disconnected. A green or normal folder means it is open.

### 8. Find tables and columns

In the tree on the left, expand:

1. Your connection
2. **Databases** → `autonovent`, if that level is shown
3. **Schemas**
4. **public**
5. **Tables**

Click a table, then expand it to see columns. The application tables live in the schema named `public`.

### 9. View rows

Right-click a table and choose **View Data**, or the equivalent **Read data** item. This shows the current rows. Prefer this for looking. Do not use a data grid’s delete button.

### 10. Open an SQL editor

Right-click the connection and choose **SQL Editor** → **New SQL Script**. A new editor tab opens.

### 11. Run a read-only query

Paste one query from the list below. Run it with the execute button or with `Ctrl+Enter`. Run **one** statement at a time until you are comfortable.

These queries only read. Amounts are integer cents. A missing price is an empty `unit_price_cents`, not zero, unless a row was deliberately saved as zero.

Products:

```sql
SELECT id, slug, name, sku, unit_price_cents, currency, active, created_at
FROM public.products
ORDER BY name;
```

Orders:

```sql
SELECT id, order_number, customer_name, customer_email, payment_status, fulfilment_status,
       subtotal_cents, shipping_cents, total_cents, created_at
FROM public.orders
ORDER BY created_at DESC;
```

Order items:

```sql
SELECT order_id, product_name, sku, quantity, unit_price_cents, line_total_cents
FROM public.order_items
ORDER BY order_id;
```

Payments, without the stored provider notification:

```sql
SELECT id, order_id, provider, provider_reference, status, amount_cents, currency, created_at
FROM public.payments
ORDER BY created_at DESC;
```

Leave `notification` out of casual queries. It can hold a provider payload.

Shipments:

```sql
SELECT id, order_id, provider, status, tracking_number, service_code,
       weight_grams, length_mm, width_mm, height_mm, created_at
FROM public.shipments
ORDER BY created_at DESC;
```

Order status history:

```sql
SELECT order_id, field_name, from_status, to_status, actor, created_at
FROM public.order_status_events
ORDER BY created_at;
```

Product audit history:

```sql
SELECT product_id, actor, changes, created_at
FROM public.product_audit_events
ORDER BY created_at;
```

Owner accounts, without the password hash:

```sql
SELECT id, email, role, created_at, disabled_at
FROM public.admin_users
ORDER BY created_at;
```

Do not select `password_hash`. Do not select `token_hash` or `csrf_token_hash` from `public.admin_sessions`. Those columns are secrets or secret stand-ins, even though they are hashes.

### 12. Refresh after a migration

After `alembic upgrade head`, right-click the connection or the `public` schema and choose **Refresh**. DBeaver does not notice new tables until you refresh.

### `public` tables and Alembic’s table

`public` holds both the application and one bookkeeping table:

| Table | Purpose |
| --- | --- |
| `products` | Product records. Price and SKU may be empty. |
| `orders` | Orders. There is no public order form yet, so this may be empty. |
| `order_items` | Copies of product name, SKU, and price at the time of the order. |
| `payments` | Payment rows. Checkout is not enabled. |
| `shipments` | Shipment rows. Live booking is not enabled. |
| `order_status_events` | Payment and fulfilment history for orders. |
| `product_audit_events` | Owner edits to products. |
| `admin_users` | Owner accounts. |
| `admin_sessions` | Hashed sign-in sessions. |
| `auth_login_attempts` | Hashed login-failure records. |
| `alembic_version` | The migration revision only. It is not business data. |

Check the revision in DBeaver with:

```sql
SELECT version_num FROM public.alembic_version;
```

That should match `alembic current` from `backend`. It does not list every migration, only the current one.

## 8. DBeaver safety rules

Looking is safe. Changing is not, unless you meant to change that exact row and you know the effect.

Do not:

- Drop a table, schema, or database.
- Delete rows from the grid.
- Run `DELETE`, `UPDATE`, `INSERT`, or `TRUNCATE` to “tidy up” while browsing.
- Create or alter tables in DBeaver. The next Alembic run will not know about a hand-made change, and the API can break.
- Restore a backup onto `autonovent` to see whether the backup works.
- Turn on a setting that publishes port `5432` beyond this PC. Compose already limits it to `127.0.0.1`.

Use `SELECT` when you only want to inspect data. If a change is deliberate, make it through the owner portal or a migration, then look again with `SELECT`.

## 9. Running automated tests

PostgreSQL must be running. The website and the API window can be closed.

From `C:\Projects\AutonoVent\backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The tests connect to PostgreSQL on `127.0.0.1` and use a database named `autonovent_test`. If that database does not exist, the test setup creates it. They migrate `autonovent_test` and insert rows that are named as fixtures. They do not drop or recreate `autonovent`.

A quiet success ends with a line such as `N passed`. Read the summary at the end of your own run. This guide was not a reason to run the suite again.

A failure prints `FAILED` and a file path such as `tests\test_health.py`. Open that file and read the assertion above the error. Scroll up for the first failure. Fix the cause, then run pytest again. Do not point the tests at a hosted database. They refuse a host that is not `127.0.0.1` or `localhost`.

## 10. Database migrations

A migration is a small Python file in `backend\alembic\versions\`. It changes the database structure: new tables or changed columns. It is how AutonoVent remembers those changes.

From `C:\Projects\AutonoVent\backend`:

Check the revision:

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

Apply migrations that are in the folder but not yet on this database:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Check again:

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

You want the word `(head)` after the revision. Then refresh DBeaver.

Do the schema change in a new migration file, not by editing tables in DBeaver. Hand-edited tables exist only in that one database. Another PC, the test database, and a restore will not have them.

Before a migration that changes or removes real customer data, make a backup first. Section 14 describes that. The migrations in this project so far create structure. They do not seed a price or an owner. Still back up before a change you cannot easily undo.

`alembic.ini` contains a placeholder database URL. Leave it. The command reads the real URL from `backend\.env`.

`20261016_0007` adds nullable terms-acceptance columns on `orders`. Existing orders stay without an acceptance record. Apply it with `alembic upgrade head` from `backend`. It does not delete orders or reset the database volume.

Address search is optional. In `backend\.env`, set `ADDRESS_PROVIDER=google` and `GOOGLE_PLACES_API_KEY` to a Google Places API (New) key restricted to this server. Leave `ADDRESS_PROVIDER` empty until you have that key. The checkout then keeps manual address entry. Do not put the key in a JavaScript file.

## 11. ShipLogic sandbox

The shipping code can request rates from the documented ShipLogic sandbox host only:

`https://api.shiplogic.com`

The path it calls is `POST /rates`. The public documentation says the sandbox uses that host, and that the sandbox account token selects the sandbox. Any other host is rejected. It does not book a shipment.

Settings, all in `backend\.env`:

| Name | Role |
| --- | --- |
| `COURIER_PROVIDER` | `shiplogic` for sandbox checkout. Leave empty while simulated checkout is on. |
| `SHIPLOGIC_MODE` | Must be `sandbox`. |
| `SHIPLOGIC_API_TOKEN` | The bearer token from Integrations > API Keys after registering at https://sandbox.shiplogic.com/register |
| `SHIPLOGIC_SANDBOX_BASE_URL` | Must remain `https://api.shiplogic.com`. |
| `SHIPLOGIC_TIMEOUT_SECONDS` | Request limit. The example file uses `20`. |

Create the token in the ShipLogic sandbox, then paste it only into `backend\.env`. `.env` is listed in `.gitignore`. `.env.example` keeps `SHIPLOGIC_API_TOKEN` empty on purpose.

The automated ShipLogic tests use a fake HTTP response. A passing test does **not** mean a real sandbox call worked.

A real quote is still blocked until all of these exist. Do not invent them.

- A sandbox token in `backend\.env`.
- The collection street address, suburb (`local_area`), city, zone, and postal code. The public name of the collection place is the Rhino Canopies manufacturing warehouse in Pretoria. The street fields are not in the project.
- Packed parcel dimensions and weight. The product’s unit size, 187 × 150 × 41 mm and 2 kg, is **not** a packed parcel and is not sent as one.

The owner readiness page reports whether the provider, sandbox mode, and token are present. It does not show the token, and it does not claim a rate test succeeded. None is recorded by the current code.

Checkout asks ShipLogic for a price only when sandbox checkout is the active mode. Simulated checkout does not.

## 12. Troubleshooting

Try the specific check below. Do not drop `autonovent` or run `docker compose down -v` as a first step. That volume flag deletes the database data.

### Docker Desktop is not running

Start Docker Desktop from the Start menu. Wait until it is idle. Run `docker info`. Then, from `C:\Projects\AutonoVent`, run `docker compose up -d`.

### PostgreSQL does not become healthy

```powershell
cd C:\Projects\AutonoVent
docker compose ps
docker compose logs postgres --tail 50
```

Give it up to a minute on a cold start. The health check uses `pg_isready` against database `autonovent`. If the container is restarting, read the log. Do not delete the volume unless you have a backup and you intend to destroy the data.

### Port 5432 is already in use

```powershell
Get-NetTCPConnection -LocalPort 5432 -State Listen | Select-Object LocalAddress,OwningProcess
```

AutonoVent expects its own PostgreSQL on `127.0.0.1:5432`. If another database already owns that port, `docker compose up -d` cannot publish it. Find out what the other program is before you stop it. Do not change the compose port unless you also change `DATABASE_URL` to the same port.

### Port 8000 is already in use

Leave that program alone. AutonoVent’s API is supposed to use port `8001`. `js\config.js` already points at `http://127.0.0.1:8001`.

### The API does not answer on 8001

Check the API PowerShell window for a red error. Typical causes:

- The command was not run from `C:\Projects\AutonoVent\backend`.
- The virtual environment Python was not used.
- Port `8001` is already taken by an old AutonoVent window. Close that window with `Ctrl+C`, or open `http://127.0.0.1:8001/api/v1/health`. If health already returns JSON, the API is running and you do not need a second copy.

See which process listens:

```powershell
Get-NetTCPConnection -LocalPort 8001 -State Listen | Select-Object OwningProcess
```

Do not stop a process until you know it is the AutonoVent API.

### The website does not answer on 8765

The static server must be started from `C:\Projects\AutonoVent`, not from `backend`:

```powershell
cd C:\Projects\AutonoVent
python -m http.server 8765 --bind 127.0.0.1
```

If port `8765` is taken, an older website window is probably still open. Use that window, or stop it with `Ctrl+C`, then start it again.

### Readiness returns 503

`http://127.0.0.1:8001/api/v1/health` can still say `ok` when the database is down. `/api/v1/health/ready` returns 503 when `DATABASE_URL` is missing or PostgreSQL cannot be reached.

Check `docker compose ps`, then check that `backend\.env` exists and that `DATABASE_URL` uses `127.0.0.1`, port `5432`, and database `autonovent`. Restart the API window after you change `.env`. The message should be generic. It should not print the password.

### `.env` is missing or wrong

If `backend\.env` is missing, copy it once with the command in section 4. If it exists, edit it in place. Do not copy `.env.example` over it if you have already added a sandbox token. A wrong host, port, or database name makes Alembic and the API fail. Compare the user and password with `docker-compose.yml` without pasting them anywhere else.

### Alembic fails

Run it from `backend` with the virtual environment:

```powershell
cd C:\Projects\AutonoVent\backend
.\.venv\Scripts\python.exe -m alembic current
```

If it cannot connect, PostgreSQL is down or `.env` is wrong. If it says a revision is missing, do not edit `alembic_version` in DBeaver. Stop and inspect the files in `backend\alembic\versions` before you change anything.

### DBeaver cannot connect

Confirm `docker compose ps` shows `127.0.0.1:5432` and healthy. In DBeaver use host `127.0.0.1`, port `5432`, database `autonovent`, and the user and password from `docker-compose.yml`. A timeout usually means Docker is stopped. A password error means the two files disagree. Download the driver if DBeaver asks.

### Owner sign-in fails because the host differs

Open the site only as `http://127.0.0.1:8765/owner/login.html`. The API must be `http://127.0.0.1:8001`. Do not mix in `localhost`.

A wrong email or password returns the same message: `The email or password is not correct.` That is deliberate. After too many failures the API asks you to wait. The limit is 5 failures in 15 minutes for that email or that client address.

`APP_ENV` must stay `development` for local HTTP. `production` marks the cookie Secure, and the browser will then ignore it on `http://`.

### Bootstrap refuses to run

| Message | What to do |
| --- | --- |
| `This command does not accept arguments.` | Run it with no email and no password on the command line. |
| `An owner account already exists.` | Use the existing owner. Do not create another with this command. |
| `Refusing to create an owner outside the local database.` | Point `DATABASE_URL` at `127.0.0.1` or `localhost`. |
| `The passwords do not match.` | Type the same password twice. |
| `The password must be 12 to 200 characters.` | Choose a longer password and type it at the prompt. |

### Tests fail because PostgreSQL is unavailable

Start Docker and `docker compose up -d`. Then run pytest again from `backend`. A connection error to port `5432` means the database is down. Do not point `DATABASE_URL` at a remote server to make the tests pass.

### A ShipLogic quote cannot be made

The usual gaps are an empty `SHIPLOGIC_API_TOKEN`, `SHIPLOGIC_MODE` not set to `sandbox`, a missing collection address, or missing packed size and weight. The unit measurements are not a substitute. The readiness page is only a checklist. It does not call ShipLogic. Simulated checkout is a different mode and does not return ShipLogic prices.

## 13. Stopping the project

### Stop the website and the API

Click the PowerShell window that is running the website. Press `Ctrl+C`. Do the same in the API window. That stops those two programs. It does not stop PostgreSQL, and it does not delete data.

Closing the window with the X button also stops that program, but `Ctrl+C` is the clean stop.

### Stop PostgreSQL, and keep the data

From `C:\Projects\AutonoVent`:

```powershell
docker compose stop
```

This stops the `postgres` service. The container and the named volume `autonovent_pg` remain. The next `docker compose up -d` brings the same database back.

`docker compose down` removes the container but, **without** `-v`, still keeps the volume `autonovent_pg`. Prefer `docker compose stop` when you are only finished for the day.

Never run `docker compose down -v` unless you have a backup and you mean to delete the database contents. The `-v` flag removes the volume.

Stopping Docker Desktop also stops the container. Start Docker Desktop and run `docker compose up -d` when you need the database again.

## 14. Backups and recovery

Backups are **not** automatic and they are **not** stored off this PC. A dump can contain customer and order details once those rows exist. Keep it outside Git. The folder `backups\` and files ending in `.dump` are ignored by Git. Do not email a dump.

These commands were checked against `docker-compose.yml`. They use the user inside the container, so you do not put the password on the command line. They were rehearsed earlier against disposable database names, not by restoring over `autonovent`.

From `C:\Projects\AutonoVent`, dump the working database:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T postgres pg_dump -U autonovent -d autonovent --format=custom --no-owner --no-acl --file=/tmp/autonovent.dump
docker compose cp postgres:/tmp/autonovent.dump backups/autonovent.dump
docker compose exec -T postgres rm -f /tmp/autonovent.dump
```

To practise a restore, create a **new** database name and load the dump there. Do not use `autonovent` as the restore target.

```powershell
docker compose exec -T postgres psql -U autonovent -d postgres -c "CREATE DATABASE autonovent_restore"
docker compose cp backups/autonovent.dump postgres:/tmp/autonovent-restore.dump
docker compose exec -T postgres pg_restore -U autonovent -d autonovent_restore --no-owner --no-acl /tmp/autonovent-restore.dump
docker compose exec -T postgres psql -U autonovent -d autonovent_restore -c "SELECT version_num FROM alembic_version"
docker compose exec -T postgres rm -f /tmp/autonovent-restore.dump
```

Compare `version_num` with `alembic current`. In DBeaver you can add a second connection to database `autonovent_restore` and run the same `SELECT` queries. When you are finished with the rehearsal:

```powershell
docker compose exec -T postgres psql -U autonovent -d postgres -c "DROP DATABASE autonovent_restore"
```

If PostgreSQL says the database is in use, disconnect DBeaver from `autonovent_restore` and run the drop again. Do not run `DROP DATABASE autonovent`.

Restrict the `backups` folder to your Windows user. A dump is a full copy of the data.

## 15. GitHub workflow

Do this only when you intend to save or publish work. Checking status does not change the database.

From `C:\Projects\AutonoVent`:

```powershell
git status
```

See what would be committed:

```powershell
git diff
```

When the changes are ones you mean to keep, stage the files by name, then commit. Example:

```powershell
git add path\to\file
git commit -m "Explain why this change exists."
```

Publish the `main` branch:

```powershell
git push origin main
```

`origin` is `https://github.com/benExact/AutonoVent.git`. If Git asks you to sign in, use GitHub’s normal Windows sign-in. Do not paste a token into the project.

Never commit:

- `backend\.env` or any other `.env` file that holds a password or token
- `backend\.venv\`
- `backups\` or a `.dump` file
- A password, session cookie, or ShipLogic token typed into a source file

`.gitignore` already ignores `.env`, `.venv`, `backups\`, and `*.dump`. `git status` should not list those. If it does, do not `git add` them.

Do not force-push `main`.

## Verified while writing this guide

These were checked against this PC and this folder:

- Python 3.14.7, Docker 29.7.2, Docker Compose v5.4.0, and Git 2.54.0.windows.1.
- `backend\.venv` and `backend\.env` exist. The template is `.env.example` in the project root.
- `js\config.js` uses `http://127.0.0.1:8001`.
- PostgreSQL was healthy as `autonovent-postgres-1`, image `postgres:16`, on `127.0.0.1:5432`.
- The API answers on port `8001` for `/api/v1/health`, `/api/v1/health/ready`, and `/api/v1/products`.
- Alembic’s current revision is `20261015_0003` `(head)`.
- The remote URL in `.git\config` is `https://github.com/benExact/AutonoVent.git`, branch `main`.

These were **not** done while writing this guide:

- DBeaver was not opened, so its menu labels were not clicked.
- The test suite was not run again.
- No owner account was created or changed.
- No backup was taken, and nothing was restored.
- Git status, commit, and push were not run.
- The API and PostgreSQL were left running. No application code and no database rows were changed to produce this file.
