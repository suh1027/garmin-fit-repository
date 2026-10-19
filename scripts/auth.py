#!/usr/bin/env python3
"""Interactive Garmin login; session tokens remain outside the Git repository."""
from getpass import getpass
from pathlib import Path
import os
from garminconnect import Garmin


def main():
    tokenstore = Path(os.getenv('GARMIN_TOKEN_DIR', '~/.garminconnect')).expanduser()
    tokenstore.mkdir(parents=True, exist_ok=True, mode=0o700)
    tokenstore.chmod(0o700)
    username = input('Garmin Connect email: ').strip()
    password = getpass('Garmin Connect password: ')
    client = Garmin(username, password, prompt_mfa=lambda: input('MFA code: ').strip())
    client.login(str(tokenstore))
    print(f'Authenticated. Session stored outside Git: {tokenstore}')


if __name__ == '__main__':
    main()
