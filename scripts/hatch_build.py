"""Keep local ignore configuration out of source distributions."""

from pathlib import PurePosixPath

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

IGNORED_NAMES = frozenset({".gitignore", ".dockerignore", ".rgignore"})


class SourceDistributionHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "sdist":
            return
        forced = build_data["force_include"]
        for source, destination in list(forced.items()):
            names = {PurePosixPath(str(path).replace("\\", "/")).name.casefold() for path in (source, destination)}
            if names & IGNORED_NAMES:
                del forced[source]
