# Set broker test env before any test module imports broker.app (so init_db/migrate_db use temp DB and tokens)
import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["BROKER_DB"] = _tmp.name
os.environ["WORKER_TOKEN"] = "test-worker-token"
os.environ["BOT_TOKEN"] = "test-bot-token"
