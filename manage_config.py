# -*- coding: utf-8 -*-
"""
配合 .github/workflows/manage-config.yml 使用。
GitHub网页上"Run workflow"那个表单填的内容，会通过环境变量传进来，
这个脚本负责按表单里选的操作类型，去增/删/启用/停用 config.json 里对应的一项。
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

config.setdefault("keywords", [])
config.setdefault("official_pages", [])


def find_index(lst, target_name):
    for i, item in enumerate(lst):
        if item.get("name") == target_name:
            return i
    return -1


def save():
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


if action == "添加关键词":
    if not name or not value:
        print('添加关键词需要同时填写"名称"和"搜索词内容"这两栏，本次没有做任何修改。')
        sys.exit(0)
    idx = find_index(config["keywords"], name)
    if idx >= 0:
        print(f'关键词「{name}」已经存在，没有重复添加。')
    else:
        config["keywords"].append({"name": name, "q": value, "enabled": True})
        save()
        print(f'已添加关键词「{name}」（搜索词：{value}）')

elif action == "删除关键词":
    idx = find_index(config["keywords"], name)
    if idx >= 0:
        config["keywords"].pop(idx)
        save()
        print(f'已删除关键词「{name}」')
    else:
        print(f'没有找到名叫「{name}」的关键词，没有做任何修改，请检查名称是否和现有列表完全一致。')

elif action == "启用关键词":
    idx = find_index(config["keywords"], name)
    if idx >= 0:
        config["keywords"][idx]["enabled"] = True
        save()
        print(f'已启用关键词「{name}」')
    else:
        print(f'没有找到名叫「{name}」的关键词。')

elif action == "停用关键词":
    idx = find_index(config["keywords"], name)
    if idx >= 0:
        config["keywords"][idx]["enabled"] = False
        save()
        print(f'已停用关键词「{name}」')
    else:
        print(f'没有找到名叫「{name}」的关键词。')

elif action == "添加官网":
    if not name or not value:
        print('添加官网需要同时填写"名称"和"网址"这两栏，本次没有做任何修改。')
        sys.exit(0)
    idx = find_index(config["official_pages"], name)
    if idx >= 0:
        print(f'官网「{name}」已经存在，没有重复添加。')
    else:
        url = value if value.startswith("http") else "https://" + value
        config["official_pages"].append({"name": name, "url": url, "enabled": True})
        save()
        print(f'已添加官网「{name}」（网址：{url}）')

elif action == "删除官网":
    idx = find_index(config["official_pages"], name)
    if idx >= 0:
        config["official_pages"].pop(idx)
        save()
        print(f'已删除官网「{name}」')
    else:
        print(f'没有找到名叫「{name}」的官网。')

elif action == "启用官网":
    idx = find_index(config["official_pages"], name)
    if idx >= 0:
        config["official_pages"][idx]["enabled"] = True
        save()
        print(f'已启用官网「{name}」')
    else:
        print(f'没有找到名叫「{name}」的官网。')

elif action == "停用官网":
    idx = find_index(config["official_pages"], name)
    if idx >= 0:
        config["official_pages"][idx]["enabled"] = False
        save()
        print(f'已停用官网「{name}」')
    else:
        print(f'没有找到名叫「{name}」的官网。')

elif action == "添加展会门户":
    if not name or not value:
        print('添加展会门户需要同时填写"名称"和"网址"这两栏，本次没有做任何修改。')
        sys.exit(0)
    config.setdefault("exhibition_portals", [])
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        print(f'展会门户「{name}」已经存在，没有重复添加。')
    else:
        url = value if value.startswith("http") else "https://" + value
        config["exhibition_portals"].append({"name": name, "url": url, "enabled": True})
        save()
        print(f'已添加展会门户「{name}」（网址：{url}）')

elif action == "删除展会门户":
    config.setdefault("exhibition_portals", [])
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        config["exhibition_portals"].pop(idx)
        save()
        print(f'已删除展会门户「{name}」')
    else:
        print(f'没有找到名叫「{name}」的展会门户。')

elif action == "启用展会门户":
    config.setdefault("exhibition_portals", [])
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        config["exhibition_portals"][idx]["enabled"] = True
        save()
        print(f'已启用展会门户「{name}」')
    else:
        print(f'没有找到名叫「{name}」的展会门户。')

elif action == "停用展会门户":
    config.setdefault("exhibition_portals", [])
    idx = find_index(config["exhibition_portals"], name)
    if idx >= 0:
        config["exhibition_portals"][idx]["enabled"] = False
        save()
        print(f'已停用展会门户「{name}」')
    else:
        print(f'没有找到名叫「{name}」的展会门户。')

else:
    print(f'不认识的操作类型："{action}"，没有做任何修改。')
