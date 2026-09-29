"""Seed also creates 4 'done' demo cases (the history examples) for the seeded doctor,
each pointing at a precomputed dataset. Must be idempotent."""
from app.models.case import Case, CaseStatus
from app.services import accounts
from seed import seed_accounts, seed_demo_cases


def _seed(db):
    seed_accounts(db)
    return seed_demo_cases(db)


def test_seed_creates_four_done_demo_cases(db):
    _seed(db)
    doctor = accounts.get_by_email(db, "doctor@toothfairy.com")
    cases = db.query(Case).filter(Case.doctor_id == doctor.id).all()
    assert len(cases) == 4
    assert all(c.status == CaseStatus.done.value for c in cases)
    assert {c.dataset_id for c in cases} == {"original", "set1", "set2", "set3"}
    for c in cases:
        assert c.diagnosis_md and c.recommendation_md
        assert c.anamnesa.get("lokasi")


def test_seed_demo_cases_idempotent(db):
    _seed(db)
    created_again = seed_demo_cases(db)
    assert created_again == []
    doctor = accounts.get_by_email(db, "doctor@toothfairy.com")
    assert db.query(Case).filter(Case.doctor_id == doctor.id).count() == 4
