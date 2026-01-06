# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/weibo/weibo_es_mappings.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

_weibocontent_mappings = {
    "mappings": {
        "properties": {
            "content_id": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "spider_id": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "content_text": {"type": "text", "analyzer": "jieba_index"},
            "reposts_count": {"type": "integer"},
            "comments_count": {"type": "integer"},
            "attitudes_count": {"type": "integer"},
            "create_user": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "weibo_url": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "created_at": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss"},
            "update_at": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss"},
            "senti_score": {"type": "integer"},
            "hotwords": {
                "type": "nested",
                "properties": {
                    "word": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "weight": {"type": "integer"},
                },
            },
        }
    }
}

_weibopinglun_mappings = {
    "mappings": {
        "properties": {
            "pinglun_id": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "pinglun_parent_id": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "pinglun_text": {"type": "text", "analyzer": "jieba_index"},
            "created_at": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss"},
            "update_at": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss"},
            "sub_pinglun_count": {"type": "integer"},
            "like_count": {"type": "integer"},
            "floor_number": {"type": "integer"},
            "pinglun_user": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "weibo_content_id": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "senti_score": {"type": "integer"},
            "hotwords": {
                "type": "nested",
                "properties": {
                    "word": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "weight": {"type": "integer"},
                },
            },
        }
    }
}
