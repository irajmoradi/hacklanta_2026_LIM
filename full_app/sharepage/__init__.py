"""Public montage links. Register create_blueprint(store) in the host app."""
from .store import EMOJIS, ShareStore
from .routes import create_blueprint

__all__ = ["ShareStore", "create_blueprint", "EMOJIS"]
