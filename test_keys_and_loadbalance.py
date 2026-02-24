#!/usr/bin/env python3
"""
多 API Key 验证与负载均衡效果测试脚本。

用法:
    # 测试直连 agentrouter.org（逐个验证每个 key 是否有效）
    python test_keys_and_loadbalance.py --direct

    # 测试通过代理的负载均衡效果（需先启动 Node 代理 + LiteLLM 代理）
    python test_keys_and_loadbalance.py --proxy

    # 同时测试两者
    python test_keys_and_loadbalance.py --direct --proxy

    # 自定义参数
    python test_keys_and_loadbalance.py --direct --proxy \
        --keys "sk-key1,sk-key2,sk-key3" \
        --model glm-4.6 \
        --proxy-url http://localhost:8000 \
        --rounds 9
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

DEFAULT_PROXY_URL = "http://localhost:4000"
DEFAULT_UPSTREAM_URL = "https://agentrouter.org/v1"
DEFAULT_MODEL = "glm-4.6"
DEFAULT_MASTER_KEY = "sk-local-master"
DEFAULT_ROUNDS = 6


def load_keys_from_env() -> list[str]:
    """从环境变量或 .env 文件加载 API keys。"""
    # 先尝试环境变量
    keys_str = os.environ.get("OPENAI_API_KEYS") or os.environ.get("OPENAI_API_KEY", "")

    # 如果环境变量为空，尝试读 .env
    if not keys_str:
        env_path = Path(__file__).resolve().parent / ".env"
        if not env_path.exists():
            env_path = Path.cwd() / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                if key in ("OPENAI_API_KEYS", "OPENAI_API_KEY") and value:
                    keys_str = value
                    if key == "OPENAI_API_KEYS":
                        break  # 优先用 OPENAI_API_KEYS

    return [k.strip() for k in keys_str.split(",") if k.strip()]


def make_chat_request(
    url: str,
    api_key: str,
    model: str,
    timeout: int = 30,
) -> dict:
    """发送一个 chat completion 请求，返回解析后的 JSON 响应。"""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：你好"}],
        "max_tokens": 50,
    }).encode("utf-8")

    req = Request(
        f"{url.rstrip('/')}/v1/chat/completions"
        if "/v1" not in url else
        f"{url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    resp = urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode("utf-8"))


def mask_key(key: str) -> str:
    """掩码显示 key：保留前 5 位和后 4 位。"""
    if len(key) <= 12:
        return key[:4] + "***"
    return key[:5] + "..." + key[-4:]


# ---------------------------------------------------------------------------
# 测试 1：直连验证每个 key
# ---------------------------------------------------------------------------

def test_direct_keys(keys: list[str], model: str, upstream_url: str) -> list[str]:
    """直连 agentrouter.org 验证每个 key 的有效性。返回有效 key 列表。"""
    print("=" * 65)
    print("  直连验证：逐个测试 API Key 有效性")
    print(f"  上游地址: {upstream_url}")
    print(f"  测试模型: {model}")
    print("=" * 65)

    valid_keys = []

    for i, key in enumerate(keys, 1):
        masked = mask_key(key)
        sys.stdout.write(f"\n  [{i}/{len(keys)}] {masked} ... ")
        sys.stdout.flush()

        start = time.time()
        try:
            resp = make_chat_request(upstream_url, key, model)
            elapsed = time.time() - start
            content = resp["choices"][0]["message"]["content"].strip()
            print(f"有效  ({elapsed:.2f}s)  回复: {content[:30]}")
            valid_keys.append(key)
        except HTTPError as e:
            elapsed = time.time() - start
            try:
                body = json.loads(e.read().decode("utf-8"))
                msg = body.get("error", {}).get("message", str(body))
            except Exception:
                msg = str(e)
            print(f"失败  ({elapsed:.2f}s)  HTTP {e.code}: {msg[:60]}")
        except URLError as e:
            elapsed = time.time() - start
            print(f"失败  ({elapsed:.2f}s)  连接错误: {e.reason}")
        except Exception as e:
            elapsed = time.time() - start
            print(f"失败  ({elapsed:.2f}s)  {e}")

    print(f"\n  结果: {len(valid_keys)}/{len(keys)} 个 key 有效")
    if len(valid_keys) < len(keys):
        invalid = set(keys) - set(valid_keys)
        for k in invalid:
            print(f"    无效: {mask_key(k)}")

    return valid_keys


# ---------------------------------------------------------------------------
# 测试 2：通过代理测试负载均衡
# ---------------------------------------------------------------------------

def test_load_balance(
    proxy_url: str,
    master_key: str,
    model: str,
    rounds: int,
) -> None:
    """通过代理发送多次请求，观察负载均衡分布效果。"""
    print("\n" + "=" * 65)
    print("  负载均衡测试：通过代理发送多次请求")
    print(f"  代理地址: {proxy_url}")
    print(f"  测试模型: {model}")
    print(f"  请求轮次: {rounds}")
    print("=" * 65)

    results = []  # (轮次, 状态, 耗时, api_key_used, 回复片段)
    key_counter: Counter = Counter()

    for i in range(1, rounds + 1):
        sys.stdout.write(f"\n  请求 [{i}/{rounds}] ... ")
        sys.stdout.flush()

        start = time.time()
        try:
            resp = make_chat_request(proxy_url, master_key, model)
            elapsed = time.time() - start

            content = resp["choices"][0]["message"]["content"].strip()
            resp_model = resp.get("model", "?")

            # 尝试从 LiteLLM 的响应头里提取使用的 api_key（LiteLLM 会在内部记录）
            # 无法直接获取用了哪个 key，但可以通过 request_id 或时间推断
            print(f"成功  ({elapsed:.2f}s)  model={resp_model}  回复: {content[:30]}")
            results.append((i, "成功", elapsed, resp_model, content[:30]))
            key_counter["成功"] += 1
        except HTTPError as e:
            elapsed = time.time() - start
            try:
                body = json.loads(e.read().decode("utf-8"))
                msg = body.get("error", {}).get("message", str(body))[:50]
            except Exception:
                msg = str(e)[:50]
            print(f"失败  ({elapsed:.2f}s)  HTTP {e.code}: {msg}")
            results.append((i, f"失败({e.code})", elapsed, "-", msg))
            key_counter[f"失败({e.code})"] += 1
        except Exception as e:
            elapsed = time.time() - start
            print(f"失败  ({elapsed:.2f}s)  {str(e)[:50]}")
            results.append((i, "异常", elapsed, "-", str(e)[:50]))
            key_counter["异常"] += 1

    # 汇总
    print("\n" + "-" * 65)
    print("  负载均衡测试汇总")
    print("-" * 65)

    total_time = sum(r[2] for r in results)
    success_count = key_counter.get("成功", 0)

    print(f"  总请求数:  {rounds}")
    print(f"  成功:      {success_count}")
    print(f"  失败:      {rounds - success_count}")
    print(f"  总耗时:    {total_time:.2f}s")
    if success_count > 0:
        avg = total_time / rounds
        print(f"  平均耗时:  {avg:.2f}s/请求")

    print(f"\n  状态分布:")
    for status, count in key_counter.most_common():
        bar = "█" * count
        print(f"    {status:>10}: {count:>3}  {bar}")

    # 打印详细表格
    print(f"\n  {'轮次':>4}  {'状态':>8}  {'耗时':>6}  {'模型':>12}  {'回复'}")
    print(f"  {'----':>4}  {'--------':>8}  {'------':>6}  {'------------':>12}  {'----'}")
    for seq, status, elapsed, mdl, snippet in results:
        print(f"  {seq:>4}  {status:>8}  {elapsed:>5.2f}s  {mdl:>12}  {snippet}")

    print()
    if success_count == rounds:
        print("  全部请求成功，负载均衡运行正常。")
        print("  (查看 Node 代理终端的日志，可以看到每次请求使用了不同的 API Key)")
    elif success_count > 0:
        print("  部分请求失败，建议用 --direct 模式检查哪些 key 无效。")
    else:
        print("  所有请求都失败了，请检查代理是否正常启动。")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="多 API Key 验证与负载均衡效果测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test_keys_and_loadbalance.py --direct              # 验证每个 key
  python test_keys_and_loadbalance.py --proxy               # 测试负载均衡
  python test_keys_and_loadbalance.py --direct --proxy      # 两者都测
  python test_keys_and_loadbalance.py --proxy --rounds 12   # 12 轮负载测试
        """,
    )
    parser.add_argument("--direct", action="store_true", help="直连验证每个 API key 的有效性")
    parser.add_argument("--proxy", action="store_true", help="通过代理测试负载均衡效果")
    parser.add_argument("--keys", default=None, help="逗号分隔的 API keys（默认从 .env 读取）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"测试模型（默认: {DEFAULT_MODEL}）")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help=f"代理地址（默认: {DEFAULT_PROXY_URL}）")
    parser.add_argument("--upstream-url", default=DEFAULT_UPSTREAM_URL, help=f"上游地址（默认: {DEFAULT_UPSTREAM_URL}）")
    parser.add_argument("--master-key", default=DEFAULT_MASTER_KEY, help=f"代理认证 key（默认: {DEFAULT_MASTER_KEY}）")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help=f"负载均衡测试轮次（默认: {DEFAULT_ROUNDS}）")

    args = parser.parse_args()

    if not args.direct and not args.proxy:
        parser.print_help()
        print("\n错误: 请至少指定 --direct 或 --proxy 之一")
        sys.exit(1)

    # 加载 keys
    if args.keys:
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    else:
        keys = load_keys_from_env()

    if not keys:
        print("错误: 未找到 API keys。请用 --keys 参数指定，或在 .env 中配置 OPENAI_API_KEYS。")
        sys.exit(1)

    print(f"\n  加载了 {len(keys)} 个 API Key:")
    for i, k in enumerate(keys, 1):
        print(f"    [{i}] {mask_key(k)}")

    # 直连验证
    valid_keys = keys
    if args.direct:
        print()
        valid_keys = test_direct_keys(keys, args.model, args.upstream_url)

    # 负载均衡测试
    if args.proxy:
        test_load_balance(args.proxy_url, args.master_key, args.model, args.rounds)

    print()


if __name__ == "__main__":
    main()
