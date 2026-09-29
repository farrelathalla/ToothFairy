# Safety, privacy and security

ToothFairy processes children's medical images and produces text a clinician may act on. This
document states what the system does and does not claim, what could go wrong, and what is
implemented in code to contain it.

---

## 1. Intended use and clinical status

**ToothFairy is a decision-support tool for a qualified dentist. It is not a medical device,
it does not diagnose autonomously, and it must not be used to make treatment decisions without
an in-person clinical examination.**

|                      |                                                                                                                                                              |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Intended user        | A licensed dentist or dental student under supervision                                                                                                       |
| Intended setting     | Clinic screening and patient communication, with the patient present                                                                                         |
| Intended subject     | Paediatric patients, deciduous and mixed dentition                                                                                                           |
| **Not** intended for | Self-diagnosis by patients or parents, unsupervised triage, billing or insurance coding without review, any use where a clinician does not review the output |

Every generated document is a **draft for a clinician to verify**. The system prompts state
this explicitly, the treatment plan is written conditionally ("if vitality testing shows X,
then Y"), and the user interface labels the advisory cards as automatically generated.

### Regulatory position

The product is presented as an academic and competition prototype. It has no CE mark, no FDA
clearance, and no Indonesian Kemenkes AKD/AKL registration. Deploying it in a real clinic
would require, at minimum, a clinical evaluation, a registered quality management system, and
an assessment against the local medical-device regulations for software. Nothing in this
repository should be read as a claim that those steps have been taken.

---

## 2. Privacy and data protection

The system handles intraoral photographs, panoramic radiographs, and a free-text clinical
history, health data about **minors**, which is the most strictly protected category under
Indonesia's PDP Law (UU No. 27/2022) and comparable to special-category data under GDPR
Article 9.

### Data minimisation, in code

- **The anamnesa accepts a fixed field list.** Any other key in the request is dropped rather
  than stored (`gateway/internal/httpapi/cases.go`). An open JSON blob is exactly how a
  national ID number or a phone number ends up in a database nobody remembers to purge. There
  is a test for this.
- **No date of birth, address, phone number or national ID is collected anywhere.** A patient
  name field exists and is optional, and the demo data uses first names and an age.
- **Nothing patient-identifying enters a JWT.** Tokens carry a user id, a role and an expiry.
- **Access logs record the request path only**, never the query string or the body, so case
  ids, patient names and media tokens do not reach log aggregation.

### Storage and deletion

- Patient photos live under `UPLOAD_DIR/<case-id>/`, and derived results under
  `RESULTS_DIR/<case-id>/`. Neither is committed to version control.
- `DELETE /cases/{id}` removes the database row, the uploaded photographs **and** the derived
  results directory. A "delete" that leaves the images on disk is not a deletion. This is the
  endpoint a data-erasure request lands on.
- Deleting a user cascades to their cases and images at the database level.

### Data leaving the machine

| Data                               | Leaves the deployment?                                                              |
| ---------------------------------- | ----------------------------------------------------------------------------------- |
| Intraoral / panoramic images       | **No.** All vision inference is local. Images are never sent to any model provider. |
| RAG query text                     | **No.** The embedder and reranker are open-weight models running locally.           |
| Anamnesa text + per-tooth findings | **Yes**, only when `LLM_ENABLED=1`, and only to the configured model provider.      |
| Patient name                       | Only if the clinician entered one and the advisory layer is enabled.                |

The advisory layer is **off by default**. With `LLM_ENABLED=0` the whole product works,
including the detection, the 3D reconstruction and a deterministic summary, with no outbound
network call at all. That is the recommended configuration for any deployment that has not completed a data
processing agreement with the model provider.

`OPENAI_BASE_URL` allows pointing the client at a self-hosted or regional endpoint where data
residency requires it.

### Consent

Consent is a clinical workflow obligation, not something software can assert. A real deployment
must obtain and record guardian consent for image capture and for automated processing before
a case is created.

---

## 3. Handling of AI failure modes

### Hallucination

| Mitigation                                                                                                                                                      | Where                                    |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Every claimed citation is verified as a **verbatim substring** of the document it is attributed to, and unverifiable quotes are dropped along with their marker | `ml/app/llm/citations.py`                |
| ICD-10 codes are constrained to a supplied table, and codes outside it are flagged                                                                              | `ml/app/llm/icd10.py`, consistency check |
| The prompt forbids inventing figures, prevalences, dosages or study names not present in the attached passages                                                  | `prompts/common.py`                      |
| Dosages and product protocols require a citation, and without one the agent may name the procedure but not the numbers                                          | `prompts/recommendation.py`              |
| Abstention is required over guessing, with an explicit limitations section                                                                                      | both system prompts                      |
| The verified/rejected citation ratio is measured per case                                                                                                       | `ml/evals/`                              |
| A judge labels each atomic claim `DOKUMEN` / `INPUT` / `KLINIS` / `SALAH`, and faithfulness is `1 - SALAH/total`                                                | `ml/evals/judge.py`                      |

### Over-confidence

The per-tooth confidence rating is **derived from detector agreement**, not from the model's
prose, and depends on how many detectors found the lesion, their scores, whether the tooth's
position had to be interpolated, and whether the panoramic corroborates. A tooth carried by one
weak detector
is never presented with the same certainty as one three detectors agree on.

### Bias

- **Population.** The vision models are trained on paediatric dental datasets whose
  demographic composition is not fully characterised. Performance on populations, imaging
  hardware or lighting conditions unlike the training data is unknown and may be worse.
- **Skin, gingival and enamel tone.** Severity uses a _relative_ darkness measure (lesion
  luminance against healthy enamel across the same arch) rather than absolute thresholds.
  This is deliberately exposure- and tone-invariant, and it replaced an earlier absolute-
  threshold approach that failed on dark photographs. It is a mitigation, not a proof of
  fairness, and a stratified evaluation across skin tones has **not** been performed.
- **Language.** The interface and all generated text are Indonesian. The retrieval corpus is
  mixed Indonesian/English, and the embedder is multilingual.
- **Recall asymmetry.** Teeth not visible in any uploaded view are reported healthy. Under-
  photographed regions therefore look healthier than they are, and the generated limitations
  section is required to say so.

### Automation bias

The greater risk in practice is not that the model is wrong but that a busy clinician stops
checking. Countermeasures include a confidence column that is per tooth rather than global, a
mandatory limitations section, a verbatim quote shown on every citation to audit against, a
treatment plan conditional on chair-side findings the software cannot observe, and a
consistency report shown to the user rather than kept as a silent internal gate.

---

## 4. Security

### Authentication and authorisation

- bcrypt password hashing, with passwords over bcrypt's 72-byte limit **rejected** rather than
  silently truncated into a weaker hash.
- HS256 JWTs with the algorithm pinned at verification, so an `alg: none` token cannot be
  forged. There is a test that attempts exactly that.
- Every request re-loads the user, so **deactivating an account revokes access immediately**
  even while its token is still cryptographically valid.
- **Role-based access control** lets doctors reach only their own cases, while admins manage
  accounts but cannot create cases. A case belonging to another doctor returns **404, not
  403**, since a 403 would confirm the id exists.
- Login answers identically for an unknown email and a wrong password, and spends the hashing
  time either way, so the endpoint is not an account-enumeration oracle.
- The last active admin cannot be deleted or demoted, and an admin cannot delete themselves.

### Upload handling

- Content type is **sniffed from the bytes**, not read from the client's header.
- The stored filename is derived entirely from the validated view key and the sniffed type, so
  a crafted filename cannot traverse directories or land as an executable extension.
- Per-file and whole-request size limits.
- One image per view slot, and re-uploading replaces rather than accumulates.

### Patient media

`/media` is **authenticated**, so patient photographs are not public. Because an `<img>` element
cannot send an Authorization header and the session cookie is `SameSite=Lax`, that route also
accepts the session token as a query parameter. The usual downsides of a token in a URL are
closed off deliberately. Responses are `no-store`, `Referrer-Policy: no-referrer` prevents the
URL leaking onward, the access log omits query strings, and the service worker is configured
`NetworkOnly` for `/media` so an installed PWA on a shared clinic device retains no
identifiable images after logout. Ownership is checked on every request, and the resolved path
is verified to remain inside the upload root.

### Transport and service boundary

- Security headers on every response, including `nosniff`, `X-Frame-Options: DENY`, and
  `no-referrer`.
- CORS reflects only allow-listed origins and never emits a wildcard on a credentialed API.
- Per-IP rate limiting, with `X-Forwarded-For` honoured **only** when the deployment declares it
  sits behind a trusted proxy, so a client cannot spoof its way around the limiter.
- The internal ML API requires a shared secret compared in constant time, and the service logs
  a warning at boot if it is unset.
- `ENV=production` refuses to start with a development JWT secret or a missing internal key.

### Secrets

No secret is committed. `.env` files are git-ignored, `.env.example` documents every variable,
and API keys are read only from the environment. **If a key is ever pasted into an issue, a
commit or a chat, rotate it**, since the provider dashboard is the only reliable revocation.

---

## 5. Error and failure handling

| Condition                                 | Behaviour                                                                                                                            |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| ML service unreachable                    | Gateway `/health` reports the dependency as down while staying healthy itself, and the case fails with a readable Indonesian message |
| Analysis stream truncated                 | Treated as failure, never marked "done" with no results                                                                              |
| Analysis fails                            | Case moves to `failed` with the reason, and the doctor can retry                                                                     |
| Advisory fails or is rate-limited         | Case still completes with detection + 3D, and the advisory card is empty and the reason recorded                                     |
| Model response truncated at the token cap | Raised as an error and replaced by the deterministic stub, since half a clinical table is worse than none                            |
| Retrieval unavailable or index missing    | Degrades to BM25-only, then to no passages, and never fails the case                                                                 |
| Job queue saturated                       | `503` with `Retry-After` rather than an unbounded wait                                                                               |
| Server restarted mid-analysis             | Interrupted cases are reset to `failed` at boot instead of polling forever                                                           |
| Panic in any handler or worker            | Recovered, logged with a request id, returned as a generic 500, and internal detail never reaches the client                         |

Client-facing messages are in Indonesian and free of stack traces, SQL and file paths.

---

## 6. Known limitations

1. Vision model accuracy has not been validated on an external, prospectively collected
   clinical cohort.
2. No stratified fairness evaluation across skin tones, age groups or imaging devices.
3. Teeth absent from every uploaded view are assumed healthy unless the panoramic disagrees.
4. Proximal lesions, lesions under existing restorations, and pits obscured by debris are
   commonly missed by photographic detection.
5. The 3D reconstruction is an anatomically plausible visualisation for communication and
   planning, and it is **not** a metric reconstruction and must not be measured against.
6. The generated text is not a substitute for periapical radiographs, vitality testing,
   percussion or palpation.
7. The advisory layer's quality is measured on four demo cases, which is a smoke test, not a
   clinical validation.
8. SQLite suits a single clinic, and a multi-site deployment should move the store to Postgres.

---

## 7. Reporting a security issue

Please open a private report to the repository owner rather than a public issue. Include the
affected endpoint, a reproduction, and the impact you believe it has.
