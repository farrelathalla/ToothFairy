"""The LLM/RAG layer is stubbed (Phase 8 wires the real graph). For now graph.run must
return deterministic, non-empty markdown for both diagnosis and recommendation so the
results UI has something to render."""
from app.llm import graph
from app.services import accounts, cases

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


def test_graph_run_returns_markdown(db):
    doc = accounts.create_user(db, email="d@x.io", name="D", password="secret1")
    case = cases.create_case(db, doc, patient_name="Anak A", anamnesa=ANAMNESA)
    out = graph.run(case)
    assert out["diagnosis_md"].strip()
    assert out["recommendation_md"].strip()
    # markdown-ish: has a heading
    assert out["diagnosis_md"].lstrip().startswith("#")
    assert "TODO(LLM)" in out["diagnosis_md"]


def test_graph_run_is_deterministic(db):
    doc = accounts.create_user(db, email="d@x.io", name="D", password="secret1")
    case = cases.create_case(db, doc, patient_name="Anak A", anamnesa=ANAMNESA)
    assert graph.run(case) == graph.run(case)
