from subprocess import CompletedProcess

from models import ModuleConfig, WorkspaceManifest


def module(module_id: str, path: str, kind: str) -> ModuleConfig:
    return ModuleConfig(module_id=module_id, path=path, kind=kind)


def manifest_object(modules: list[ModuleConfig]) -> WorkspaceManifest:
    return WorkspaceManifest(
        system="SHOP", workspace_root=".", load_test_module="load-tests",
        modules=tuple(modules), allowed_modules=("load-tests",),
    )


def completed_git_outputs(*, head: str, branch: str, status: str, remote: str):
    return [
        CompletedProcess(["git"], 0, head, ""),
        CompletedProcess(["git"], 0, branch, ""),
        CompletedProcess(["git"], 0, status, ""),
        CompletedProcess(["git"], 0, remote, ""),
    ]
