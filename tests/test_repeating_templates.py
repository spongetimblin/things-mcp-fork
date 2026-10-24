"""Tests for get_repeating_templates (things-mcp #57).

The tool lists the repeating to-do templates themselves, which things.py hides
from every query, with each one's repeat rule and next date. Occurrence
projection is covered in test_recurring_visibility.py.
"""

import json
from datetime import date, timedelta

import pytest

from things_mcp import recurrence
from things_mcp.formatters import format_repeating_template
from tests.test_recurring_visibility import (  # noqa: F401  (fixtures)
    make_rule,
    no_real_recurrence_templates,
    things_db,
)

TODAY = date(2026, 3, 10)


def _template(uuid="tpl-1", title="Water the plants", unit=recurrence.UNIT_WEEK,
              interval=1, repeat_type=0, next_instance=None, existing=(),
              paused=False, notes=None, project=None, lead_days=0):
    rule = recurrence.parse_recurrence_rule(
        make_rule(unit, interval=interval, repeat_type=repeat_type,
                  anchor=date(2020, 1, 1), lead_days=lead_days)
    )
    return {
        "uuid": uuid, "title": title, "notes": notes, "project": project,
        "area": None, "heading": None, "rule": rule,
        "next_instance": next_instance, "existing_dates": set(existing),
        "paused": paused,
    }


class TestDescribeTemplate:
    """One template becomes one JSON-safe summary."""

    def test_uses_things_own_next_date_when_present(self):
        item = recurrence.describe_template(
            _template(next_instance=date(2026, 3, 16)), today=TODAY)
        assert item["next_date"] == "2026-03-16"
        assert item["type"] == "repeating-template"
        assert item["paused"] is False
        assert item["repeat"] == {
            "type": "fixed_schedule", "unit": "week", "interval": 1,
            "lead_days": 0, "end_date": None, "count_limit": 0,
        }

    def test_fixed_schedule_without_next_date_projects_the_first_one(self):
        item = recurrence.describe_template(
            _template(unit=recurrence.UNIT_DAY), today=TODAY)
        assert item["next_date"] == TODAY.isoformat()

    def test_after_completion_without_next_date_stays_unknown(self):
        item = recurrence.describe_template(_template(repeat_type=1), today=TODAY)
        assert item["next_date"] is None
        assert item["repeat"]["type"] == "after_completion"

    def test_materialized_dates_keep_only_today_and_later(self):
        item = recurrence.describe_template(
            _template(existing=[date(2026, 3, 2), TODAY, date(2026, 3, 16)]),
            today=TODAY)
        assert item["materialized_dates"] == ["2026-03-10", "2026-03-16"]

    def test_lead_time_and_interval_are_reported(self):
        item = recurrence.describe_template(
            _template(interval=2, lead_days=-3), today=TODAY)
        assert item["repeat"]["interval"] == 2
        assert item["repeat"]["lead_days"] == -3

    def test_is_json_safe(self):
        item = recurrence.describe_template(
            _template(existing=[TODAY], next_instance=TODAY), today=TODAY)
        json.dumps(item)


class TestPausedTemplates:
    """fetch_templates leaves paused templates out unless asked."""

    def test_paused_templates_are_excluded_by_default(self, things_db):
        things_db.add_template("tpl-p", "Paused", make_rule(recurrence.UNIT_DAY), paused=1)
        things_db.add_template("tpl-a", "Active", make_rule(recurrence.UNIT_DAY))
        templates = recurrence.fetch_templates(things_db.filepath)
        assert [t["title"] for t in templates] == ["Active"]
        assert templates[0]["paused"] is False

    def test_include_paused_returns_them_flagged(self, things_db):
        things_db.add_template("tpl-p", "Paused", make_rule(recurrence.UNIT_DAY), paused=1)
        things_db.add_template("tpl-a", "Active", make_rule(recurrence.UNIT_DAY))
        templates = recurrence.fetch_templates(things_db.filepath, include_paused=True)
        assert {t["title"]: t["paused"] for t in templates} == {
            "Paused": True, "Active": False}


class TestFormatter:

    def test_text_summarizes_rule_and_next_date(self):
        item = recurrence.describe_template(
            _template(interval=2, lead_days=-3, paused=True,
                      next_instance=date(2026, 3, 16), existing=[date(2026, 3, 16)]),
            today=TODAY)
        text = format_repeating_template(item)
        assert "Type: repeating-template" in text
        assert "Repeats: every 2 weeks, shown 3 days early" in text
        assert "Next Date: 2026-03-16" in text
        assert "Already Created: 2026-03-16" in text
        assert "Paused: yes" in text

    def test_after_completion_without_next_date(self):
        item = recurrence.describe_template(_template(repeat_type=1), today=TODAY)
        text = format_repeating_template(item)
        assert "Repeats: every week after completion" in text
        assert "Next Date: after the open instance is completed" in text
        assert "Paused" not in text


class TestGetRepeatingTemplatesTool:
    """The server tool lists, filters and paginates templates."""

    @staticmethod
    def _soon_and_later():
        today = date.today()
        return [
            _template(uuid="b", title="Later", next_instance=today + timedelta(days=9)),
            _template(uuid="a", title="Sooner", next_instance=today + timedelta(days=2)),
            _template(uuid="c", title="Someday", repeat_type=1),
        ]

    @pytest.mark.asyncio
    async def test_lists_templates_sorted_by_next_date(self, mocker):
        from things_mcp.server import get_repeating_templates
        fetch = mocker.patch("things_mcp.recurrence.fetch_templates",
                             return_value=self._soon_and_later())
        result = await get_repeating_templates()
        items = result.structured_content["items"]
        assert [i["title"] for i in items] == ["Sooner", "Later", "Someday"]
        assert all(i["type"] == "repeating-template" for i in items)
        fetch.assert_called_once_with(include_paused=False)

    @pytest.mark.asyncio
    async def test_days_window_filters_on_next_date(self, mocker):
        from things_mcp.server import get_repeating_templates
        mocker.patch("things_mcp.recurrence.fetch_templates",
                     return_value=self._soon_and_later())
        result = await get_repeating_templates(days=3)
        assert [i["title"] for i in result.structured_content["items"]] == ["Sooner"]

    @pytest.mark.asyncio
    async def test_include_paused_is_passed_through(self, mocker):
        from things_mcp.server import get_repeating_templates
        fetch = mocker.patch("things_mcp.recurrence.fetch_templates", return_value=[])
        result = await get_repeating_templates(include_paused=True)
        fetch.assert_called_once_with(include_paused=True)
        assert result.structured_content["items"] == []

    @pytest.mark.asyncio
    async def test_pagination_applies(self, mocker):
        from things_mcp.server import get_repeating_templates
        mocker.patch("things_mcp.recurrence.fetch_templates",
                     return_value=self._soon_and_later())
        result = await get_repeating_templates(limit=2)
        assert result.structured_content["count"] == 2
        assert result.structured_content["total"] == 3

    @pytest.mark.asyncio
    async def test_negative_days_is_an_error(self):
        from things_mcp.server import get_repeating_templates
        result = await get_repeating_templates(days=-1)
        assert "error" in result.structured_content

    @pytest.mark.asyncio
    async def test_read_failure_is_an_error_not_a_crash(self, mocker):
        from things_mcp.server import get_repeating_templates
        mocker.patch("things_mcp.recurrence.fetch_templates",
                     side_effect=RuntimeError("boom"))
        result = await get_repeating_templates()
        assert "error" in result.structured_content
