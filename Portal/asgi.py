import os
import sys
from pathlib import Path
from django.core.asgi import get_asgi_application


BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Portal.settings")

application = get_asgi_application()

