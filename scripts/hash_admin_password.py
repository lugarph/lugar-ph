"""Print a salted password hash for ROUTE_ADMIN_PASSWORD_HASH."""

from getpass import getpass
from hashlib import pbkdf2_hmac
from secrets import token_bytes


def main() -> None:
    password = getpass("New route reviewer password: ")
    confirm = getpass("Confirm password: ")
    if password != confirm or len(password) < 16:
        raise SystemExit("Passwords must match and have at least 16 characters")
    salt = token_bytes(16)
    rounds = 600_000
    digest = pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    print(f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}")


if __name__ == "__main__":
    main()
