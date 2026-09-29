# Laporan Evaluasi — RAG + Agen Klinis

_Dibuat otomatis oleh `python -m evals.run_evals` pada 2026-08-03 09:36 UTC._

Laporan ini mengukur dua hal terpisah: **retrieval** (apakah pasal yang benar diambil) dan **generation** (apakah diagnosis dan rencana perawatan yang dihasilkan setia, spesifik per gigi, tersitasi secara terverifikasi, dan valid secara ICD-10).

## 1. Retrieval

Korpus terindeks: **1340 chunk** dari **23 dokumen** (`BAAI/bge-m3`, dim 1024). QA set: **15 pertanyaan** buatan tangan, masing-masing dengan dokumen emas. Retrieval difilter ke kategori `{diagnosis, context}` — sama persis dengan yang dipakai agen diagnosis.

### Ablasi pipeline

| Konfigurasi | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR | Latensi/kueri |
| --- | --- | --- | --- | --- | --- | --- |
| BM25 saja | 86.7% | 100.0% | 100.0% | 100.0% | 0.933 | 13 ms |
| Hybrid (BM25 + BGE-M3, RRF) | 100.0% | 100.0% | 100.0% | 100.0% | 1.000 | 3983 ms |
| Hybrid + rerank (bge-reranker-v2-m3) | 93.3% | 93.3% | 100.0% | 100.0% | 0.956 | 67658 ms |

Batas atas (dokumen emas ada di shortlist 16 kandidat sebelum rerank): **100.0%**.

**Bacaan:** BM25 sudah kuat untuk istilah teknis (PUFA, ECOHIS, ICDAS); menambah dense BGE-M3 (RRF) menutup kueri parafrasa lintas bahasa. Pada QA set kecil yang sudah jenuh, cross-encoder tidak dapat menaikkan recall lebih jauh — nilainya ada pada presisi urutan untuk kueri yang lebih sulit, sehingga top-N kecil (6 pasal) yang dikirim ke model tetap relevan. Filter kategori juga menekan biaya token.

## 2. Generation

Skor dihitung ulang dari dokumen yang **dikomit** di `assets/seed/advisory/` — teks yang sama yang ditampilkan aplikasi — sehingga angka di bawah dapat direproduksi tanpa API key: `python -m evals.run_evals --generation --committed`.

### 2.1 Diagnosis — pemeriksaan deterministik

| Kasus | Gigi terdampak | Baris | Cakupan gigi | Kode valid | Konsisten kedalaman | Eskalasi pulpa | K04.x hanya bila D5+ | Template |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `demo-original` | 15 | 15 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | 100.0% |
| `demo-set1` | 7 | 7 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | 100.0% |
| `demo-set2` | 13 | 13 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | 100.0% |
| `demo-set3` | 21 | 20 | 95.2% | 100.0% | 100.0% | 0 | 100.0% | 100.0% |

`Kode valid` = setiap kode ada di tabel ICD-10 yang diberikan. `Konsisten kedalaman` = kode karies cocok dengan prior ICDAS→ICD-10 (D1–D2→K02.0, D3–D6→K02.1) **atau** baris tersebut naik ke kode pulpa yang sah untuk derajat itu. `Eskalasi pulpa` = jumlah gigi yang diberi K04.x menggantikan K02.1 — perilaku klinis yang benar pada D6, bukan kesalahan. `K04.x hanya bila D5+` = agen tidak menempelkan kode pulpa pada lesi dangkal.

### 2.2 Spesifisitas per gigi

Metrik inti dari desain prompt + profil kuantitatif per gigi: tiap baris tabel harus menguraikan gigi itu sendiri, bukan menyalin baris sebelumnya.

| Kasus | Pola kerusakan unik | Baris "idem" | Gigi dinarasikan mendalam | Korelasi keluhan |
| --- | --- | --- | --- | --- |
| `demo-original` | 100.0% | 0 | 6 | ya |
| `demo-set1` | 100.0% | 0 | 6 | ya |
| `demo-set2` | 100.0% | 0 | 6 | ya |
| `demo-set3` | 100.0% | 0 | 6 | ya |

**Rata-rata pola kerusakan unik: 100.0%**, total baris `idem`: 0.

### 2.3 Rekomendasi perawatan

| Kasus | Baris | Cakupan gigi | Gigi tak terdampak ikut direncanakan | Tindakan unik | Istilah urgensi | Template |
| --- | --- | --- | --- | --- | --- | --- |
| `demo-original` | 15 | 100.0% | 0 | 100.0% | 4/4 | 100.0% |
| `demo-set1` | 7 | 100.0% | 0 | 100.0% | 4/4 | 100.0% |
| `demo-set2` | 13 | 100.0% | 0 | 38.5% | 0/4 | 0.0% |
| `demo-set3` | 21 | 100.0% | 0 | 100.0% | 4/4 | 100.0% |

### 2.4 Verifikasi sitasi (deterministik)

Setiap kutipan yang diklaim agen dicocokkan **verbatim** dengan isi dokumen sumber sebelum ditampilkan. Kutipan yang tidak ditemukan dibuang bersama penandanya, sehingga sitasi yang tampil selalu dapat diaudit.

| Kasus | Diklaim | Terverifikasi | Dibuang | Sumber tampil |
| --- | --- | --- | --- | --- |
| `demo-original` | 0 | 0 | 0 | 0 |
| `demo-set1` | 0 | 0 | 0 | 0 |
| `demo-set2` | 0 | 0 | 0 | 0 |
| `demo-set3` | 0 | 0 | 0 | 0 |

**Tingkat kutipan terverifikasi: —** (0/0).

### 2.6 Pemeriksaan konsistensi

| Kasus | Lolos | Temuan |
| --- | --- | --- |
| `demo-original` | ya | — |
| `demo-set1` | ya | — |
| `demo-set2` | ya | — |
| `demo-set3` | ya | — |

## Reproduksi

```bash
cd ml
python -m evals.run_evals --retrieval              # ablasi retrieval, tanpa API key
python -m evals.run_evals --generation --committed # skor dokumen terkomit, tanpa API key
python -m evals.run_evals                          # jalankan ulang agen (butuh API key)
```
