#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 WebUI API 路由"""

import httpx

BASE_URL = "http://localhost:8080/weibo/api"

def test_routes():
    """测试所有路由"""
    print("=" * 60)
    print("测试 WebUI API 路由")
    print("=" * 60)
    print()

    routes = [
        ("GET", "/webhook/config"),
        ("GET", "/schedule/config"),
        ("GET", "/cookie_check/schedule/config"),
        ("GET", "/sentiment/words?word_type=positive"),
        ("GET", "/tasks"),
    ]

    for method, path in routes:
        url = f"{BASE_URL}{path}"
        print(f"{method} {path}...", end="", flush=True)
        try:
            if method == "GET":
                resp = httpx.get(url, timeout=5)
            elif method == "POST":
                resp = httpx.post(url, json={}, timeout=5)
            elif method == "PUT":
                resp = httpx.put(url, json={}, timeout=5)

            if resp.status_code == 200:
                print(f" ✓ {resp.status_code}")
            else:
                print(f" ✗ {resp.status_code}")
        except Exception as e:
            print(f" ✗ {e}")

    print()
    print("=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_routes()
