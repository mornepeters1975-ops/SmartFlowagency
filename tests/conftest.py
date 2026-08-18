"""(Re)generates the synthetic fixture files before the test session runs.

The fixtures are xlsx/csv binaries — deterministic, cheap to build, and not
worth committing to git. tests/fixtures/make_fixtures.py is the source of
truth; this just calls it once per test session.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixtures  # noqa: E402


def pytest_configure(config):
    make_fixtures.main()
