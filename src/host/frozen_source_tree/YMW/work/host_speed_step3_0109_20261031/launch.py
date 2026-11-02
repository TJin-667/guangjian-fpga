"""Separate desktop entry; check-only and opening the UI never contact hardware."""
import bootstrap
import sys
if __name__ == '__main__':
    bootstrap.verify()
    from speed_app import main
    main()
