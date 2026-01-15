# -*- coding: utf-8 -*-
"""
批量写入方法补丁 - 添加到 weibo_store_compat.py 文件末尾
"""

def _flush_comment_batch(self):
    """批量写入评论到 MySQL 和 ES"""
    if not self._comment_buffer:
        return

    comments = self._comment_buffer.copy()
    self._comment_buffer.clear()

    utils.logger.info(f"[WeiboCompatStore] Flushing {len(comments)} comments (batch mode)...")

    # 处理每条评论的数据
    mysql_payloads = []
    es_payloads = []
    hotword_deletions = []
    hotword_insertions = []

    for comment_item in comments:
        note_id = comment_item.get("note_id")
        comment_id = comment_item.get("comment_id")
        content_id = self._build_content_id(note_id)
        if not content_id or not comment_id:
            continue

        pinglun_id = f"{content_id}_{comment_id}"
        now = datetime.now()
        created_at = self._parse_datetime(comment_item.get("create_date_time")) or now
        update_at = self._parse_datetime(now) or now
        comment_text = self._clean_text(comment_item.get("content", ""))
        if len(comment_text) > self._MAX_TEXT_LENGTH:
            comment_text = comment_text[: self._MAX_TEXT_LENGTH]

        payload = {
            "pinglun_id": pinglun_id,
            "pinglun_parent_id": comment_item.get("parent_comment_id") or "",
            "pinglun_text": comment_text,
            "created_at": created_at,
            "sub_pinglun_count": str(comment_item.get("sub_comment_count", 0) or 0),
            "like_count": str(comment_item.get("comment_like_count", 0) or 0),
            "floor_number": str(comment_item.get("floor_number", 0) or 0),
            "pinglun_user": comment_item.get("nickname", ""),
            "weibo_content_id": content_id,
            "senti_score": int(comment_item.get("senti_score", 0) or 0),
            "update_at": update_at,
        }

        # 提取热词
        hotwords = self._extract_hotwords(payload["pinglun_text"])

        # 收集 MySQL 数据
        mysql_payloads.append((pinglun_id, payload, hotwords))

        # 收集 ES 数据
        es_payloads.append({
            "pinglun_id": pinglun_id,
            "pinglun_parent_id": payload["pinglun_parent_id"],
            "pinglun_text": payload["pinglun_text"],
            "created_at": payload["created_at"],
            "update_at": payload["update_at"],
            "sub_pinglun_count": payload["sub_pinglun_count"],
            "like_count": payload["like_count"],
            "floor_number": payload["floor_number"],
            "pinglun_user": payload["pinglun_user"],
            "weibo_content_id": content_id,
            "senti_score": payload["senti_score"],
        })

        hotword_deletions.append(pinglun_id)
        if hotwords:
            for hw in hotwords:
                hotword_insertions.append({
                    "pinglun_id": pinglun_id,
                    "word": hw["word"],
                    "weight": hw["weight"],
                })

    # 1. 批量写入 MySQL（如果启用）
    if self._session_factory and self._comment_mysql_enabled:
        session = self._session_factory()
        try:
            # 删除旧热词（批量）
            if hotword_deletions:
                from sqlalchemy import delete
                stmt = delete(WeiboPinglunHotword).where(
                    WeiboPinglunHotword.pinglun_id.in_(hotword_deletions)
                )
                session.execute(stmt)

            # 批量插入/更新评论
            for pinglun_id, payload, hotwords in mysql_payloads:
                existing = session.get(WeiboPinglun, pinglun_id)
                if existing:
                    for key, value in payload.items():
                        setattr(existing, key, value)
                else:
                    session.add(WeiboPinglun(**payload))

            # 批量插入热词
            if hotword_insertions:
                session.bulk_insert_mappings(WeiboPinglunHotword, hotword_insertions)

            session.commit()
            utils.logger.info(f"[WeiboCompatStore] MySQL: Committed {len(mysql_payloads)} comments with hotwords")
        except Exception as e:
            session.rollback()
            utils.logger.error(f"[WeiboCompatStore] MySQL batch failed: {e}")
        finally:
            session.close()

    # 2. 批量写入 ES（使用 Bulk API）
    if self._es_enabled and es_payloads:
        self._es_bulk_index(os.getenv("ES_INDEX_PINGLUN", "weibopinglun"), es_payloads)

    utils.logger.info(f"[WeiboCompatStore] Batch flush completed: {len(comments)} comments")


def _es_bulk_index(self, index_name, docs):
    """使用 ES Bulk API 批量索引文档"""
    if not self._es_base or not docs:
        return

    # 构建 Bulk API 请求体（NDJSON 格式）
    bulk_lines = []
    for doc in docs:
        doc_id = doc.get("pinglun_id")
        if not doc_id:
            continue

        # Action 行
        action = {"index": {"_index": index_name, "_id": doc_id}}
        bulk_lines.append(json.dumps(action, ensure_ascii=False))

        # Document 行
        bulk_lines.append(json.dumps(doc, ensure_ascii=False, default=self._json_default))

    if not bulk_lines:
        return

    # 拼接为 NDJSON（每行一个 JSON，结尾必须有换行符）
    bulk_body = "\n".join(bulk_lines) + "\n"

    # 调用 Bulk API
    url = f"{self._es_base}/_bulk"
    headers = {
        "Content-Type": "application/x-ndjson",
        "Accept": "application/json"
    }
    req = urlrequest.Request(
        url,
        data=bulk_body.encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            result_data = resp.read()
            result = json.loads(result_data)

            if result.get("errors"):
                # 有错误，记录详细信息
                error_items = [item for item in result.get("items", [])
                              if item.get("index", {}).get("error")]
                error_count = len(error_items)
                utils.logger.warning(
                    f"[WeiboCompatStore] ES Bulk: {error_count} errors out of {len(docs)} docs"
                )
                # 记录第一个错误示例
                if error_items:
                    first_error = error_items[0].get("index", {}).get("error")
                    utils.logger.warning(f"[WeiboCompatStore] ES Bulk error example: {first_error}")
            else:
                utils.logger.info(f"[WeiboCompatStore] ES Bulk: Successfully indexed {len(docs)} documents")

    except HTTPError as e:
        body = e.read()
        utils.logger.error(
            f"[WeiboCompatStore] ES Bulk failed: status={e.code}, body={body[:500]}"
        )
    except (TimeoutError, socket.timeout, URLError) as exc:
        utils.logger.error(f"[WeiboCompatStore] ES Bulk request error: {exc}")


async def flush_all(self):
    """刷新所有批量缓冲区（程序结束前调用）"""
    if self._batch_enabled:
        await asyncio.to_thread(self._flush_all_sync)


def _flush_all_sync(self):
    """同步刷新所有缓冲区"""
    with self._batch_lock:
        if self._comment_buffer:
            utils.logger.info(f"[WeiboCompatStore] Flushing remaining {len(self._comment_buffer)} comments...")
            self._flush_comment_batch()

        if self._content_buffer:
            utils.logger.info(f"[WeiboCompatStore] Flushing remaining {len(self._content_buffer)} contents...")
            # TODO: 实现内容批量刷新

    utils.logger.info("[WeiboCompatStore] All batch buffers flushed")
