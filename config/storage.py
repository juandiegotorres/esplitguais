from whitenoise.storage import CompressedManifestStaticFilesStorage


class StaticStorage(CompressedManifestStaticFilesStorage):
    """Hashed static names in production; unhashed fallback when no manifest exists (tests, dev)."""

    manifest_strict = False
