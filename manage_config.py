# -*- coding: utf-8 -*-
"""
配合 .github/workflows/manage-config.yml 使用。
GitHub网页上"Run workflow"那个表单填的内容，会通过环境变量传进来，
这个脚本负责按表单里选的操作类型，去增/删/启用/停用 config.json 里的展会门户网站。
"""
import json
import os
import sys

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

action = os.environ.get("ACTION_TYPE", "").strip()
name = os.environ.get("ITEM_NAME", "").strip()
value = os.environ.get("ITEM_VALUE", "").strip()

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

config.setdefault("exhibition_portals", [])


def find_index(lst, target_name):
    for i, item in enumerate(lst):
        if item.get("name") == target_name:
            return i
    return -1


def save():
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


if action == "添加展会门户":
    if not name or not value:
        print('添加展会门户需要同时填写"名称"和"网址"这两栏，本次没有做任何修改。')
        sys.exit(0)
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        print(f'展会门户「{name}」已经存在，没有重复添加。')
    else:
        url = value if value.startswith("http") else "https://" + value
        config["exhibition_portals"].append({"name": name, "url": url, "enabled": True})
        save()
        print(f'已添加展会门户「{name}」（网址：{url}）')

elif action == "删除展会门户":
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        config["exhibition_portals"].pop(idx)
        save()
        print(f'已删除展会门户「{name}」')
    else:
        print(f'没有找到名叫「{name}」的展会门户，没有做任何修改，请检查名称是否和现有列表完全一致。')

elif action == "启用展会门户":
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        config["exhibition_portals"][idx]["enabled"] = True
        save()
        print(f'已启用展会门户「{name}」')
    else:
        print(f'没有找到名叫「{name}」的展会门户。')

elif action == "停用展会门户":
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        config["exhibition_portals"][idx]["enabled"] = False
        save()
        print(f'已停用展会门户「{name}」')
    else:
        print(f'没有找到名叫「{name}」的展会门户。')

else:
    print(f'不认识的操作类型："{action}"，没有做任何修改。')
