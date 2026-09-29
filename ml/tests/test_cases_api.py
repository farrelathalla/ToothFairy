from app.models.user import Role
from app.security import create_token
from app.services import accounts

ANAMNESA = {
    "lokasi": "Geraham kiri bawah",
    "quality": "Cenut-cenut",
    "severity": "Skala 6",
    "chronology": "3 hari",
    "setting": "Saat mengunyah",
    "aggravating_alleviating": "Manis memperparah",
    "associated": "Gusi bengkak",
    "pernah_ke_drg_lain": "Belum",
    "obat_digunakan": "Paracetamol",
    "tindakan_sebelumnya": "Belum",
    "penyakit_sistemik": "Tidak ada",
    "pernah_menunda": "Ya",
    "alasan_kuat": "Sulit tidur",
}


def _token(db, role=Role.doctor, email=None):
    email = email or f"{role.value}@x.io"
    u = accounts.create_user(db, email=email, name=role.value, password="secret1", role=role)
    return create_token(u)


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _create_case(client, tok, patient="Anak A"):
    return client.post(
        "/cases", headers=_auth(tok), json={"patient_name": patient, "anamnesa": ANAMNESA}
    )


def test_create_case_requires_doctor(client, db):
    admin_tok = _token(db, Role.admin)
    assert client.post("/cases", headers=_auth(admin_tok), json={"anamnesa": ANAMNESA}).status_code == 403
    assert client.post("/cases", json={"anamnesa": ANAMNESA}).status_code == 401


def test_create_case_validates_required_anamnesa(client, db):
    tok = _token(db)
    bad = dict(ANAMNESA)
    del bad["lokasi"]
    r = client.post("/cases", headers=_auth(tok), json={"anamnesa": bad})
    assert r.status_code == 422


def test_create_and_get_case(client, db):
    tok = _token(db)
    r = _create_case(client, tok)
    assert r.status_code == 201
    case = r.json()
    assert case["status"] == "draft"
    assert case["anamnesa"]["lokasi"] == "Geraham kiri bawah"

    got = client.get(f"/cases/{case['id']}", headers=_auth(tok))
    assert got.status_code == 200
    assert got.json()["id"] == case["id"]


def test_list_cases_scoped_to_doctor(client, db):
    t1 = _token(db, Role.doctor, "d1@x.io")
    t2 = _token(db, Role.doctor, "d2@x.io")
    _create_case(client, t1, "P1")
    _create_case(client, t1, "P2")
    _create_case(client, t2, "P3")
    assert len(client.get("/cases", headers=_auth(t1)).json()) == 2
    assert len(client.get("/cases", headers=_auth(t2)).json()) == 1


def test_get_other_doctors_case_404(client, db):
    t1 = _token(db, Role.doctor, "d1@x.io")
    t2 = _token(db, Role.doctor, "d2@x.io")
    cid = _create_case(client, t1).json()["id"]
    assert client.get(f"/cases/{cid}", headers=_auth(t2)).status_code == 404


def test_upload_images_saves_slots(client, db):
    tok = _token(db)
    cid = _create_case(client, tok).json()["id"]
    r = client.post(
        f"/cases/{cid}/images",
        headers=_auth(tok),
        files={
            "up": ("up.jpg", b"\xff\xd8fakejpeg", "image/jpeg"),
            "panoramic": ("pano.png", b"\x89PNGfake", "image/png"),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "uploaded"
    slots = {i["view_key"]: i for i in body["images"]}
    assert set(slots) == {"up", "panoramic"}
    assert slots["up"]["url"] == f"/media/{cid}/up.jpg"


def test_upload_rejects_non_image(client, db):
    tok = _token(db)
    cid = _create_case(client, tok).json()["id"]
    r = client.post(
        f"/cases/{cid}/images",
        headers=_auth(tok),
        files={"up": ("note.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_upload_no_files_400(client, db):
    tok = _token(db)
    cid = _create_case(client, tok).json()["id"]
    # send an empty unnamed part so multipart parsing succeeds but no slot is filled
    r = client.post(f"/cases/{cid}/images", headers=_auth(tok), data={"note": "x"})
    assert r.status_code == 400
