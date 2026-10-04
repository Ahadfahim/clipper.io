"""Read-only analytics for the Analyst and Director (PLAN §16.1 insights).

Everything runs on ``Database.readonly()`` (SQLite ``mode=ro`` + ``query_only``), so even a crafted SQL
string can't change data; ``query`` additionally accepts a single SELECT/WITH statement only.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from clipper.services.base import Service, ServiceError

MAX_ROWS = 200
_ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.I)

DIMENSIONS: dict[str, str] = {
    "marketplace": "c.marketplace",
    "campaign": "c.id",
    "platform": "p.platform",
    "account": "p.account_id",
    "layout": "cl.layout",
    "caption_style": "cl.caption_style",
    "hour": "strftime('%H', p.posted_at)",
}


class InsightsService(Service):
    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = self.db.readonly()
        try:
            cur = conn.execute(sql, params)
            cols = [d[0] for d in cur.description or []]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchmany(MAX_ROWS)]
        except sqlite3.Error as exc:
            raise ServiceError(f"query failed: {exc}") from exc
        finally:
            conn.close()

    def query(self, sql: str) -> dict[str, Any]:
        stripped = sql.strip().rstrip(";")
        if ";" in stripped or not _ALLOWED_START.match(stripped):
            raise ServiceError("insights.query runs one SELECT (or WITH ... SELECT) statement")
        rows = self._rows(stripped)
        return {"rows": rows, "truncated": len(rows) == MAX_ROWS}

    def performance_by(self, dimension: str, days: int = 30) -> list[dict[str, Any]]:
        col = DIMENSIONS.get(dimension)
        if col is None:
            raise ServiceError(f"dimension must be one of {', '.join(DIMENSIONS)}")
        sql = f"""
            with latest as (select post_id, max(ts) ts from metric group by post_id),
                 m as (select metric.* from metric join latest using (post_id, ts))
            select {col} as key, count(distinct p.id) posts, coalesce(sum(m.views),0) views,
                   round(coalesce(sum(m.earnings),0),2) earnings
            from post p join clip cl on cl.id = p.clip_id left join campaign c on c.id = p.campaign_id
            left join m on m.post_id = p.id
            where p.status = 'live' and p.posted_at >= datetime('now', ?)
            group by key order by earnings desc, views desc
        """
        return self._rows(sql, (f"-{int(days)} days",))

    def approval_rate_by(self, dimension: str) -> list[dict[str, Any]]:
        cols = {
            "campaign": "cl.campaign_id",
            "marketplace": "c.marketplace",
            "layout": "cl.layout",
            "caption_style": "cl.caption_style",
            "score_tier": "cast(r.score_at_decision / 10 as int) * 10",
            "reason": "r.reason",
        }
        col = cols.get(dimension)
        if col is None:
            raise ServiceError(f"dimension must be one of {', '.join(cols)}")
        sql = f"""
            select {col} as key, count(*) decided,
                   round(avg(case when r.decision = 'approved' then 1.0 else 0.0 end), 3) approval_rate
            from review r join clip cl on cl.id = r.clip_id left join campaign c on c.id = cl.campaign_id
            where r.decision in ('approved', 'rejected') group by key order by decided desc
        """
        return self._rows(sql)

    def top_clips(self, n: int = 10, metric: str = "views") -> list[dict[str, Any]]:
        if metric not in ("views", "earnings"):
            raise ServiceError("metric must be views or earnings")
        sql = f"""
            with latest as (select post_id, max(ts) ts from metric group by post_id)
            select cl.id clip_id, cl.campaign_id, mo.hook, sum(m.views) views, round(sum(m.earnings),2) earnings
            from metric m join latest using (post_id, ts) join post p on p.id = m.post_id
            join clip cl on cl.id = p.clip_id join moment mo on mo.id = cl.moment_id
            group by cl.id order by {metric} desc limit ?
        """
        return self._rows(sql, (min(int(n), 50),))

    def campaign_report(self, campaign_id: int) -> dict[str, Any]:
        head = self._rows(
            "select id, title, marketplace, status, cpm, budget_left, score from campaign where id = ?",
            (campaign_id,),
        )
        if not head:
            raise ServiceError(f"campaign {campaign_id} not found")
        clips = self._rows(
            "select status, count(*) n from clip where campaign_id = ? group by status", (campaign_id,)
        )
        reviews = self._rows(
            "select r.decision, count(*) n from review r join clip c on c.id = r.clip_id where c.campaign_id = ? group by r.decision",
            (campaign_id,),
        )
        posts = self._rows(
            "select platform, status, count(*) n from post where campaign_id = ? group by platform, status",
            (campaign_id,),
        )
        money = self._rows(
            """with latest as (select post_id, max(ts) ts from metric group by post_id)
               select coalesce(sum(m.views),0) views, round(coalesce(sum(m.earnings),0),2) earnings
               from metric m join latest using (post_id, ts) join post p on p.id = m.post_id where p.campaign_id = ?""",
            (campaign_id,),
        )
        return {
            "campaign": head[0],
            "clips": clips,
            "reviews": reviews,
            "posts": posts,
            "totals": money[0] if money else {},
        }
