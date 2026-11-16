"""Load a script from a skill folder (the folder names have hyphens)."""

import importlib.util
import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")

# The tests never see a real Fyers login: fyers.py keeps its token and request
# count in this empty folder, so the default --source auto always means Yahoo
# here, and no test can reach Fyers with the user's token.
TEST_HOME = tempfile.mkdtemp(prefix="dti-test-home-")
os.environ["DAY_TRADER_INDIA_HOME"] = TEST_HOME
for _k in ("FYERS_APP_ID", "FYERS_SECRET_ID", "FYERS_REDIRECT_URI"):
    os.environ.pop(_k, None)


def load(folder, name):
    path = os.path.join(ROOT, folder, name + ".py")
    spec = importlib.util.spec_from_file_location("trader_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
