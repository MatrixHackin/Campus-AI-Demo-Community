#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import textwrap
from collections import defaultdict
from pathlib import Path

import yaml

DATE_TAG = "20260803"
SOURCE_REGISTRY = "10.120.17.137:5053"
PULL_REGISTRY = "gpunion2.io"
PULL_PROJECT = "library"
PUSH_REF_PREFIX = f"{SOURCE_REGISTRY}/{PULL_PROJECT}"
PULL_REF_PREFIX = f"{PULL_REGISTRY}/{PULL_PROJECT}"
NERDCTL_IMAGE = f"{PULL_REGISTRY}/library/nerdctl:latest"
HOST_CONTAINERD_SOCKET = "/run/k3s/containerd/containerd.sock"
CONTAINERD_SOCKET = "/run/containerd/containerd.sock"
TEMP_SECRET_NAME = "harbor-admin-temp"
HARBOR_USERNAME = os.environ.get("HARBOR_USERNAME", "admin").strip() or "admin"
HARBOR_PASSWORD = os.environ.get("HARBOR_PASSWORD", "")
WORKDIR = Path("/tmp/campus-ai-migration/all-20260803")

TARGET_NODES = [
    "node1",
    "ril-lab-89eace",
    "suscomlab-lhm-1ffbcf",
    "user-c51ab258-887407",
    "lhm-9cf574",
]


def sh(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def kubectl(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return sh(["kubectl", *args], input_text=input_text, check=check)


def get_json(args: list[str]) -> dict:
    return json.loads(kubectl(args).stdout)


def competition_nodes() -> set[str]:
    data = get_json(["get", "nodes", "-l", "competition=true", "-o", "json"])
    return {item["metadata"]["name"] for item in data.get("items", [])}


def running_counts() -> dict[str, int]:
    counts = {node: 0 for node in TARGET_NODES}
    data = get_json(["get", "pods", "-A", "-o", "wide"])
    for item in data.get("items", []):
        node = item.get("spec", {}).get("nodeName")
        if node in counts and item.get("status", {}).get("phase") == "Running":
            counts[node] += 1
    return counts


def choose_target(counts: dict[str, int]) -> str:
    return min(TARGET_NODES, key=lambda n: (counts.get(n, 0), n))


def clean_metadata(meta: dict) -> dict:
    meta = copy.deepcopy(meta)
    for key in [
        "creationTimestamp",
        "generation",
        "managedFields",
        "resourceVersion",
        "uid",
        "selfLink",
    ]:
        meta.pop(key, None)
    return meta


def strip_user_workspace(spec: dict) -> None:
    volumes = spec.get("volumes", [])
    volumes = [v for v in volumes if v.get("name") != "user-workspace"]
    if volumes:
        spec["volumes"] = volumes
    else:
        spec.pop("volumes", None)
    for container in spec.get("containers", []):
        mounts = container.get("volumeMounts", [])
        mounts = [m for m in mounts if m.get("name") != "user-workspace"]
        if mounts:
            container["volumeMounts"] = mounts
        else:
            container.pop("volumeMounts", None)


def append_symlink_prelude(command: list[str]) -> list[str]:
    if len(command) < 3:
        return command
    original = command[2]
    prelude = textwrap.dedent(
        """
        set -e
        rm -rf /mydata
        ln -s /campus-ai-migrated-mydata /mydata
        chown -h "$USERNAME:$USERNAME" /mydata 2>/dev/null || true
        chown -R "$USERNAME:$USERNAME" /campus-ai-migrated-mydata 2>/dev/null || true
        """
    ).strip()
    return [command[0], command[1], f"{prelude}\n{original}"]


def build_actual_manifest(pod: dict, *, target_node: str, image: str) -> dict:
    manifest = copy.deepcopy(pod)
    manifest["metadata"] = clean_metadata(manifest["metadata"])
    manifest.pop("status", None)
    manifest["metadata"].setdefault("annotations", {})
    manifest["metadata"]["annotations"]["campus-ai/image"] = image
    manifest["metadata"]["annotations"]["campus-ai/migration"] = "longhorn-to-image"
    spec = manifest["spec"]
    spec["nodeName"] = target_node
    spec.pop("nodeSelector", None)
    spec.pop("affinity", None)
    container = spec["containers"][0]
    container["image"] = image
    container["command"] = append_symlink_prelude(container.get("command", []))
    strip_user_workspace(spec)
    return manifest


def build_canary_manifest(actual_manifest: dict, *, canary_name: str) -> dict:
    manifest = copy.deepcopy(actual_manifest)
    manifest["metadata"]["name"] = canary_name
    labels = dict(manifest["metadata"].get("labels", {}))
    labels.pop("campus-ai/app-name", None)
    labels["campus-ai/migration-canary"] = "true"
    manifest["metadata"]["labels"] = labels
    manifest["metadata"]["annotations"] = dict(manifest["metadata"].get("annotations", {}))
    manifest["metadata"]["annotations"]["campus-ai/migration"] = "longhorn-to-image-canary"
    return manifest


def dump_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(manifest, fh, sort_keys=False)


def pod_json(ns: str, pod: str) -> dict:
    return get_json(["get", "pod", pod, "-n", ns, "-o", "json"])


def kill_non_base_processes(ns: str, pod: str) -> None:
    script = r"""
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  comm=$(cat "$d/comm" 2>/dev/null || true)
  cmd=$(tr "\0" " " < "$d/cmdline" 2>/dev/null || true)
  [ -n "$cmd" ] || continue
  case "$pid:$comm" in
    1:*|*:sh|*:bash|*:sleep|*:sshd|*:ps|*:sed|*:cat|*:tr|*:readlink|*:find|*:du|*:wc|*:cp|*:mv|*:rm|*:mkdir|*:sort|*:comm|*:cut|*:test|*:date)
      continue
      ;;
  esac
  case "$cmd" in
    *"/usr/sbin/sshd -D -e"*|"sleep infinity")
      continue
      ;;
  esac
  kill "$pid" 2>/dev/null || true
done
sleep 2
"""
    kubectl(["-n", ns, "exec", pod, "--", "sh", "-lc", script])


def copy_mydata_into_layer(ns: str, pod: str) -> None:
    script = r"""
set -eu
rm -rf /campus-ai-migrated-mydata /campus-ai-migrated-mydata.tmp
mkdir -p /campus-ai-migrated-mydata.tmp
cp -a /mydata/. /campus-ai-migrated-mydata.tmp/
cd /mydata
find . -xdev -type f -printf '%P\t%s\n' | sort > /tmp/campus-ai-src-files.list
cd /campus-ai-migrated-mydata.tmp
find . -xdev -type f -printf '%P\t%s\n' | sort > /tmp/campus-ai-dst-files.list
diff_count=$(comm -3 /tmp/campus-ai-src-files.list /tmp/campus-ai-dst-files.list | wc -l)
test "$diff_count" = 0
mv /campus-ai-migrated-mydata.tmp /campus-ai-migrated-mydata
find /campus-ai-migrated-mydata -xdev -type f | wc -l
du -sh /campus-ai-migrated-mydata
"""
    kubectl(["-n", ns, "exec", pod, "--", "sh", "-lc", script])


def ensure_temp_secret(ns: str) -> None:
    rendered = sh(
        [
            "kubectl",
            "-n",
            ns,
            "create",
            "secret",
            "generic",
            TEMP_SECRET_NAME,
            f"--from-literal=username={HARBOR_USERNAME}",
            f"--from-literal=password={HARBOR_PASSWORD}",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        check=True,
    ).stdout
    kubectl(["apply", "-f", "-"], input_text=rendered)


def delete_temp_secret(ns: str) -> None:
    kubectl(["-n", ns, "delete", "secret", TEMP_SECRET_NAME, "--ignore-not-found=true"], check=False)


def commit_image(ns: str, pod: str, source_node: str, image: str) -> None:
    cid = kubectl(
        ["-n", ns, "get", "pod", pod, "-o", "jsonpath={.status.containerStatuses[0].containerID}"]
    ).stdout.strip().removeprefix("containerd://")
    job = f"commit-{pod}-{DATE_TAG}"
    kubectl(["-n", ns, "delete", "job", job, "--ignore-not-found=true", "--wait=true"], check=False)
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job,
            "namespace": ns,
            "labels": {
                "app.kubernetes.io/managed-by": "campus-ai",
                "campus-ai/commit-job": "true",
                "campus-ai/migration": "longhorn-to-image",
                "campus-ai/source-pod": pod,
            },
        },
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/managed-by": "campus-ai",
                        "campus-ai/commit-job": "true",
                        "campus-ai/migration": "longhorn-to-image",
                        "campus-ai/source-pod": pod,
                    }
                },
                "spec": {
                    "nodeName": source_node,
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "commit-runner",
                            "image": NERDCTL_IMAGE,
                            "imagePullPolicy": "IfNotPresent",
                            "securityContext": {"privileged": True},
                            "command": [
                                "/bin/sh",
                                "-lc",
                                textwrap.dedent(
                                    f"""
                                    set -eu
                                    NERDCTL="nerdctl --address {CONTAINERD_SOCKET} --namespace k8s.io"
                                    printf "%s\\n" "$HARBOR_PASSWORD" | $NERDCTL login -u "$HARBOR_USERNAME" --password-stdin {SOURCE_REGISTRY} --insecure-registry
                                    $NERDCTL commit --insecure-registry "{cid}" "{image}"
                                    $NERDCTL push --insecure-registry "{image}"
                                    """
                                ).strip(),
                            ],
                            "env": [
                                {
                                    "name": "HARBOR_USERNAME",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": TEMP_SECRET_NAME,
                                            "key": "username",
                                        }
                                    },
                                },
                                {
                                    "name": "HARBOR_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": TEMP_SECRET_NAME,
                                            "key": "password",
                                        }
                                    },
                                },
                            ],
                            "volumeMounts": [
                                {
                                    "name": "containerd-sock",
                                    "mountPath": CONTAINERD_SOCKET,
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "containerd-sock",
                            "hostPath": {
                                "path": HOST_CONTAINERD_SOCKET,
                                "type": "Socket",
                            },
                        }
                    ],
                },
            },
        },
    }
    dump_manifest(WORKDIR / f"{job}.yaml", manifest)
    kubectl(["-n", ns, "apply", "-f", str(WORKDIR / f"{job}.yaml")])
    kubectl(["-n", ns, "wait", "--for=condition=complete", f"job/{job}", "--timeout=1800s"])
    logs = kubectl(["-n", ns, "logs", f"job/{job}", "--tail=40"], check=False).stdout
    if logs:
        print(logs, end="" if logs.endswith("\n") else "\n")


def wait_ready(ns: str, pod: str, timeout: str = "300s") -> None:
    kubectl(["-n", ns, "wait", "--for=condition=Ready", f"pod/{pod}", f"--timeout={timeout}"])


def verify_running(ns: str, pod: str) -> None:
    script = r"""
echo POD=$(hostname)
echo ---
ps -ef
echo ---
test -L /mydata && readlink /mydata
echo ---
pgrep -af "sshd|sleep" || true
echo ---
find /campus-ai-migrated-mydata -xdev -type f | wc -l
"""
    out = kubectl(["-n", ns, "exec", pod, "--", "sh", "-lc", script]).stdout
    print(out, end="" if out.endswith("\n") else "\n")


def apply_pod(ns: str, manifest: dict, filename: str) -> None:
    path = WORKDIR / filename
    dump_manifest(path, manifest)
    kubectl(["apply", "-f", str(path)])


def migrate_one(ns: str, pod: str, target_node: str) -> None:
    pod_obj = pod_json(ns, pod)
    labels = pod_obj["metadata"].get("labels", {})
    annotations = pod_obj["metadata"].get("annotations", {})
    app = labels["campus-ai/app-name"]
    image = f"{PULL_REF_PREFIX}/{ns}-{app}-migrated-{DATE_TAG}:latest"
    source_node = pod_obj["spec"]["nodeName"]
    print(f"\n=== migrate {ns}/{pod} {source_node} -> {target_node} ===")

    kill_non_base_processes(ns, pod)
    copy_mydata_into_layer(ns, pod)
    ensure_temp_secret(ns)
    try:
        commit_image(ns, pod, source_node, image)

        actual = build_actual_manifest(pod_obj, target_node=target_node, image=image)
        canary_name = f"{pod}-canary"
        canary = build_canary_manifest(actual, canary_name=canary_name)
        apply_pod(ns, canary, f"canary-{ns}-{pod}.yaml")
        wait_ready(ns, canary_name)
        verify_running(ns, canary_name)
        kubectl(["-n", ns, "delete", "pod", canary_name, "--wait=true"], check=False)

        kubectl(["-n", ns, "delete", "pod", pod, "--wait=true"])
        apply_pod(ns, actual, f"actual-{ns}-{pod}.yaml")
        wait_ready(ns, pod)
        verify_running(ns, pod)
        endpoints = kubectl(["-n", ns, "get", "endpoints", f"{app}-svc", f"{app}-ssh-svc", "-o", "wide"], check=False).stdout
        if endpoints:
            print(endpoints, end="" if endpoints.endswith("\n") else "\n")
    except Exception:
        print(f"[rollback] {ns}/{pod} migration failed; restoring original pod on {source_node}")
        try:
            kubectl(["-n", ns, "delete", "pod", pod, "--ignore-not-found=true", "--wait=true"], check=False)
            kubectl(["-n", ns, "delete", "pod", f"{pod}-canary", "--ignore-not-found=true", "--wait=true"], check=False)
        except Exception:
            pass
        restored = copy.deepcopy(pod_obj)
        restored["metadata"] = clean_metadata(restored["metadata"])
        restored.pop("status", None)
        restored["spec"]["nodeName"] = source_node
        restored["spec"].pop("nodeSelector", None)
        restored["spec"].pop("affinity", None)
        strip_user_workspace(restored["spec"])
        apply_pod(ns, restored, f"rollback-{ns}-{pod}.yaml")
        wait_ready(ns, pod)
        raise
    finally:
        delete_temp_secret(ns)


def namespace_has_workspace_mount(ns: str) -> bool:
    data = get_json(["get", "pods", "-n", ns, "-l", "app=campus-ai-devbox", "-o", "json"])
    for item in data.get("items", []):
        spec = item.get("spec", {})
        for container in spec.get("containers", []):
            for mount in container.get("volumeMounts", []):
                if mount.get("name") == "user-workspace":
                    return True
    return False


def delete_namespace_pvc(ns: str) -> None:
    if namespace_has_workspace_mount(ns):
        print(f"[skip pvc] {ns} still has user-workspace mounts")
        return
    print(f"[pvc delete] {ns}/user-workspace")
    kubectl(["-n", ns, "delete", "pvc", "user-workspace", "--wait=true"], check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--namespace",
        action="append",
        dest="namespaces",
        help="only migrate devbox pods in the selected namespace(s); repeatable",
    )
    parser.add_argument(
        "--pod",
        action="append",
        dest="pods",
        help="only migrate the selected pod name(s); repeatable",
    )
    parser.add_argument(
        "--delete-pvc",
        action="store_true",
        help="delete namespace user-workspace PVCs after migration when no mounts remain",
    )
    args = parser.parse_args()

    if not HARBOR_PASSWORD:
        parser.error("HARBOR_PASSWORD environment variable is required")

    WORKDIR.mkdir(parents=True, exist_ok=True)
    comp_nodes = competition_nodes()
    data = get_json(["get", "pods", "-A", "-l", "app=campus-ai-devbox", "-o", "json"])
    pods_by_ns: dict[str, list[dict]] = defaultdict(list)
    all_namespaces: set[str] = set()
    for item in data.get("items", []):
        ns = item["metadata"]["namespace"]
        all_namespaces.add(ns)
        node = item.get("spec", {}).get("nodeName")
        if node in comp_nodes:
            pods_by_ns[ns].append(item)

    if args.namespaces:
        wanted = set(args.namespaces)
        pods_by_ns = {ns: pods for ns, pods in pods_by_ns.items() if ns in wanted}
        all_namespaces = {ns for ns in all_namespaces if ns in wanted}
    if args.pods:
        wanted_pods = set(args.pods)
        pods_by_ns = {
            ns: [item for item in pods if item["metadata"]["name"] in wanted_pods]
            for ns, pods in pods_by_ns.items()
        }
        pods_by_ns = {ns: pods for ns, pods in pods_by_ns.items() if pods}
        all_namespaces = {ns for ns, pods in pods_by_ns.items() if pods}

    counts = running_counts()
    print("[target counts before]", counts)
    migration_order = []
    for ns in sorted(pods_by_ns):
        for item in sorted(pods_by_ns[ns], key=lambda x: x["metadata"]["name"]):
            migration_order.append((ns, item["metadata"]["name"]))

    print("[migration order]")
    for ns, pod in migration_order:
        print(f"  {ns}/{pod}")

    for ns in sorted(pods_by_ns):
        ns_pods = sorted(pods_by_ns[ns], key=lambda x: x["metadata"]["name"])
        print(f"\n### namespace {ns}: {len(ns_pods)} pods")
        for item in ns_pods:
            pod = item["metadata"]["name"]
            target = choose_target(counts)
            counts[target] += 1
            migrate_one(ns, pod, target)
        if args.delete_pvc:
            delete_namespace_pvc(ns)

    if args.delete_pvc:
        for ns in sorted(all_namespaces):
            if not namespace_has_workspace_mount(ns):
                delete_namespace_pvc(ns)

    print("\nall competition devbox pods migrated; eligible PVCs deleted")


if __name__ == "__main__":
    main()
