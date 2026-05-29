import sys


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        from v3.runtime_selftest import main as self_test_main

        args = [arg for arg in sys.argv[1:] if arg != "--self-test"]
        raise SystemExit(self_test_main(args))

    from v3.gui_v3 import main

    main()
