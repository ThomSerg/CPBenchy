import sys

from cpbenchy.worker.runtime import main

sys.exit(main(sys.argv[1:], standalone=True))
