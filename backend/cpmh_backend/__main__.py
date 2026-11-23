import sys

if len(sys.argv) > 1 and sys.argv[1] == "vpn":
    from cpmh_backend.vpn import _cli

    raise SystemExit(_cli(sys.argv[2:]))

from cpmh_backend.main import main

if __name__ == "__main__":
    main()
