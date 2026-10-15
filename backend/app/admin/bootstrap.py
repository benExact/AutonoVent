"""Create the first owner. Run from backend: python -m app.admin.bootstrap"""

import sys
from getpass import getpass

from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.auth.service import OwnerExistsError, OwnerProvisioningError, create_initial_owner
from app.core.config import get_settings
from app.db.session import get_engine


def main(read_email=input, read_password=getpass) -> int:
    if len(sys.argv) > 1:
        print("This command does not accept arguments.", file=sys.stderr)
        return 2
    settings = get_settings()
    host = make_url(settings.database_url).host if settings.database_url else None
    if host not in {"127.0.0.1", "localhost"}:
        print("Refusing to create an owner outside the local database.", file=sys.stderr)
        return 2
    email = read_email("Owner email: ")
    password = read_password("Password: ")
    confirmation = read_password("Confirm password: ")
    if password != confirmation:
        print("The passwords do not match.", file=sys.stderr)
        return 2
    with Session(get_engine(), expire_on_commit=False) as session:
        try:
            create_initial_owner(session, email, password)
        except OwnerExistsError:
            print("An owner account already exists.", file=sys.stderr)
            return 1
        except OwnerProvisioningError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    print("Owner account created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
