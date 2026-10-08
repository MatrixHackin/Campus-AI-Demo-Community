from __future__ import annotations

import logging
import re
import shlex
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.runtime_image_builder import DockerfileError, render_build_script
from app.services.workspace_contract import WorkspaceContract

logger = logging.getLogger(__name__)

JOB_WORKSPACE_MOUNT = '/workspace'


class RuntimeWorkloadService:
    """把开发目录按 Dockerfile 打成个人运行镜像，并单独部署到 k3s。"""

    def __init__(self, k3s) -> None:
        self.k3s = k3s

    def build_runtime_image(
        self,
        *,
        emp_id: str | None,
        username: str,
        email: str | None,
        pod_name: str,
    ) -> dict[str, Any]:
        namespace, record, pod = self._owned_running_pod(emp_id, username, pod_name)
        if not email:
            raise RuntimeError('当前用户缺少邮箱，无法保存运行镜像')
        if not self._pod_has_workspace(pod):
            raise ValueError('这个开发沙盒没有挂载持久工作区，无法打包运行镜像。请重新创建开发沙盒')

        app_name = record['app_name']
        contract = WorkspaceContract.from_settings(self.k3s.settings, app_name)
        dockerfile = self._read_dockerfile(namespace, pod_name, contract.dockerfile_path)
        push_registry = self.k3s._commit_push_registry()
        try:
            self.k3s.harbor_service.ensure_user_private_project(email)
            project_name = self.k3s._harbor_user_project_name(email)
            credentials_secret_name = self.k3s._ensure_harbor_credentials_secret(email, namespace)
        except Exception as exc:
            logger.warning('准备运行镜像仓库失败：%s', exc)
            raise RuntimeError(f'准备个人镜像仓库失败：{exc}') from exc

        push_ref = f'{push_registry}/{project_name}/{app_name}:latest'
        pull_ref = self._pull_ref(project_name, app_name)
        socket = self.k3s.settings.k3s_commit_containerd_socket
        nerdctl = f'nerdctl --address {shlex.quote(socket)} --namespace k8s.io'
        context_dir = f'{JOB_WORKSPACE_MOUNT}/apps/{app_name}'
        try:
            script = render_build_script(
                dockerfile_text=dockerfile,
                nerdctl=nerdctl,
                container_name=f'rt{uuid.uuid4().hex[:8]}',
                context_dir=context_dir,
                push_registry=push_registry,
                push_ref=push_ref,
                insecure=self.k3s.settings.k3s_commit_insecure_registry,
            )
        except DockerfileError as exc:
            raise ValueError(str(exc)) from exc

        job_name = f'runtime-{uuid.uuid4().hex[:8]}'
        try:
            self.k3s._batch().create_namespaced_job(
                namespace=namespace,
                body=self._build_job_body(
                    job_name=job_name,
                    namespace=namespace,
                    secret_name=credentials_secret_name,
                    pod_name=pod_name,
                    script=script,
                    pull_ref=pull_ref,
                ),
            )
        except self.k3s._api_exception_class() as exc:
            logger.warning('创建运行镜像构建 Job %s 失败：%s', job_name, exc)
            raise RuntimeError(f'提交运行镜像构建失败：{exc.reason or exc.status}') from exc
        except Exception as exc:
            logger.warning('创建运行镜像构建 Job %s 异常：%s', job_name, exc)
            raise RuntimeError(f'提交运行镜像构建失败：{exc}') from exc

        return {
            'job_name': job_name,
            'pod_name': pod_name,
            'namespace': namespace,
            'image': pull_ref,
            'status': 'Running',
            'message': '正在根据 Dockerfile 构建运行镜像',
        }

    def deploy_published_runtime(
        self,
        *,
        emp_id: str | None,
        username: str,
        email: str | None,
        pod_name: str,
    ) -> dict[str, Any]:
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法部署运行镜像')
        if not email:
            raise RuntimeError('当前用户缺少邮箱，无法部署运行镜像')
        namespace = self.k3s.namespace_for_emp_id(emp_id)
        record = self.k3s.container_repository.get_container_record(pod_name=pod_name)
        if not record:
            raise FileNotFoundError('未找到容器记录')
        if record.get('username') and record['username'] != username:
            raise PermissionError('无权发布该应用')
        app_name = record.get('app_name')
        if not app_name:
            raise ValueError('容器记录缺少应用名称')

        project_name = self.k3s._harbor_user_project_name(email)
        pull_ref = self._pull_ref(project_name, app_name)
        if not self._runtime_image_ready(project_name, app_name):
            contract = WorkspaceContract.from_settings(self.k3s.settings, app_name)
            raise ValueError(
                f'运行镜像还没有构建完成。请先在 {contract.dockerfile_path} 写好 Dockerfile，'
                '再用开发 Agent 或发布操作构建运行镜像'
            )

        gpu_count = self._gpu_count(namespace, pod_name)
        pull_secret_name = self.k3s._ensure_harbor_pull_secret(email, namespace)
        self._apply_runtime_service(namespace, app_name)
        self._apply_runtime_deployment(
            namespace=namespace,
            app_name=app_name,
            image_ref=pull_ref,
            pull_secret_name=pull_secret_name,
            gpu_count=gpu_count,
        )
        self.k3s._set_ingress_backend_service(namespace, app_name, self._runtime_service_name(app_name))
        return {
            'app_name': app_name,
            'image': pull_ref,
            'service': self._runtime_service_name(app_name),
        }

    def remove_published_runtime(self, *, pod_name: str, username: str) -> None:
        record = self.k3s.container_repository.get_container_record(pod_name=pod_name)
        if not record:
            return
        if record.get('username') and record['username'] != username:
            raise PermissionError('无权取消发布该应用')
        app_name = record.get('app_name')
        namespace = record.get('namespace')
        if not app_name or not namespace:
            return
        self._delete_if_exists(
            lambda: self.k3s._apps().delete_namespaced_deployment(
                name=self._runtime_deployment_name(app_name),
                namespace=namespace,
            )
        )
        self._delete_if_exists(
            lambda: self.k3s._core().delete_namespaced_service(
                name=self._runtime_service_name(app_name),
                namespace=namespace,
            )
        )
        try:
            self.k3s._set_ingress_backend_service(namespace, app_name, f'{app_name}-svc')
        except FileNotFoundError:
            logger.info('应用 %s 的 Ingress 不存在，跳过切回开发沙盒', app_name)

    def _owned_running_pod(self, emp_id: str | None, username: str, pod_name: str):
        if not pod_name or not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', pod_name):
            raise ValueError('Pod 名称不合法')
        if not emp_id:
            raise RuntimeError('当前用户缺少 emp_id，无法构建运行镜像')
        namespace = self.k3s.namespace_for_emp_id(emp_id)
        record = self.k3s.container_repository.get_container_record(pod_name=pod_name)
        if not record:
            raise FileNotFoundError('未找到容器记录')
        if record.get('username') and record['username'] != username:
            raise PermissionError('无权构建该应用的运行镜像')
        if not record.get('app_name'):
            raise ValueError('容器记录缺少应用名称')
        try:
            pod = self.k3s._core().read_namespaced_pod(name=pod_name, namespace=namespace)
        except self.k3s._api_exception_class() as exc:
            if exc.status == 404:
                raise FileNotFoundError('未找到开发沙盒') from exc
            raise RuntimeError(f'查询开发沙盒失败：{exc.reason or exc.status}') from exc
        if not pod.status or pod.status.phase != 'Running':
            raise RuntimeError('只有运行中的开发沙盒可以构建运行镜像')
        return namespace, record, pod

    def _pod_has_workspace(self, pod) -> bool:
        claim_name = (self.k3s.settings.k3s_user_workspace_pvc_name or 'user-workspace').strip()
        for volume in pod.spec.volumes or []:
            claim = volume.persistent_volume_claim
            if claim and claim.claim_name == claim_name:
                return True
        return False

    def _read_dockerfile(self, namespace: str, pod_name: str, path: str) -> str:
        marker = '__CAMPUS_DOCKERFILE_MISSING__'
        script = (
            f'if [ ! -f {shlex.quote(path)} ]; then echo {marker}; exit 0; fi; '
            f'cat {shlex.quote(path)}'
        )
        stdout, stderr, code = self.k3s.exec_shell(namespace, pod_name, script, timeout=30)
        if code not in (0, None):
            detail = (stderr or stdout or '').strip()
            raise RuntimeError(detail or '读取 Dockerfile 失败')
        if marker in stdout:
            raise ValueError(
                f'还没有 Dockerfile。请使用开发 Agent，或在 {path} 写好启动方式后再发布'
            )
        text = stdout.strip()
        if len(text.encode()) > 64 * 1024:
            raise ValueError('Dockerfile 过大')
        if not text:
            raise ValueError(f'{path} 是空的，无法构建运行镜像')
        return text if text.endswith('\n') else text + '\n'

    def _runtime_image_ready(self, project_name: str, app_name: str) -> bool:
        for _ in range(5):
            try:
                if self.k3s.harbor_service.artifact_exists(project_name, app_name, 'latest'):
                    return True
            except Exception as exc:
                logger.warning('查询运行镜像 %s/%s 失败：%s', project_name, app_name, exc)
                return False
            time.sleep(2)
        return False

    def _pull_ref(self, project_name: str, app_name: str) -> str:
        registry = self.k3s.settings.harbor_registry.rstrip('/')
        return f'{registry}/{project_name}/{app_name}:latest'

    def _gpu_count(self, namespace: str, pod_name: str) -> int:
        try:
            pod = self.k3s._core().read_namespaced_pod(name=pod_name, namespace=namespace)
        except Exception:
            return 0
        containers = pod.spec.containers if pod.spec and pod.spec.containers else []
        if not containers or not containers[0].resources or not containers[0].resources.limits:
            return 0
        raw = containers[0].resources.limits.get('nvidia.com/gpu')
        try:
            return max(0, int(str(raw)))
        except (TypeError, ValueError):
            return 0

    def _apply_runtime_service(self, namespace: str, app_name: str) -> None:
        from kubernetes import client

        name = self._runtime_service_name(app_name)
        body = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=name,
                labels={
                    'app.kubernetes.io/managed-by': 'campus-ai',
                    'campus-ai/runtime-for': app_name,
                },
            ),
            spec=client.V1ServiceSpec(
                type='ClusterIP',
                selector=self._runtime_selector(app_name),
                ports=[
                    client.V1ServicePort(name='http', port=80, target_port=3000),
                ],
            ),
        )
        try:
            self.k3s._core().create_namespaced_service(namespace=namespace, body=body)
        except self.k3s._api_exception_class() as exc:
            if exc.status != 409:
                raise RuntimeError(f'创建运行服务失败：{exc.reason or exc.status}') from exc

    def _apply_runtime_deployment(
        self,
        *,
        namespace: str,
        app_name: str,
        image_ref: str,
        pull_secret_name: str | None,
        gpu_count: int,
    ) -> None:
        from kubernetes import client

        name = self._runtime_deployment_name(app_name)
        limits = {
            'cpu': self.k3s.settings.k3s_runtime_cpu,
            'memory': self.k3s.settings.k3s_runtime_memory,
        }
        if gpu_count > 0:
            limits = {
                'cpu': str(max(4, 4 * gpu_count)),
                'memory': f'{max(8, 8 * gpu_count)}Gi',
                'nvidia.com/gpu': str(gpu_count),
            }
        labels = self._runtime_selector(app_name)
        body = client.V1Deployment(
            api_version='apps/v1',
            kind='Deployment',
            metadata=client.V1ObjectMeta(
                name=name,
                labels=labels,
            ),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(match_labels=labels),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels=labels,
                        annotations={
                            'campus-ai/published-at': datetime.now(timezone.utc).isoformat(),
                        },
                    ),
                    spec=client.V1PodSpec(
                        restart_policy='Always',
                        node_selector={'competition': 'true'},
                        affinity=self.k3s._devbox_affinity(needs_gpu=gpu_count > 0),
                        image_pull_secrets=[
                            client.V1LocalObjectReference(name=pull_secret_name)
                        ] if pull_secret_name else None,
                        containers=[
                            client.V1Container(
                                name='app',
                                image=image_ref,
                                image_pull_policy='Always',
                                ports=[client.V1ContainerPort(name='http', container_port=3000)],
                                resources=client.V1ResourceRequirements(
                                    requests=limits,
                                    limits=limits,
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )
        apps = self.k3s._apps()
        try:
            existing = apps.read_namespaced_deployment(name=name, namespace=namespace)
            body.metadata.resource_version = existing.metadata.resource_version
            apps.replace_namespaced_deployment(name=name, namespace=namespace, body=body)
        except self.k3s._api_exception_class() as exc:
            if exc.status != 404:
                raise RuntimeError(f'更新运行副本失败：{exc.reason or exc.status}') from exc
            try:
                apps.create_namespaced_deployment(namespace=namespace, body=body)
            except self.k3s._api_exception_class() as create_exc:
                raise RuntimeError(f'创建运行副本失败：{create_exc.reason or create_exc.status}') from create_exc

    def _build_job_body(
        self,
        *,
        job_name: str,
        namespace: str,
        secret_name: str,
        pod_name: str,
        script: str,
        pull_ref: str,
    ):
        from kubernetes import client

        socket_mount_path = self.k3s.settings.k3s_commit_containerd_socket
        claim_name = (self.k3s.settings.k3s_user_workspace_pvc_name or 'user-workspace').strip()
        labels = {
            'app.kubernetes.io/managed-by': 'campus-ai',
            'campus-ai/commit-job': 'true',
            'campus-ai/runtime-build': 'true',
            'campus-ai/source-namespace': namespace,
            'campus-ai/source-pod': pod_name,
        }
        annotations = {'campus-ai/commit-image': pull_ref}
        return client.V1Job(
            api_version='batch/v1',
            kind='Job',
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=namespace,
                labels=labels,
                annotations=annotations,
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=600,
                backoff_limit=0,
                active_deadline_seconds=900,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=labels, annotations=annotations),
                    spec=client.V1PodSpec(
                        restart_policy='Never',
                        node_selector={'competition': 'true'},
                        containers=[
                            client.V1Container(
                                name='runtime-build',
                                image=self.k3s.settings.k3s_commit_nerdctl_image,
                                security_context=client.V1SecurityContext(privileged=True),
                                command=['/bin/sh', '-c', script],
                                env=[
                                    client.V1EnvVar(
                                        name='HARBOR_USERNAME',
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name=secret_name,
                                                key='username',
                                            )
                                        ),
                                    ),
                                    client.V1EnvVar(
                                        name='HARBOR_PASSWORD',
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name=secret_name,
                                                key='password',
                                            )
                                        ),
                                    ),
                                ],
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name='containerd-sock',
                                        mount_path=socket_mount_path,
                                    ),
                                    client.V1VolumeMount(
                                        name='workspace',
                                        mount_path=JOB_WORKSPACE_MOUNT,
                                    ),
                                ],
                            )
                        ],
                        volumes=[
                            client.V1Volume(
                                name='containerd-sock',
                                host_path=client.V1HostPathVolumeSource(
                                    path=self.k3s.settings.k3s_commit_host_containerd_socket,
                                    type='Socket',
                                ),
                            ),
                            client.V1Volume(
                                name='workspace',
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name=claim_name,
                                ),
                            ),
                        ],
                    ),
                ),
            ),
        )

    def _delete_if_exists(self, action) -> None:
        try:
            action()
        except self.k3s._api_exception_class() as exc:
            if exc.status != 404:
                raise RuntimeError(f'删除运行副本失败：{exc.reason or exc.status}') from exc

    @staticmethod
    def _runtime_selector(app_name: str) -> dict[str, str]:
        return {
            'app': 'campus-ai-runtime',
            'campus-ai/runtime-for': app_name,
        }

    @staticmethod
    def _runtime_deployment_name(app_name: str) -> str:
        return f'{app_name}-runtime'

    @staticmethod
    def _runtime_service_name(app_name: str) -> str:
        return f'{app_name}-runtime-svc'
