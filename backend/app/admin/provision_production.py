"""Create the first production owner. Run inside the API container: python -m app.admin.provision_production"""

import sys
from getpass import getpass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.service import OwnerExistsError, OwnerProvisioningError, create_initial_owner
from app.core.config import get_settings
from app.db.session import get_engine


def main(read_email=input, read_password=getpass) -> int:
    if len(sys.argv) > 1:
        print("This command does not accept arguments.", file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.app_env != "production":
        print("Refusing to create an owner unless APP_ENV is production.", file=sys.stderr)
        return 2
    if not settings.database_url.strip():
        print("DATABASE_URL is not configured.", file=sys.stderr)
        return 2
    email = read_email("Owner email: ")
    password = read_password("Password: ")
    confirmation = read_password("Confirm password: ")
    if password != confirmation:
        print("The passwords do not match.", file=sys.stderr)
        return 2
    try:
        with Session(get_engine(), expire_on_commit=False) as session:
            try:
                create_initial_owner(session, email, password)
            except OwnerExistsError:
                print("An owner account already exists.", file=sys.stderr)
                return 1
            except OwnerProvisioningError as exc:
                print(str(exc), file=sys.stderr)
                return 2
    except SQLAlchemyError:
        print("The database could not be reached.", file=sys.stderr)
        return 2
    print("Owner account created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
