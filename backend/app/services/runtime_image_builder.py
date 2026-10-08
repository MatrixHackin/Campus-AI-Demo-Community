from __future__ import annotations

import re
import shlex

_IMAGE_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,200}$')
_ENV_KEY_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_SUPPORTED = {'FROM', 'WORKDIR', 'COPY', 'ENV', 'EXPOSE', 'RUN', 'CMD', 'ENTRYPOINT'}


class DockerfileError(ValueError):
    pass


def parse_dockerfile(text: str) -> list[tuple[str, str]]:
    logical_lines: list[str] = []
    buffer = ''
    for raw in text.splitlines():
        stripped = raw.strip()
        if not buffer and (not stripped or stripped.startswith('#')):
            continue
        if stripped.endswith('\\'):
            buffer += stripped[:-1].rstrip() + ' '
            continue
        buffer += stripped
        if buffer.strip():
            logical_lines.append(buffer.strip())
        buffer = ''
    if buffer.strip():
        raise DockerfileError('Dockerfile 有未结束的续行')

    instructions: list[tuple[str, str]] = []
    for line in logical_lines:
        parts = line.split(None, 1)
        op = parts[0].upper()
        arg = parts[1].strip() if len(parts) > 1 else ''
        if op not in _SUPPORTED:
            raise DockerfileError(f'Dockerfile 暂不支持 {op}，请只使用 FROM、WORKDIR、COPY、ENV、EXPOSE、RUN、CMD、ENTRYPOINT')
        instructions.append((op, arg))
    return instructions


def build_plan(text: str) -> dict:
    instructions = parse_dockerfile(text)
    if not instructions or instructions[0][0] != 'FROM':
        raise DockerfileError('Dockerfile 必须以 FROM 开头')

    base_image = ''
    workdir = '/'
    env: list[tuple[str, str]] = []
    steps: list[dict] = []
    entrypoint = None
    cmd = None

    for op, arg in instructions:
        if op == 'FROM':
            if base_image:
                raise DockerfileError('暂不支持多阶段构建')
            token = arg.split()[0] if arg else ''
            if not token or token.startswith('-') or re.search(r'\s+AS\s+', arg, re.IGNORECASE):
                raise DockerfileError('FROM 只支持单个基础镜像，不能带平台参数或多阶段别名')
            if not _IMAGE_PATTERN.fullmatch(token):
                raise DockerfileError('基础镜像名称不合法')
            base_image = token
            continue
        if op == 'WORKDIR':
            if not arg or '\n' in arg:
                raise DockerfileError('WORKDIR 不能为空')
            workdir = arg if arg.startswith('/') else f'{workdir.rstrip("/")}/{arg}'
            continue
        if op == 'COPY':
            if arg.startswith('-'):
                raise DockerfileError('COPY 暂不支持参数')
            parts = arg.split()
            if len(parts) != 2:
                raise DockerfileError('COPY 只支持一个源路径和一个目标路径，例如 COPY . /app')
            src, dest = parts
            _validate_copy_source(src)
            if dest == '.':
                dest = workdir
            elif not dest.startswith('/'):
                dest = f'{workdir.rstrip("/")}/{dest}'
            if '..' in dest.split('/') or not dest.startswith('/'):
                raise DockerfileError('COPY 目标路径不合法')
            steps.append({'op': 'copy', 'src': src, 'dest': dest})
            continue
        if op == 'ENV':
            env.extend(_parse_env(arg))
            continue
        if op == 'EXPOSE':
            continue
        if op == 'RUN':
            if not arg:
                raise DockerfileError('RUN 不能为空')
            steps.append({
                'op': 'run',
                'command': arg,
                'workdir': workdir,
                'env': list(env),
            })
            continue
        if op == 'CMD':
            cmd = arg
            continue
        if op == 'ENTRYPOINT':
            entrypoint = arg
            continue

    if not base_image:
        raise DockerfileError('Dockerfile 缺少 FROM')
    if not cmd and not entrypoint:
        raise DockerfileError('Dockerfile 必须写出 CMD 或 ENTRYPOINT，运行镜像才知道如何启动')
    return {
        'base_image': base_image,
        'workdir': workdir,
        'env': env,
        'steps': steps,
        'entrypoint': entrypoint,
        'cmd': cmd,
    }


def render_build_script(
    *,
    dockerfile_text: str,
    nerdctl: str,
    container_name: str,
    context_dir: str,
    push_registry: str,
    push_ref: str,
    insecure: bool,
) -> str:
    plan = build_plan(dockerfile_text)
    flag = ' --insecure-registry' if insecure else ''
    lines = [
        'set -eu',
        f'NERDCTL={shlex.quote(nerdctl)}',
        f'NAME={shlex.quote(container_name)}',
        'cleanup() { $NERDCTL rm -f "$NAME" >/dev/null 2>&1 || true; }',
        'trap cleanup EXIT',
        (
            f'printf "%s\\n" "$HARBOR_PASSWORD" | $NERDCTL login '
            f'-u "$HARBOR_USERNAME" --password-stdin {shlex.quote(push_registry)}{flag}'
        ),
        '$NERDCTL rm -f "$NAME" >/dev/null 2>&1 || true',
        (
            '$NERDCTL run -d --network host --name "$NAME" --entrypoint /bin/sh '
            f'{shlex.quote(plan["base_image"])} -c {shlex.quote("while true; do sleep 3600; done")}'
        ),
    ]
    for step in plan['steps']:
        if step['op'] == 'copy':
            host_src = _host_source(context_dir, step['src'])
            directory_copy = step['src'] in {'.', './'} or step['src'].endswith('/')
            mkdir_target = step['dest'] if directory_copy else (step['dest'].rsplit('/', 1)[0] or '/')
            lines.append(f'$NERDCTL exec "$NAME" mkdir -p {shlex.quote(mkdir_target)}')
            lines.append(f'$NERDCTL cp {shlex.quote(host_src)} "$NAME":{shlex.quote(step["dest"])}')
            continue
        exports = ' && '.join(
            f'export {key}={shlex.quote(value)}' for key, value in step['env']
        )
        inner = f'cd {shlex.quote(step["workdir"])}'
        if exports:
            inner += f' && {exports}'
        inner += f' && {step["command"]}'
        lines.append(f'$NERDCTL exec "$NAME" /bin/sh -lc {shlex.quote(inner)}')

    changes = [f'WORKDIR {plan["workdir"]}']
    changes.extend(_env_instruction(key, value) for key, value in plan['env'])
    if plan['entrypoint'] is None:
        changes.append('ENTRYPOINT []')
    else:
        changes.append(f'ENTRYPOINT {plan["entrypoint"]}')
    if plan['cmd']:
        changes.append(f'CMD {plan["cmd"]}')
    change_args = ' '.join(f'--change {shlex.quote(item)}' for item in changes)
    lines.append(f'$NERDCTL commit {change_args} "$NAME" {shlex.quote(push_ref)}')
    lines.append(f'$NERDCTL push {shlex.quote(push_ref)}{flag}')
    return '\n'.join(lines) + '\n'


def _validate_copy_source(src: str) -> None:
    if src.startswith('/') or src.startswith('-') or '*' in src or '?' in src:
        raise DockerfileError('COPY 源路径必须是应用目录内的相对路径，且不能使用通配符')
    parts = src.split('/')
    if any(part == '..' for part in parts):
        raise DockerfileError('COPY 源路径不能跳出应用目录')


def _host_source(context_dir: str, src: str) -> str:
    root = context_dir.rstrip('/')
    if src in {'.', './'}:
        return f'{root}/.'
    return f'{root}/{src.lstrip("./")}'


def _parse_env(arg: str) -> list[tuple[str, str]]:
    if not arg:
        raise DockerfileError('ENV 不能为空')
    if '=' in arg.split()[0]:
        pairs: list[tuple[str, str]] = []
        for token in arg.split():
            key, separator, value = token.partition('=')
            if not separator or not _ENV_KEY_PATTERN.fullmatch(key):
                raise DockerfileError('ENV 格式应为 KEY=VALUE')
            pairs.append((key, value))
        return pairs
    key, separator, value = arg.partition(' ')
    if not separator or not _ENV_KEY_PATTERN.fullmatch(key):
        raise DockerfileError('ENV 格式应为 KEY VALUE 或 KEY=VALUE')
    return [(key, value.strip())]


def _env_instruction(key: str, value: str) -> str:
    if re.fullmatch(r'[A-Za-z0-9_./:@+-]+', value or ''):
        return f'ENV {key}={value}'
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'ENV {key}="{escaped}"'
