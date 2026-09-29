import pytest

from app.models.case import CaseStatus
from app.services import accounts, cases
from app.services.errors import CaseNotFound, InvalidImage

ANAMNESA = {
    "lokasi": "Gigi geraham kiri bawah",
    "quality": "Nyeri cenut-cenut",
    "severity": "Skala 6, mengganggu tidur",
    "chronology": "Sejak 3 hari, tiap malam",
    "setting": "Saat mengunyah dan diam",
    "aggravating_alleviating": "Parah saat makan manis; reda dengan obat",
    "associated": "Gusi sedikit bengkak",
    "pernah_ke_drg_lain": "Belum",
    "obat_digunakan": "Paracetamol",
    "tindakan_sebelumnya": "Belum ada",
    "penyakit_sistemik": "Tidak ada",
    "pernah_menunda": "Ya, 2 bulan",
    "alasan_kuat": "Nyeri makin parah dan sulit tidur",
}


def _doctor(db, email="doc@x.io"):
    return accounts.create_user(db, email=email, name="Doc", password="secret1")


def test_create_case_persists_anamnesa(db):
    doc = _doctor(db)
    case = cases.create_case(db, doc, patient_name="Anak A", anamnesa=ANAMNESA)
    assert case.id.startswith("case-")
    assert case.status == CaseStatus.draft.value
    assert case.patient_name == "Anak A"
    assert case.anamnesa["lokasi"] == "Gigi geraham kiri bawah"
    assert case.anamnesa["alasan_kuat"].startswith("Nyeri")


def test_list_cases_is_doctor_scoped(db):
    d1, d2 = _doctor(db, "d1@x.io"), _doctor(db, "d2@x.io")
    cases.create_case(db, d1, patient_name="P1", anamnesa=ANAMNESA)
    cases.create_case(db, d1, patient_name="P2", anamnesa=ANAMNESA)
    cases.create_case(db, d2, patient_name="P3", anamnesa=ANAMNESA)
    assert len(cases.list_cases(db, d1)) == 2
    assert len(cases.list_cases(db, d2)) == 1


def test_get_case_cross_doctor_raises(db):
    d1, d2 = _doctor(db, "d1@x.io"), _doctor(db, "d2@x.io")
    case = cases.create_case(db, d1, patient_name="P", anamnesa=ANAMNESA)
    assert cases.get_case(db, d1, case.id).id == case.id
    with pytest.raises(CaseNotFound):
        cases.get_case(db, d2, case.id)
    with pytest.raises(CaseNotFound):
        cases.get_case(db, d1, "case-missing")


def test_save_image_writes_file_and_row_and_sets_status(db):
    doc = _doctor(db)
    case = cases.create_case(db, doc, patient_name="P", anamnesa=ANAMNESA)
    img = cases.save_image(
        db, case, "up", filename="up.jpg", content_type="image/jpeg", data=b"\xff\xd8fakejpeg"
    )
    assert img.path == f"{case.id}/up.jpg"
    from app.config import settings

    assert (settings.upload_dir / img.path).exists()
    assert case.status == CaseStatus.uploaded.value


def test_reupload_replaces_same_slot(db):
    doc = _doctor(db)
    case = cases.create_case(db, doc, patient_name="P", anamnesa=ANAMNESA)
    cases.save_image(db, case, "up", filename="a.jpg", content_type="image/jpeg", data=b"one")
    cases.save_image(db, case, "up", filename="b.png", content_type="image/png", data=b"two-bytes")
    ups = [i for i in case.images if i.view_key == "up"]
    assert len(ups) == 1  # replaced, not duplicated
    from app.config import settings

    assert (settings.upload_dir / ups[0].path).read_bytes() == b"two-bytes"


def test_save_image_rejects_bad_input(db):
    doc = _doctor(db)
    case = cases.create_case(db, doc, patient_name="P", anamnesa=ANAMNESA)
    with pytest.raises(InvalidImage):
        cases.save_image(db, case, "up", filename="x.txt", content_type="text/plain", data=b"x")
    with pytest.raises(InvalidImage):
        cases.save_image(db, case, "up", filename="x.jpg", content_type="image/jpeg", data=b"")
    with pytest.raises(InvalidImage):
        cases.save_image(db, case, "nope", filename="x.jpg", content_type="image/jpeg", data=b"x")
    with pytest.raises(InvalidImage):
        cases.save_image(
            db, case, "up", filename="x.jpg", content_type="image/jpeg",
            data=b"0" * (26 * 1024 * 1024),
        )
