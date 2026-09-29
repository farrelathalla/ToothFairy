"""POST /cases/{id}/run enqueues inference; GET /cases/{id}/status polls progress."""
import time

from app.models.user import Role
from app.security import create_token
from app.services import accounts

ANAMNESA = {
    "lokasi": "Geraham kiri bawah", "quality": "Cenut-cenut", "severity": "Skala 6",
    "chronology": "3 hari", "setting": "Saat mengunyah",
    "aggravating_alleviating": "Manis", "associated": "Bengkak",
    "pernah_ke_drg_lain": "Belum", "obat_digunakan": "Paracetamol",
    "tindakan_sebelumnya": "Belum", "penyakit_sistemik": "Tidak ada",
    "pernah_menunda": "Ya", "alasan_kuat": "Sulit tidur",
}


def _token(db, role=Role.doctor, email=None):
    email = email or f"{role.value}@x.io"
    u = accounts.create_user(db, email=email, name=role.value, password="secret1", role=role)
    return create_token(u)


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _case_with_image(client, tok):
    cid = client.post("/cases", headers=_auth(tok),
                      json={"patient_name": "P", "anamnesa": ANAMNESA}).json()["id"]
    client.post(f"/cases/{cid}/images", headers=_auth(tok),
                files={"up": ("up.jpg", b"\xff\xd8fakejpeg", "image/jpeg")})
    return cid


def test_run_requires_images(client, db):
    tok = _token(db)
    cid = client.post("/cases", headers=_auth(tok),
                      json={"patient_name": "P", "anamnesa": ANAMNESA}).json()["id"]
    r = client.post(f"/cases/{cid}/run", headers=_auth(tok))
    assert r.status_code == 400


def test_run_enqueues_and_status_reaches_done(client, db):
    tok = _token(db)
    cid = _case_with_image(client, tok)
    r = client.post(f"/cases/{cid}/run", headers=_auth(tok))
    assert r.status_code == 202
    assert r.json()["status"] == "queued"

    deadline = time.time() + 15
    status = None
    while time.time() < deadline:
        body = client.get(f"/cases/{cid}/status", headers=_auth(tok)).json()
        status = body["status"]
        assert 0 <= body["progress"] <= 100
        if status in ("done", "failed"):
            break
        time.sleep(0.1)
    assert status == "done"

    got = client.get(f"/cases/{cid}", headers=_auth(tok)).json()
    assert got["dataset_id"]
    assert got["diagnosis_md"]


def test_run_blocked_for_admin_and_cross_doctor(client, db):
    doc_tok = _token(db, Role.doctor, "doc@x.io")
    cid = _case_with_image(client, doc_tok)

    admin_tok = _token(db, Role.admin)
    assert client.post(f"/cases/{cid}/run", headers=_auth(admin_tok)).status_code == 403

    other = _token(db, Role.doctor, "other@x.io")
    assert client.post(f"/cases/{cid}/run", headers=_auth(other)).status_code == 404
