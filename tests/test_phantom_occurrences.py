"""An occurrence Things already created must not be projected again.

Things creates every occurrence before the template's next instance date. When
the created copy is later moved to another day or deleted, its date drops out of
existing_dates, and the projection must not bring it back as a preview.
"""
from datetime import date

from things_mcp import recurrence
from tests.test_recurring_visibility import (  # noqa: F401  (fixtures)
    make_rule,
    no_real_recurrence_templates,
    things_db,
)

FRI = date(2026, 11, 20)


def _dates(things_db, start, end):
    templates = recurrence.fetch_templates(things_db.filepath)
    return [t["start_date"] for t in recurrence.recurring_occurrences(start, end, templates=templates)]


def test_moved_copy_is_not_projected_on_its_old_day(things_db):
    # Daily repeat; Things created Friday's copy, then it was deferred to Sunday.
    things_db.add_template("tpl", "Water the plants", make_rule(recurrence.UNIT_DAY),
                           next_instance=date(2026, 11, 21))
    things_db.add_instance("inst", "tpl", date(2026, 11, 22))
    assert _dates(things_db, FRI, FRI) == []


def test_deleted_copy_is_not_projected(things_db):
    things_db.add_template("tpl", "Water the plants", make_rule(recurrence.UNIT_DAY),
                           next_instance=date(2026, 11, 21))
    things_db.add_instance("inst", "tpl", FRI, trashed=1)
    assert _dates(things_db, FRI, FRI) == []


def test_occurrences_from_the_next_instance_on_are_still_projected(things_db):
    things_db.add_template("tpl", "Water the plants", make_rule(recurrence.UNIT_DAY),
                           next_instance=date(2026, 11, 21))
    things_db.add_instance("inst", "tpl", date(2026, 11, 22))
    assert _dates(things_db, FRI, date(2026, 11, 23)) == ["2026-11-21", "2026-11-23"]


def test_series_that_starts_later_is_not_projected_before_it_starts(things_db):
    # Monthly on the 1st, first copy due 2027-01-01.
    things_db.add_template("tpl", "Pay rent", make_rule(recurrence.UNIT_MONTH,
                           constraints=[{"dy": 0}], anchor=date(2027, 1, 1)),
                           next_instance=date(2027, 1, 1))
    assert _dates(things_db, FRI, date(2027, 2, 1)) == ["2027-01-01", "2027-02-01"]
