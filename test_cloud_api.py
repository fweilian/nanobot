from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import boto3
import httpx
import jwt
import uvicorn

from nanobot.cloud.server import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the real nanobot cloud API and validate a multi-user chat flow.",
    )
    parser.add_argument(
        "--platform-config",
        default=os.environ.get("NANOBOT_CLOUD_NANOBOT_CONFIG_PATH"),
        help="Path to the platform-managed nanobot config.json.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    parser.add_argument("--redis-mode", choices=("single", "cluster", "auto"), default="single")
    parser.add_argument("--s3-endpoint-url", default="http://127.0.0.1:9000")
    parser.add_argument("--s3-region-name", default="us-east-1")
    parser.add_argument("--s3-access-key-id", default="minioadmin")
    parser.add_argument("--s3-secret-access-key", default="minioadmin")
    parser.add_argument("--s3-bucket", default="nanobot-cloud")
    parser.add_argument(
        "--s3-prefix",
        default=f"e2e-{int(time.time())}-{uuid.uuid4().hex[:8]}",
        help="Isolated object prefix for this run.",
    )
    parser.add_argument(
        "--workspace-prefix",
        default="workspaces",
        help="Per-user workspace root inside the S3 prefix.",
    )
    parser.add_argument(
        "--alice-session-id",
        default="shared-session",
        help="Session id reused by Alice before and after restart.",
    )
    parser.add_argument(
        "--bob-session-id",
        default="shared-session",
        help="Bob can use the same raw session id to prove user isolation.",
    )
    args = parser.parse_args()
    if not args.platform_config:
        parser.error("--platform-config is required")
    return args


def build_env(args: argparse.Namespace, cache_dir: Path, shared_secret: str) -> dict[str, str]:
    return {
        "NANOBOT_CLOUD_NANOBOT_CONFIG_PATH": str(Path(args.platform_config).expanduser().resolve()),
        "NANOBOT_CLOUD_LOCAL_CACHE_DIR": str(cache_dir),
        "NANOBOT_CLOUD_HOST": args.host,
        "NANOBOT_CLOUD_PORT": str(args.port),
        "NANOBOT_CLOUD_REQUEST_TIMEOUT": str(args.timeout),
        "NANOBOT_CLOUD_WORKSPACE_PREFIX": args.workspace_prefix,
        "NANOBOT_CLOUD_REDIS__URL": args.redis_url,
        "NANOBOT_CLOUD_REDIS__MODE": args.redis_mode,
        "NANOBOT_CLOUD_REDIS__KEY_PREFIX": f"nanobot-cloud-e2e:{args.s3_prefix}",
        "NANOBOT_CLOUD_REDIS__SESSION_TTL_S": "3600",
        "NANOBOT_CLOUD_REDIS__LOCK_TTL_S": "120",
        "NANOBOT_CLOUD_AUTH__ISSUER": "nanobot-cloud-e2e",
        "NANOBOT_CLOUD_AUTH__AUDIENCE": "nanobot-cloud",
        "NANOBOT_CLOUD_AUTH__USER_ID_CLAIM": "sub",
        "NANOBOT_CLOUD_AUTH__ALGORITHMS": '["HS256"]',
        "NANOBOT_CLOUD_AUTH__SHARED_SECRET": shared_secret,
        "NANOBOT_CLOUD_S3__BUCKET": args.s3_bucket,
        "NANOBOT_CLOUD_S3__PREFIX": args.s3_prefix,
        "NANOBOT_CLOUD_S3__ENDPOINT_URL": args.s3_endpoint_url,
        "NANOBOT_CLOUD_S3__REGION_NAME": args.s3_region_name,
        "NANOBOT_CLOUD_S3__ACCESS_KEY_ID": args.s3_access_key_id,
        "NANOBOT_CLOUD_S3__SECRET_ACCESS_KEY": args.s3_secret_access_key,
    }


def s3_client(args: argparse.Namespace):
    return boto3.client(
        "s3",
        endpoint_url=args.s3_endpoint_url,
        region_name=args.s3_region_name,
        aws_access_key_id=args.s3_access_key_id,
        aws_secret_access_key=args.s3_secret_access_key,
    )


def ensure_bucket(args: argparse.Namespace) -> None:
    client = s3_client(args)
    try:
        client.head_bucket(Bucket=args.s3_bucket)
    except Exception:
        create_kwargs = {"Bucket": args.s3_bucket}
        if args.s3_region_name and args.s3_region_name != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": args.s3_region_name}
        client.create_bucket(**create_kwargs)


def clear_prefix(args: argparse.Namespace) -> None:
    client = s3_client(args)
    paginator = client.get_paginator("list_objects_v2")
    prefix = args.s3_prefix.rstrip("/") + "/"
    keys: list[dict[str, str]] = []
    for page in paginator.paginate(Bucket=args.s3_bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            keys.append({"Key": item["Key"]})
    for start in range(0, len(keys), 1000):
        client.delete_objects(
            Bucket=args.s3_bucket,
            Delete={"Objects": keys[start:start + 1000], "Quiet": True},
        )


def list_user_objects(args: argparse.Namespace, user_id: str) -> list[str]:
    client = s3_client(args)
    prefix = f"{args.s3_prefix.rstrip('/')}/{args.workspace_prefix}/{user_id}/"
    paginator = client.get_paginator("list_objects_v2")
    found: list[str] = []
    for page in paginator.paginate(Bucket=args.s3_bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            found.append(item["Key"])
    return sorted(found)


def session_objects(args: argparse.Namespace, user_id: str) -> list[str]:
    return [
        key
        for key in list_user_objects(args, user_id)
        if "/sessions/" in key and key.endswith(".jsonl")
    ]


def make_token(user_id: str, shared_secret: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iss": "nanobot-cloud-e2e",
        "aud": "nanobot-cloud",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, shared_secret, algorithm="HS256")


@contextmanager
def cloud_server(env: dict[str, str], host: str, port: int) -> Iterator[None]:
    old_values = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    app = create_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_for_health(host, port)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def wait_for_health(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    url = f"http://{host}:{port}/health"
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(url)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Cloud API did not become healthy: {url}")


def print_step(title: str) -> None:
    print(f"\n=== {title} ===")


def api_client(host: str, port: int) -> httpx.Client:
    return httpx.Client(base_url=f"http://{host}:{port}", timeout=300.0)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_agents(client: httpx.Client, token: str) -> dict:
    response = client.get("/v1/agents", headers=auth_headers(token))
    response.raise_for_status()
    return response.json()


def chat_once(
    client: httpx.Client,
    token: str,
    *,
    agent: str,
    session_id: str,
    message: str,
    stream: bool = False,
) -> str:
    payload = {
        "agent": agent,
        "session_id": session_id,
        "messages": [{"role": "user", "content": message}],
        "stream": stream,
    }
    if not stream:
        response = client.post("/v1/chat/completions", headers=auth_headers(token), json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    chunks: list[str] = []
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=auth_headers(token),
        json=payload,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            body = line[6:]
            if body == "[DONE]":
                break
            event = json.loads(body)
            delta = event["choices"][0]["delta"]
            if delta.get("content"):
                chunks.append(delta["content"])
    return "".join(chunks)


def assert_default_agent(agents_payload: dict) -> None:
    ids = [item["id"] for item in agents_payload["data"]]
    if "default" not in ids:
        raise AssertionError(f"default agent not found: {ids}")


def run_validation(args: argparse.Namespace) -> None:
    ensure_bucket(args)
    clear_prefix(args)

    shared_secret = secrets.token_urlsafe(32)
    alice_token = make_token("alice", shared_secret)
    bob_token = make_token("bob", shared_secret)

    cache_dir = Path(tempfile.mkdtemp(prefix="nanobot-cloud-cache-"))
    env = build_env(args, cache_dir, shared_secret)

    try:
        print_step("START SERVER")
        with cloud_server(env, args.host, args.port):
            with api_client(args.host, args.port) as client:
                print_step("FIRST LOGIN / BOOTSTRAP")
                alice_agents = get_agents(client, alice_token)
                bob_agents = get_agents(client, bob_token)
                assert_default_agent(alice_agents)
                assert_default_agent(bob_agents)
                print("Alice agents:", alice_agents)
                print("Bob agents:", bob_agents)

                print_step("ALICE FIRST TURN")
                alice_reply_1 = chat_once(
                    client,
                    alice_token,
                    agent="default",
                    session_id=args.alice_session_id,
                    message="我是 Alice，请记住我是第一个用户。先简单回复我一句。",
                    stream=False,
                )
                print("Alice reply #1:", alice_reply_1)

                print_step("ALICE SECOND TURN SAME SESSION")
                alice_reply_2 = chat_once(
                    client,
                    alice_token,
                    agent="default",
                    session_id=args.alice_session_id,
                    message="请继续这个会话，并简短回应。",
                    stream=True,
                )
                print("Alice reply #2 (streamed):", alice_reply_2)

                print_step("BOB TURN WITH SAME RAW SESSION ID")
                bob_reply_1 = chat_once(
                    client,
                    bob_token,
                    agent="default",
                    session_id=args.bob_session_id,
                    message="我是 Bob，这是另一个用户的会话，请简单回复我一句。",
                    stream=False,
                )
                print("Bob reply #1:", bob_reply_1)

                print_step("CHECK S3 OBJECTS BEFORE RESTART")
                alice_objects_before = list_user_objects(args, "alice")
                bob_objects_before = list_user_objects(args, "bob")
                print("Alice objects:", alice_objects_before)
                print("Bob objects:", bob_objects_before)
                alice_sessions_before = session_objects(args, "alice")
                bob_sessions_before = session_objects(args, "bob")
                if not alice_sessions_before or not bob_sessions_before:
                    raise AssertionError("Expected session files for both users in object storage")
                print("Alice session objects:", alice_sessions_before)
                print("Bob session objects:", bob_sessions_before)

        print_step("RESTART SERVER")
        shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir = Path(tempfile.mkdtemp(prefix="nanobot-cloud-cache-"))
        env = build_env(args, cache_dir, shared_secret)

        with cloud_server(env, args.host, args.port):
            with api_client(args.host, args.port) as client:
                print_step("ALICE AFTER RESTART")
                alice_reply_3 = chat_once(
                    client,
                    alice_token,
                    agent="default",
                    session_id=args.alice_session_id,
                    message="服务已经重启。请继续回应当前会话。",
                    stream=False,
                )
                print("Alice reply #3 after restart:", alice_reply_3)

                print_step("CHECK S3 OBJECTS AFTER RESTART")
                alice_sessions_after = session_objects(args, "alice")
                bob_sessions_after = session_objects(args, "bob")
                print("Alice session objects after restart:", alice_sessions_after)
                print("Bob session objects after restart:", bob_sessions_after)
                if alice_sessions_before != alice_sessions_after:
                    raise AssertionError(
                        "Alice session object keys changed unexpectedly across restart"
                    )
                if bob_sessions_before != bob_sessions_after:
                    raise AssertionError(
                        "Bob session object keys changed unexpectedly across restart"
                    )

        print_step("VALIDATION PASSED")
        print("Multi-user chat flow completed successfully.")
        print(f"S3 bucket: {args.s3_bucket}")
        print(f"S3 prefix: {args.s3_prefix}")
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)


def main() -> int:
    args = parse_args()
    try:
        run_validation(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"\nVALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
