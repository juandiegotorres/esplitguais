from whitenoise.storage import CompressedManifestStaticFilesStorage


class StaticStorage(CompressedManifestStaticFilesStorage):
    """Hashed static names in production; unhashed names when no manifest exists (tests, dev)."""

    manifest_strict = False

    def stored_name(self, name):
        if not self.hashed_files:  # sin manifest: collectstatic no corrió (tests, dev)
            return name
        return super().stored_name(name)
