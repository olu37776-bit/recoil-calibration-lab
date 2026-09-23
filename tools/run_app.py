from multiprocessing import freeze_support
from recoil_lab.app import main

if __name__ == '__main__':
    freeze_support()
    raise SystemExit(main())
