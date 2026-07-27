from lib.app_profile import ENTRY_PROFILE
from main import runApplication


def main() -> int:
    return runApplication(ENTRY_PROFILE)


if __name__ == "__main__":
    raise SystemExit(main())
