#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试任务队列和 Cookie 分配功能"""

import httpx
import time

BASE_URL = "http://localhost:8080/weibo/api"

def test_task_queue():
    """测试任务队列功能"""
    print("=" * 60)
    print("测试任务队列和 Cookie 分配")
    print("=" * 60)
    print()

    # 1. 查看队列状态
    print("1. 查看初始队列状态...")
    resp = httpx.get(f"{BASE_URL}/tasks/queue/status")
    status = resp.json()
    print(f"   最大并发: {status['max_concurrent']}")
    print(f"   运行中: {status['running_count']}")
    print(f"   队列中: {status['queued_count']}")
    print()

    # 2. 查看可用的 Cookie Bundles
    print("2. 查看可用的 Cookie Bundles...")
    resp = httpx.get(f"{BASE_URL}/cookie_bundles")
    bundles = resp.json()
    print(f"   找到 {len(bundles)} 个 Cookie Bundle:")
    for bundle in bundles:
        print(f"   - {bundle['name']}: enabled={bundle.get('enabled')}, status={bundle.get('status')}")
    print()

    # 3. 创建多个任务测试并发控制
    print("3. 创建 5 个任务测试并发控制...")
    task_ids = []
    for i in range(5):
        resp = httpx.post(f"{BASE_URL}/tasks", json={
            "keyword": f"测试关键词{i+1}",
            "max_pages": 1,
            "with_comments": False
        })
        if resp.status_code == 200:
            task = resp.json().get("task", {})
            task_id = task.get("id")
            task_ids.append(task_id)
            print(f"   ✓ 任务 {task_id} 已创建")
        else:
            print(f"   ✗ 创建任务失败: {resp.status_code}")

    print()
    time.sleep(2)

    # 4. 查看队列状态
    print("4. 查看任务分配情况...")
    resp = httpx.get(f"{BASE_URL}/tasks/queue/status")
    status = resp.json()
    print(f"   运行中: {status['running_count']}/{status['max_concurrent']}")
    print(f"   队列中: {status['queued_count']}")
    print()

    if status['running_tasks']:
        print("   运行中的任务:")
        for task in status['running_tasks']:
            print(f"   - 任务 {task['id']}: {task['keyword']} (Cookie: {task['cookie']})")
        print()

    if status['queued_tasks']:
        print("   队列中的任务:")
        for task in status['queued_tasks']:
            print(f"   - 任务 {task['id']}: {task['keyword']}")
        print()

    # 5. 查看 Cookie 使用情况
    print("5. Cookie 使用情况:")
    for task_id, cookie_name in status['cookie_usage'].items():
        print(f"   - 任务 {task_id} 使用 Cookie: {cookie_name}")
    print()

    print("=" * 60)
    print("测试完成")
    print("=" * 60)
    print()
    print("提示:")
    print("- 最多同时运行 3 个任务")
    print("- 每个任务使用独立的 Cookie Bundle")
    print("- 超过限制的任务会进入队列")
    print("- 任务完成后会自动启动队列中的下一个任务")

if __name__ == "__main__":
    try:
        test_task_queue()
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
