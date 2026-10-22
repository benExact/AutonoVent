"""Runtime settings. Credentials come from the environment only."""

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shipping.simulated import SimulatedConfigurationError, parse_region_extras, parse_simulation_rates


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    cors_origins: str = "http://127.0.0.1:8765,http://localhost:8765"
    shiplogic_mode: str = ""
    shiplogic_api_token: str = ""
    shiplogic_sandbox_base_url: str = "https://api.shiplogic.com"
    shiplogic_timeout_seconds: float = 20
    auth_session_ttl_seconds: int = 43200
    auth_session_idle_seconds: int = 7200
    auth_login_max_failures: int = 5
    auth_login_window_seconds: int = 900
    checkout_simulation_enabled: bool = False
    checkout_simulation_rates: str = ""
    checkout_simulation_region_extras: str = ""
    checkout_simulation_demo_unit_price_cents: int | None = None
    email_transport: str = "capture"
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    email_from: str = "Autonovent <orders@localhost>"
    resend_api_key: str = ""
    email_logo_url: str = ""
    email_max_attempts: int = 5
    address_provider: str = ""
    google_places_api_key: str = ""
    product_image_dir: str = "var/product-images"
    courier_provider: str = ""
    payment_provider: str = ""
    payfast_mode: str = ""
    payfast_merchant_id: str = ""
    payfast_merchant_key: str = ""
    payfast_passphrase: str = ""
    payfast_notify_url: str = ""
    payfast_return_url: str = ""
    payfast_cancel_url: str = ""
    payfast_forwarded_ip_header: str = ""
    payfast_itn_proxy_token: str = ""
    collection_company: str = ""
    collection_street_address: str = ""
    collection_local_area: str = ""
    collection_city: str = ""
    collection_zone: str = ""
    collection_postal_code: str = ""
    packed_parcel_description: str = ""
    packed_parcel_length_mm: int | None = None
    packed_parcel_width_mm: int | None = None
    packed_parcel_height_mm: int | None = None
    packed_parcel_weight_grams: int | None = None

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origins(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("Wildcard CORS is not allowed.")
        return ",".join(origins)

    @field_validator("shiplogic_sandbox_base_url")
    @classmethod
    def sandbox_shiplogic_only(cls, value: str) -> str:
        normalized = value.strip().rstrip("/") or "https://api.shiplogic.com"
        if normalized != "https://api.shiplogic.com":
            raise ValueError("ShipLogic sandbox requests must use https://api.shiplogic.com.")
        return normalized

    @field_validator("shiplogic_timeout_seconds")
    @classmethod
    def positive_shiplogic_timeout(cls, value: float) -> float:
        if value <= 0 or value > 60:
            raise ValueError("ShipLogic timeout must be greater than 0 and at most 60 seconds.")
        return value

    @field_validator("auth_session_ttl_seconds", "auth_session_idle_seconds", "auth_login_window_seconds")
    @classmethod
    def positive_auth_window(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Authentication time limits must be positive.")
        return value

    @field_validator("email_transport", mode="before")
    @classmethod
    def blank_email_transport(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return "capture"
        return value

    @field_validator("checkout_simulation_demo_unit_price_cents", "packed_parcel_length_mm", "packed_parcel_width_mm", "packed_parcel_height_mm", "packed_parcel_weight_grams", mode="before")
    @classmethod
    def blank_optional_number(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("auth_login_max_failures")
    @classmethod
    def positive_login_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("The login attempt limit must be at least 1.")
        return value

    def origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @model_validator(mode="after")
    def simulation_is_development_only(self) -> "Settings":
        env = self.app_env.strip().lower()
        if not env:
            raise ValueError("APP_ENV is not configured.")
        if env not in {"development", "production"}:
            raise ValueError("APP_ENV must be development or production.")
        self.app_env = env
        if env == "production" and self.checkout_simulation_enabled:
            raise ValueError("Checkout simulation cannot be enabled when APP_ENV is production.")
        if self.checkout_simulation_enabled and env != "development":
            raise ValueError("Checkout simulation can only be enabled when APP_ENV is development.")
        demo_price = self.checkout_simulation_demo_unit_price_cents
        if demo_price is not None and demo_price < 0:
            raise ValueError("The demo product price cannot be negative.")
        if env == "production" and demo_price is not None:
            raise ValueError("A demo product price cannot be configured when APP_ENV is production.")
        courier = self.courier_provider.strip().lower()
        payment = self.payment_provider.strip().lower()
        if courier not in {"", "simulated", "shiplogic"}:
            raise ValueError("COURIER_PROVIDER must be empty, simulated, or shiplogic.")
        if payment not in {"", "simulated", "payfast"}:
            raise ValueError("PAYMENT_PROVIDER must be empty, simulated, or payfast.")
        mode = self.payfast_mode.strip().lower()
        if mode not in {"", "sandbox"}:
            raise ValueError("PAYFAST_MODE must be empty or sandbox. Live PayFast is disabled.")
        courier_mode = self.shiplogic_mode.strip().lower()
        if courier_mode not in {"", "sandbox"}:
            raise ValueError("SHIPLOGIC_MODE must be empty or sandbox. Live ShipLogic is disabled.")
        self.courier_provider = courier
        self.payment_provider = payment
        self.payfast_mode = mode
        self.shiplogic_mode = courier_mode
        if courier == "shiplogic" or payment == "payfast":
            if self.checkout_simulation_enabled:
                raise ValueError("Turn CHECKOUT_SIMULATION_ENABLED off before selecting the ShipLogic and PayFast sandbox.")
            if courier != "shiplogic" or payment != "payfast":
                raise ValueError("Sandbox checkout needs COURIER_PROVIDER=shiplogic and PAYMENT_PROVIDER=payfast together.")
            if env == "production":
                raise ValueError("Sandbox checkout cannot run when APP_ENV is production.")
            if courier_mode != "sandbox":
                raise ValueError("ShipLogic sandbox mode must be set to sandbox.")
            if mode != "sandbox":
                raise ValueError("PayFast sandbox mode must be set to sandbox.")
            if not self.shiplogic_api_token.strip():
                raise ValueError("ShipLogic sandbox checkout needs SHIPLOGIC_API_TOKEN.")
        elif courier == "simulated" or payment == "simulated":
            if courier != "simulated" or payment != "simulated":
                raise ValueError("Simulated checkout needs both the simulated courier and the simulated payment.")
            if not self.checkout_simulation_enabled:
                raise ValueError("Simulated providers require CHECKOUT_SIMULATION_ENABLED=true.")
        if env == "production" and mode == "sandbox":
            raise ValueError("PayFast sandbox settings cannot be used when APP_ENV is production.")
        if demo_price is not None and not (self.checkout_simulation_enabled or (courier == "shiplogic" and payment == "payfast")):
            raise ValueError("A demo product price requires development checkout to be enabled.")
        for label, value in (
            ("packed parcel length", self.packed_parcel_length_mm),
            ("packed parcel width", self.packed_parcel_width_mm),
            ("packed parcel height", self.packed_parcel_height_mm),
            ("packed parcel weight", self.packed_parcel_weight_grams),
        ):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
                raise ValueError(f"The {label} must be a positive whole number.")
        if self.checkout_simulation_enabled:
            try:
                rates = parse_simulation_rates(self.checkout_simulation_rates)
                parse_region_extras(self.checkout_simulation_region_extras)
            except SimulatedConfigurationError as exc:
                raise ValueError(str(exc)) from None
            if not rates:
                raise ValueError("Simulated delivery rates are not configured.")
        transport = self.email_transport.strip().lower()
        if transport not in {"capture", "smtp", "resend"}:
            raise ValueError("EMAIL_TRANSPORT must be capture, smtp, or resend.")
        self.email_transport = transport
        if env == "production" and transport == "capture":
            raise ValueError("Production email must use the smtp or resend transport.")
        if transport == "smtp" and (not self.smtp_host.strip() or not self.email_from.strip()):
            raise ValueError("SMTP email needs SMTP_HOST and EMAIL_FROM.")
        if transport == "resend" and (not self.resend_api_key.strip() or not self.email_from.strip()):
            raise ValueError("Resend email needs RESEND_API_KEY and EMAIL_FROM.")
        if self.email_max_attempts < 1:
            raise ValueError("EMAIL_MAX_ATTEMPTS must be at least 1.")
        provider = self.address_provider.strip().lower()
        if provider not in {"", "google"}:
            raise ValueError("ADDRESS_PROVIDER must be empty or google.")
        self.address_provider = provider
        if provider == "google" and not self.google_places_api_key.strip():
            raise ValueError("Google address search needs GOOGLE_PLACES_API_KEY.")
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production"

    @property
    def checkout_simulation_active(self) -> bool:
        return self.app_env == "development" and self.checkout_simulation_enabled

    @property
    def checkout_mode(self) -> str:
        courier = self.courier_provider or ("simulated" if self.checkout_simulation_active else "")
        payment = self.payment_provider or ("simulated" if self.checkout_simulation_active else "")
        if courier == "simulated" and payment == "simulated" and self.checkout_simulation_active:
            return "simulation"
        if courier == "shiplogic" and payment == "payfast" and self.payfast_mode == "sandbox" and self.shiplogic_mode == "sandbox":
            return "sandbox"
        return "unavailable"


@lru_cache
def get_settings() -> Settings:
    return Settings()
