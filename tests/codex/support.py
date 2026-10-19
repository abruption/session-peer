"""Shared deterministic identifiers and isolation for Codex test fixtures."""
import os
from unittest import mock

THREAD = "01900000-0000-7000-8000-000000000001"
OTHER = "01900000-0000-7000-8000-000000000002"


def isolate_native_layers(case, project_root=None):
    """Keep machine-wide and ancestor Codex configuration out of a fixture.

    System, requirements and macOS managed-profile layers are emptied; project
    layers are limited to paths inside `project_root` (none when omitted), so
    offline results never depend on the developer's real configuration.
    """
    import session_peer as peer
    real_project_paths = peer.codex_project_config_paths
    real_project_paths_from = peer._codex_project_config_paths_from
    base = None if project_root is None else os.path.abspath(project_root)

    def contained(cwd, **kwargs):
        if base is None:
            return []
        return [path for path in real_project_paths(cwd, **kwargs)
                if os.path.abspath(path).startswith(base + os.sep)]

    def contained_from(cwd, **kwargs):
        # Existing consumers also inspect a distinct lexical spelling through
        # this private helper; isolating only the public physical path misses it.
        if base is None:
            return []
        return [path for path in real_project_paths_from(cwd, **kwargs)
                if os.path.abspath(path).startswith(base + os.sep)]

    for patcher in (mock.patch.object(peer, "codex_system_config_paths", return_value=[]),
                    mock.patch.object(peer, "codex_queue_preference_policy", return_value=False),
                    mock.patch.object(peer, "codex_managed_preference_values", return_value=[]),
                    mock.patch.object(peer, "codex_project_config_paths", side_effect=contained),
                    mock.patch.object(peer, "_codex_project_config_paths_from", side_effect=contained_from)):
        patcher.start()
        case.addCleanup(patcher.stop)
