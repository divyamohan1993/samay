# CBOM schema mapping + stylized India-DPI estate

Research deliverable for SAMAY / `pqcsched`. Two parts:

1. **Part A** — CycloneDX 1.6 CBOM → `Asset` field mapping, plus a documented default model for the attributes CBOM does **not** carry. Verified against the CycloneDX 1.6 JSON schema that ships inside `cyclonedx-python-lib` 11.10 (the library the tool ingests with).
2. **Part B** — a stylized **India Digital Public Infrastructure (DPI)** estate (UPI / Aadhaar / DigiLocker / eSign + the CCA India PKI), built from public architecture descriptions, as a seed for the case-study `Instance`.

Companion artifacts: **`research/sample.cbom.json`** — a small, schema-valid CBOM (Part A §A.5); **`research/dpi-estate.json`** — the machine-readable, feasibility-checked India-DPI estate that the Part B table is generated from (Part B §B.5).

> **Reality note (per AGENTS.md):** the DPI estate is a *scenario reconstructed from public documents*, not internal or proprietary data. Crypto facts (algorithms, key sizes, cert hierarchy) are cited to primary sources. Where a number is not publicly documented it is flagged `[ASSUMPTION]`. The `criticality`, `shelf_life`, `cost`, and `deadline` values are **modeling choices**, not facts about the systems.

---

## Part A — CycloneDX 1.6 CBOM → `Asset` mapping

### A.1 What a CBOM is, structurally

A CBOM is an ordinary CycloneDX BOM (`bomFormat: "CycloneDX"`, `specVersion: "1.6"`) whose cryptographic items are `components` of `type: "cryptographic-asset"`, each carrying a `cryptoProperties` object. Relationships are carried in the top-level `dependencies` array. CBOM (the cryptographic profile) was introduced in CycloneDX **1.6** (June 2024); the design originated in IBM's CBOM work that was contributed to CycloneDX. [1][2][3][4]

The single discriminator inside `cryptoProperties` is **`assetType`**, whose enum (verified verbatim from the bundled 1.6 schema) is exactly:

```
"algorithm" | "certificate" | "protocol" | "related-crypto-material"
```

Each value selects one detail object: `algorithmProperties`, `certificateProperties`, `protocolProperties`, or `relatedCryptoMaterialProperties`. There is also a free `oid` string. [1][5]

#### Verified field inventory (CycloneDX 1.6, `bom-1.6` schema bundled in `cyclonedx-python-lib` 11.10)

**`cryptoProperties`** → `assetType`, `algorithmProperties`, `certificateProperties`, `protocolProperties`, `relatedCryptoMaterialProperties`, `oid`.

**`algorithmProperties`** (the object the scheduler reads most):
| field | type / enum (1.6) |
|---|---|
| `primitive` | `drbg, mac, block-cipher, stream-cipher, signature, hash, pke, xof, kdf, key-agree, kem, ae, combiner, other, unknown` |
| `parameterSetIdentifier` | string (e.g. `"2048"`, `"P-256"`, `"512"`) |
| `curve` | string (e.g. `"P-256"`) |
| `executionEnvironment` | `software-plain-ram, software-encrypted-ram, software-tee, hardware, other, unknown` |
| `implementationPlatform` | `generic, x86_32, x86_64, armv7-a, armv7-m, armv8-a, armv8-m, armv9-a, armv9-m, s390x, ppc64, ppc64le, other, unknown` |
| `certificationLevel` | array of `none, fips140-1-l1…l4, fips140-2-l1…l4, fips140-3-l1…l4, cc-eal1…cc-eal7(+), other, unknown` |
| `mode` | `cbc, ecb, ccm, gcm, cfb, ofb, ctr, other, unknown` |
| `padding` | `pkcs5, pkcs7, pkcs1v15, oaep, raw, other, unknown` |
| `cryptoFunctions` | array of `generate, keygen, encrypt, decrypt, digest, tag, keyderive, sign, verify, encapsulate, decapsulate, other, unknown` |
| `classicalSecurityLevel` | integer (bits, e.g. 112/128/256) |
| `nistQuantumSecurityLevel` | integer (**0** = not quantum-secure; **1/2/3/4/5** = NIST PQC category) |

**`certificateProperties`**: `subjectName`, `issuerName`, `notValidBefore`, `notValidAfter`, `signatureAlgorithmRef` (ref), `subjectPublicKeyRef` (ref), `certificateFormat`, `certificateExtension`.

**`protocolProperties`**: `type` (`tls, ssh, ipsec, ike, sstp, wpa, other, unknown`), `version`, `cipherSuites[]` (each `{name, algorithms[] (refs), identifiers[]}`), `ikev2TransformTypes`, `cryptoRefArray` (refs).

**`relatedCryptoMaterialProperties`**: `type` (`private-key, public-key, secret-key, key, ciphertext, signature, digest, initialization-vector, nonce, seed, salt, shared-secret, tag, additional-data, password, credential, token, other, unknown`), `id`, `state` (`pre-activation, active, suspended, deactivated, compromised, destroyed`), `algorithmRef` (ref), `size`, `creationDate`, …, `securedBy`.

**Top-level `dependencies[]` item**: `ref` (required) + optional `dependsOn[]` and `provides[]` (the `provides` semantics were added in 1.6 for crypto: a library "provides" a crypto-asset implementation). [1][5]

> **Spec-version pitfall (verified, load-bearing for `cbom.py`).** Several files in `CycloneDX/bom-examples/CBOM/` are tagged `specVersion 1.7` and use **newer field values** that are **invalid under 1.6** — e.g. `primitive: "ae"` is valid in both, but `algorithmFamily`, `ellipticCurve`, `executionEnvironment: "software-plain-ram"`, `implementationPlatform: "x86_64"`, and `cryptoFunctions: ["keygen","tag"]` are **1.7-era** values. `sample.cbom.json` is therefore pinned to the **1.6** enum set (e.g. `executionEnvironment: "software-plain-ram"` **is** in 1.6; `implementationPlatform: "x86_64"` **is** in 1.6; but `primitive` must be `signature`/`pke`/`kem`/`key-agree`/`ae`, never `"rsa"`/`"ecdsa"`). Always validate ingest against the schema version the file declares, not against an example. [5][6]

### A.2 Which CBOM fields map to our `Asset`

Our model (`PROJECT_BRIEF.md` §3.1, §10.1):
`Asset(id, criticality, shelf_life, cost, perf_penalty, earliest, deadline)` + `deps` (precedence) + `clusters` (co-migration).

A CBOM cryptographic-asset becomes a candidate `Asset` **only if it is quantum-vulnerable** (a decision variable). Everything else is context.

| `Asset` attribute | CBOM source (1.6) | Notes |
|---|---|---|
| `id` | `component.bom-ref` | Stable handle; also used to resolve all `*Ref` links and `dependencies`. |
| *(is decision variable?)* | `algorithmProperties.nistQuantumSecurityLevel == 0`; else inferred from `primitive` + name/family (§A.4) | Filters the candidate set. Non-vulnerable assets are kept only as dependency endpoints. |
| `criticality` | **partially**: `protocolProperties.type`/internet-facing-ness, `certificateProperties` (CA vs leaf), `relatedCryptoMaterialProperties.type` | CBOM has **no business-impact / exposure field**. Default model §A.3. |
| `shelf_life` | **not in CBOM** | Inferred from asset role (key-transport/encryption vs signature) + a data-type policy. §A.3. |
| `cost` | **not in CBOM** | Default by `assetType`/role tier. §A.3. |
| `perf_penalty` | **weakly**: `algorithmProperties.executionEnvironment` (`hardware`/`software-tee`), `implementationPlatform` (`armv7-m`/`armv8-m` ⇒ constrained), protocol type | CBOM has no latency/handshake-size field. Default by PQC replacement class. §A.3. |
| `earliest` | **not in CBOM** | Inferred from `assetType`/protocol + a PQC-availability profile (§A.3). |
| `deadline` | **not in CBOM directly** (`certificateProperties.notValidAfter` is a *cert expiry*, not a regulatory PQC deadline) | From a policy profile (CNSA 2.0 / NIST IR / India NQM). `notValidAfter` may be used as a *soft* hint. §A.3. |
| `deps` (precedence `j→i`) | top-level `dependencies[].dependsOn/provides` **and** inline refs: `certificateProperties.signatureAlgorithmRef` & `subjectPublicKeyRef`, `protocolProperties.cipherSuites[].algorithms` & `cryptoRefArray`, `relatedCryptoMaterialProperties.algorithmRef` | **Direction flip required — see §A.6.** |
| `clusters` (co-migrate) | **not explicit in CBOM** | Inferred: both ends of one `protocol`/channel; a cert and its own subject key. Heuristic, user-overridable. §A.3, §A.6. |

**Headline:** of nine `Asset` fields, CBOM cleanly supplies **two** (`id`, and the vulnerability flag via `nistQuantumSecurityLevel`+primitive) and **partially** informs three (`criticality`, `perf_penalty`, `deps`). The economically decisive ones — **`cost`, `shelf_life`, `deadline`, business `criticality`, and co-migration `clusters`** — are **absent** and must come from a documented default model + user override. *Stating this plainly is half the value of CBOM ingest: garbage/empty CBOM in → the schedule is only as good as these defaults.*

### A.3 Default model for the missing fields (each tied to a source/policy)

All defaults are **overridable** per asset via a sidecar (the brief mandates "documented default model + let the user override"). Period unit = **quarter**; the case study uses horizon `T=18` quarters ≈ 2026Q3→2030Q4.

**`deadline` ← regulatory policy profile (not from the CBOM).**
- **Global default profile (CNSA 2.0 / NIST):** NIST IR 8547 signals RSA/ECC **deprecated after 2030** and **disallowed after 2035**; CNSA 2.0 sets PQC as the default for NSS through 2030–2033. → default `deadline` = period covering **2030** for confidentiality/key-establishment; **2033–2035** for signatures, tightened by class. [7][8][9]
- **India profile (case study):** the DST/Principal Scientific Adviser task-force roadmap ("Implementation of a Quantum Safe Ecosystem in India", Feb 2026) targets **Critical Information Infrastructure (CII) migration by 2027**, broader migration by **2028**, and **high-priority, long-lifetime systems by 2030**; sectoral regulators (RBI/SEBI/TRAI/IRDAI/CERT-In) issue their own mandates. → in the case study, CII anchors (UIDAI keys, UPI switch, RCAI/CA chain) get the tightest deadlines, internet-facing endpoints next, low-criticality leaves last. [10][11][12]
- `certificateProperties.notValidAfter` is used only as a *soft* hint (a cert reissued for any reason is a natural migration window), never as the mandate.

**`shelf_life` ← asset role + data-type tier (HNDL-relevant only).**
HNDL/`shelf_life` is meaningful **only for confidentiality / key-establishment** assets (harvest ciphertext now, decrypt post-CRQC). For **signature** assets the quantum threat is *post-CRQC forgery*, which is a **deadline** concern, not a secrecy-lifetime concern — so signatures get `shelf_life ≈ 0` and are driven by `deadline` + anchor-first precedence.
| role (from `primitive`/`type`) | tier | default `shelf_life` (yrs) | rationale |
|---|---|---|---|
| key-transport / KEM / key-agree protecting long-lived PII (e.g. RSA wrap of biometric session key) | long | **15–25** | Aadhaar-class identity data is sensitive for a lifetime. |
| TLS session key-establishment (ECDHE) on sensitive channels | med | **5–10** | session confidentiality; HNDL on captured transcripts. |
| transient/low-value channels (CDN/static) | short | **1–2** | little harvest value. |
| signature / hash / MAC / cert-signing | none | **0** | not a secrecy asset; deadline-driven (forgery risk). |

**`cost` ← asset-type/role effort tier** (person-day proxy, calibrated later from the generator's public-source distributions; brief §6):
| role | default `cost` (normalized) | rationale |
|---|---|---|
| root/issuing CA re-key + re-issue chain; HSM-bound master keys | **high (8–13)** | ceremony, audits, downstream re-issuance, hardware. |
| server protocol endpoint (TLS) + its leaf cert | **med (3–5)** | config + cert reissue + interop test. |
| client/app crypto, signing leaf, tokenization | **low (1–3)** | library/config change. |

**`perf_penalty` ← PQC replacement class** (default 0; set when doing the constrained-edge case): ML-KEM/ML-DSA handshakes are larger than ECDHE/ECDSA; assets on `executionEnvironment: hardware`/`software-tee` or constrained `implementationPlatform` (`armv*-m`) get a higher penalty. Calibrated from published ML-DSA-vs-ECDSA and ML-KEM-vs-ECDHE size/latency figures (brief §6). [13]

**`earliest` ← PQC-availability profile by protocol/role:** software TLS libraries support hybrid/PQC KEM earliest (`earliest` small); HSM firmware, smartcards, and CA products lag (`earliest > 0`) but, by construction in the case study, never later than the deadline of anything they gate. Default: software endpoints `earliest≈1–2`; HSM/CA-bound `earliest≈4–6`.

**`criticality` ← `assetType` + internet-facing policy overlay** (CBOM carries no exposure signal):
| signal | criticality contribution |
|---|---|
| `protocol` that is internet-facing (public API/portal) | +high |
| root/issuing `certificate` (CA) — many dependents | +high |
| `related-crypto-material` private-key in HSM / key-wrap of PII | +high |
| leaf cert / client algorithm | +low–med |
Internet-facing-ness is supplied by the override sidecar (or inferred from the protocol's host metadata if present).

### A.4 Determining quantum-vulnerability (the single most consequential inference)

A CBOM asset is treated as a **decision variable** iff it is quantum-vulnerable. Use this fallback chain (real scanner CBOMs frequently omit `nistQuantumSecurityLevel` — several `bom-examples` algorithm entries do):

1. **If `algorithmProperties.nistQuantumSecurityLevel` is present:** `0` ⇒ **vulnerable**; `1–5` ⇒ quantum-safe (not a decision variable). This is the CBOM-native signal and is preferred. [5]
2. **Else infer from `primitive` + name/`algorithmFamily`/`oid`:**
   - vulnerable: `pke`/`signature`/`key-agree`/`kem`-by-classical-name where family ∈ {RSA, DSA, DH, ECDSA, ECDH, EdDSA, ECC, ElGamal} (Shor-breakable).
   - quantum-safe: ML-KEM, ML-DSA, SLH-DSA, FN-DSA/Falcon (FIPS 203/204/205) → not decision variables. [7]
   - symmetric/hash (`ae`/`block-cipher`/`hash`/`mac`, e.g. AES-256, SHA-256/384): **not** decision variables — Grover only halves the security level; AES-256 (`nistQuantumSecurityLevel` 1) and SHA-384 (level 2) are quantum-resistant at these sizes. Context only.
3. **Else** (`primitive: other/unknown`, no name signal): mark `unknown` and surface for user triage; do **not** silently treat as safe.

This rule is implemented in `cbom.py` and **must be documented** as the load-bearing assumption of ingest.

### A.5 The sample CBOM (`research/sample.cbom.json`)

A compact, **schema-valid** CBOM modeling a small PKI + TLS estate:

- **Structure adapted from** the official `CycloneDX/bom-examples` CBOM samples (`Example-With-Dependencies/`, `Certificate/`, `Protocol/`), with **field values constrained to the CycloneDX 1.6 enum set** (the examples mix 1.6/1.7). [6]
- **15 `cryptographic-asset` components:** 1 TLS 1.2 `protocol`; 4 `certificate`s (root CA, intermediate/issuing CA, a TLS-server leaf, a document-signing leaf); 6 `algorithm`s (RSA-4096 & RSA-2048 signing, ECDH-P256, ECDSA-P256, AES-256-GCM, SHA-384); 4 `related-crypto-material` public keys (RSA-4096 root, RSA-2048 intermediate, ECDSA-P256 leaf, RSA-2048 doc-sign).
- **A `dependencies[]` graph** wiring certs → their signing algorithm + subject key, intermediate → root, leaves → intermediate, and the TLS protocol → its leaf cert + cipher algorithms.
- Vulnerable assets carry `nistQuantumSecurityLevel: 0` (RSA, ECDSA, ECDH); AES-256-GCM = `1`, SHA-384 = `2`.

**Validation performed (reproducible):**
1. **JSON-schema valid** against the exact `bom-1.6.SNAPSHOT.schema.json` bundled in `cyclonedx-python-lib` 11.10 — **0 errors** (via `jsonschema` Draft7 with a local ref-resolver over the bundled `_res` schemas).
2. **Round-trips** through the library deserializer `cyclonedx.model.bom.Bom.from_json(...)` — parses to 15 cryptographic-asset components and the dependency set.
3. **Derived precedence graph is a DAG** with correct direction: after the §A.6 flip, the root CA is an *ancestor* (prerequisite) of the leaves, and the TLS leaf is a prerequisite of the TLS protocol entry. [5][6]

### A.6 Dependency direction — the flip `cbom.py` MUST apply

CBOM and our scheduler use **opposite** edge directions:

- **CBOM:** `A dependsOn B` means *A needs B* → arrow points **dependent → prerequisite**.
- **Scheduler (`PROJECT_BRIEF.md` §3.1/§3.3):** edge `(j, i)` means *`i` cannot complete migration before `j`* → arrow points **prerequisite → dependent**.

Therefore, for each CBOM `A dependsOn B`, emit the precedence edge **`(B, A)`** (and for `provides`, the provider is the prerequisite). **Sanity anchor:** the CA must re-key *before* leaves can be re-issued, so the CA is the prerequisite `j`; if your derived graph shows a leaf as an ancestor of the root, the direction is inverted. Inline refs are mapped the same way: a certificate `dependsOn` its `signatureAlgorithmRef` and `subjectPublicKeyRef`; a protocol `dependsOn` the algorithms in its `cipherSuites[].algorithms` and the certs in `cryptoRefArray`. **Co-migration clusters** are *not* in CBOM; default to *both ends of one protocol/channel* and *a cert with its own subject key*, user-overridable. (This flip and the DAG/anchor checks are exactly what was verified for the sample in §A.5.)

---

## Part B — Stylized India-DPI estate (case-study seed)

### B.1 The systems and their **public** crypto facts (cited)

**Aadhaar / UIDAI (identity).** The Authentication API encrypts the **PID block** (biometric/OTP + demographics) with a **per-transaction AES-256 session key in GCM mode** (`AES/GCM/NoPadding`); that session key is then encrypted with the **UIDAI public key, RSA-2048** (`RSA/ECB/PKCS1Padding`), and the session key is never stored or reused. The Auth XML is **digitally signed (XML-DSig)** by the AUA/ASA using a **CCA-issued Digital Signature Certificate** (SHA-256 with RSA). e-KYC uses the same envelope. **HNDL marquee asset:** the RSA-2048 wrap of a session key that protects lifetime-sensitive identity data. [14][15][16]

**UPI / NPCI (payments).** NPCI owns/operates the central **UPI switch** that routes between payer/payee PSPs and banks. Transport is **TLS 1.2+**; the stack uses **PKI** and **HSMs**; the UPI **PIN is encrypted (NPCI SDK) under the issuer bank's public key** and verified **inside the bank's HSM** (tamper-resistant), a defense-in-depth design. PSP/TPAP apps are the internet-facing clients; the switch↔bank links are interbank. [17][18][19]

**DigiLocker / eSign (documents & signatures).** DigiLocker (MeitY) serves **issuer-signed XML documents**; e.g. Aadhaar XML is **digitally signed by UIDAI**. Citizen onboarding and pull flows use **Aadhaar e-KYC**, so DigiLocker depends on the UIDAI auth/e-KYC endpoints. **eSign** issues a **short-lived (≈30-minute) one-time Digital Signature Certificate** after an Aadhaar **e-KYC**; the signer key pair is **used once and the private key deleted** (so no revocation needed). The DSC and signed document **chain to a CCA-licensed CA and up to RCAI**. [20][21][22]

**CCA India PKI (trust root for all of the above signatures).** India PKI is hierarchical: the **Root Certifying Authority of India (RCAI)**, operated by the **Controller of Certifying Authorities (CCA)** under the IT Act, signs the certificates of **CCA-licensed CAs** (≈17, incl. eMudhra, (n)Code, Capricorn, NIC-CA, and **IDRBT CA** for banking), which issue leaf **DSCs**/SSL certs. The **Interoperability Guidelines (CCA-IOG)** mandate **RSA with SHA-2**, and **ECDSA with SHA-2 on NIST curve P-256**. RCAI/CA keys are the **highest-criticality, most-depended-on** signature anchors. [23][24][25][26]

> **Honest flags.** Exact production key sizes/rotation for RCAI and individual licensed-CA roots, and UIDAI's HSM internals, are **not fully public** → modeled as `[ASSUMPTION]` (root RSA-4096-class, issuing RSA-2048/ECDSA-P256). The case study's `criticality`, `cost`, `shelf_life`, `earliest`, and `deadline` are **modeling choices** (defaults from §A.3), not facts about NPCI/UIDAI/CCA.

### B.2 Estate component table (27 components)

Tiers: **criticality** 1 (low) – 5 (critical). **shelf_life**: none/short(1–2y)/med(5–10y)/long(15–25y). **effort/cost**: L/M/H (§A.3). **inet** = internet-facing. **mand** = under a regulatory PQC mandate. **vuln** = quantum-vulnerable decision variable. **earliest**/**deadline** in quarter index (1 = 2026Q3 … 18 = 2030Q4); deadlines are the **precedence-feasible effective deadlines** (§B.4).

> The table below is **generated from a single validated source** (the script that builds and feasibility-checks the DAG) and dumped verbatim to **`research/dpi-estate.json`** (machine-readable: assets + edges + clusters + the validation report). Table flags, the counts line, and the JSON are therefore guaranteed identical. `vuln=Y` for every asset that is RSA/ECC/DH-based or a TLS endpoint relying on them; the only non-vulnerable node is the `CCA-IOG-policy` context entry.

| # | id | pillar | crypto usage | crit | shelf_life | effort | inet | mand | vuln | earliest | deadline |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | RCAI-root | CCA PKI | RSA root cert-signing (trust anchor) | 5 | none | H | – | Y | Y | 3 | 11 |
| 2 | CCA-IOG-policy | CCA PKI | interop policy (SHA-2/RSA-2048/ECDSA-P256) — context | 3 | none | L | – | Y | – | 0 | 11 |
| 3 | licensedCA-eMudhra | CCA PKI | licensed-CA cert-signing (DSC/SSL) | 5 | none | H | – | Y | Y | 4 | 13 |
| 4 | licensedCA-IDRBT | CCA PKI | banking-sector licensed-CA signing | 5 | none | H | – | Y | Y | 4 | 11 |
| 5 | licensedCA-NIC-CA | CCA PKI | govt licensed-CA signing (DigiLocker/eSign issuers) | 5 | none | H | – | Y | Y | 4 | 13 |
| 6 | UIDAI-hsm-keys | Aadhaar | HSM-held UIDAI private keys | 5 | long | H | – | Y | Y | 5 | 10 |
| 7 | UIDAI-pubkey-RSA2048 | Aadhaar | **RSA-2048 wrap of PID AES-256 session key (HNDL marquee)** | 5 | long | M | Y | Y | Y | 4 | 10 |
| 8 | UIDAI-auth-endpoint | Aadhaar | Auth API TLS endpoint | 5 | long | M | Y | Y | Y | 2 | 12 |
| 9 | UIDAI-ekyc-endpoint | Aadhaar | e-KYC API TLS endpoint | 5 | long | M | Y | Y | Y | 2 | 12 |
| 10 | UIDAI-authxml-sig | Aadhaar | XML-DSig SHA-256/RSA on Auth XML | 4 | none | M | – | Y | Y | 3 | 14 |
| 11 | AUA-ASA-DSC | Aadhaar | AUA/ASA signing DSC (leaf) | 3 | none | L | – | – | Y | 3 | 14 |
| 12 | AUA-TLS-endpoint | Aadhaar | AUA server TLS to ASA/UIDAI | 3 | med | M | Y | – | Y | 1 | 12 |
| 13 | UPI-switch-TLS | UPI | central UPI switch TLS (internet + interbank) | 5 | med | M | Y | Y | Y | 2 | 12 |
| 14 | UPI-switch-sig | UPI | request signing at the switch | 4 | none | M | – | Y | Y | 3 | 12 |
| 15 | NPCI-HSM-pin | UPI | HSM PIN-block processing | 5 | med | H | – | Y | Y | 5 | 12 |
| 16 | issuerbank-pubkey | UPI | issuer-bank RSA pubkey (PIN/key wrap) — HNDL | 5 | med | M | – | Y | Y | 4 | 12 |
| 17 | issuerbank-TLS | UPI | bank core TLS endpoint | 4 | med | M | Y | Y | Y | 2 | 12 |
| 18 | PSP-app-TLS | UPI | PSP/TPAP app client TLS | 4 | short | L | Y | – | Y | 1 | 12 |
| 19 | PSP-app-sig | UPI | PSP app request signing | 2 | none | L | – | – | Y | 1 | 16 |
| 20 | tokenization-svc | UPI | card/UPI tokenization key-wrap | 3 | med | L | Y | – | Y | 2 | 16 |
| 21 | DigiLocker-TLS | DigiLocker | portal/API TLS | 4 | med | M | Y | Y | Y | 1 | 14 |
| 22 | DigiLocker-issuer-sig | DigiLocker | issuer XML document signatures | 4 | none | M | – | Y | Y | 3 | 14 |
| 23 | DigiLocker-ekyc-tls | DigiLocker | DigiLocker→UIDAI e-KYC client TLS | 3 | med | L | Y | – | Y | 2 | 12 |
| 24 | eSign-ESP-endpoint | eSign | ESP TLS endpoint | 4 | med | M | Y | Y | Y | 2 | 14 |
| 25 | eSign-shortlived-sig | eSign | 30-min one-time signer cert (RSA/SHA-256) | 3 | none | L | – | Y | Y | 3 | 14 |
| 26 | eSign-ekyc-tls | eSign | eSign→UIDAI e-KYC client TLS | 3 | med | L | Y | – | Y | 2 | 12 |
| 27 | GIGW-CDN-TLS | shared | front CDN/edge TLS | 2 | short | L | Y | – | Y | 0 | 12 |

**Counts (from `dpi-estate.json`):** 27 components · **26 quantum-vulnerable** decision variables (all but the `CCA-IOG-policy` context node) · **13 internet-facing** · **19 mandated** · 30 dependency edges · 4 co-migration clusters.

### B.3 Dependency edges (precedence `j → i`: prerequisite migrates first)

Direction is **migration precedence**, i.e. the **provider/anchor migrates before its consumer** — the *opposite* of the runtime "call" arrows ("app→switch→bank→CA"). The CA re-keys before leaves re-issue; the e-KYC provider goes PQC before its consumers can.

```
# PKI: RCAI + interop policy -> licensed CAs -> leaf DSCs / endpoint signatures
RCAI-root           -> licensedCA-eMudhra
RCAI-root           -> licensedCA-IDRBT
RCAI-root           -> licensedCA-NIC-CA
CCA-IOG-policy      -> licensedCA-eMudhra
CCA-IOG-policy      -> licensedCA-IDRBT
CCA-IOG-policy      -> licensedCA-NIC-CA
licensedCA-eMudhra  -> AUA-ASA-DSC
licensedCA-eMudhra  -> eSign-shortlived-sig
licensedCA-IDRBT    -> UPI-switch-sig
licensedCA-IDRBT    -> issuerbank-TLS
licensedCA-NIC-CA   -> DigiLocker-issuer-sig
licensedCA-NIC-CA   -> UIDAI-authxml-sig

# Aadhaar: HSM/pubkey anchors -> endpoints/signatures
UIDAI-hsm-keys      -> UIDAI-pubkey-RSA2048
UIDAI-hsm-keys      -> UIDAI-authxml-sig
UIDAI-pubkey-RSA2048-> UIDAI-auth-endpoint
UIDAI-pubkey-RSA2048-> UIDAI-ekyc-endpoint
UIDAI-authxml-sig   -> AUA-ASA-DSC
UIDAI-auth-endpoint -> AUA-TLS-endpoint

# UPI: switch / issuer providers -> PSP client
UPI-switch-TLS      -> PSP-app-TLS
UPI-switch-sig      -> PSP-app-sig
issuerbank-pubkey   -> NPCI-HSM-pin
issuerbank-TLS      -> UPI-switch-TLS
UPI-switch-TLS      -> tokenization-svc

# DigiLocker / eSign depend on the UIDAI e-KYC provider migrating first
UIDAI-ekyc-endpoint -> DigiLocker-ekyc-tls
UIDAI-ekyc-endpoint -> eSign-ekyc-tls
UIDAI-ekyc-endpoint -> eSign-ESP-endpoint
DigiLocker-ekyc-tls -> DigiLocker-TLS
eSign-ESP-endpoint  -> eSign-shortlived-sig

# shared front edge gates the public endpoints it fronts
GIGW-CDN-TLS        -> DigiLocker-TLS
GIGW-CDN-TLS        -> UPI-switch-TLS
```

### B.4 Co-migration clusters (both ends of one protocol/channel — peers only)

A cluster forces both ends into the **same** period (a protocol only works if client and server speak the same crypto). Clusters are **peers at the same precedence depth with the same deadline** (clustering different-deadline or different-depth nodes can make the instance infeasible — designed around).

```
{ AUA-TLS-endpoint , UIDAI-auth-endpoint }      # AUA <-> UIDAI auth TLS
{ PSP-app-TLS , UPI-switch-TLS }                # app <-> UPI switch TLS
{ DigiLocker-ekyc-tls , UIDAI-ekyc-endpoint }   # DigiLocker <-> UIDAI e-KYC TLS
{ eSign-ekyc-tls , UIDAI-ekyc-endpoint }        # eSign <-> UIDAI e-KYC TLS
```

### B.5 The estate is a **verified, schedulable** `Instance`

Built and checked programmatically (so the case study actually solves):
- **DAG** — 27 nodes, 30 edges, acyclic (`networkx.is_directed_acyclic_graph` = True).
- **Anchor-first verified** — RCAI is an *ancestor* (prerequisite) of every leaf DSC; UIDAI e-KYC is an ancestor of DigiLocker; UPI switch is an ancestor of the PSP app; **no** leaf is an ancestor of RCAI.
- **Precedence × deadline feasible** — every prerequisite's `earliest ≤` each dependent's `deadline`; and the **effective deadlines are precedence-monotone** (prereq deadline ≤ dependent deadline), computed by propagating policy deadlines backward up the DAG and tightening anchors. **0** violations; **0** self-infeasibilities (`earliest ≤ deadline` for all).
- **Cluster-consistent** — both ends of every cluster share a deadline (**0** conflicts).

> **Modeling note to state in `REPORT.md` (honesty).** The effective deadline `deadline(j) = min(policy(j), min over dependents deadline)` is **not a fudge** — it is the deadline that precedence + the hard mandated-deadline constraint *logically imply* (a prerequisite must finish no later than anything that depends on it), and the solver enforces it regardless. The genuine infeasibility trigger is different: `earliest(j) > deadline(dependent)` — an anchor whose PQC support arrives *after* a leaf's mandate. That case is **tested here and absent** (0 self-/mandated-infeasibilities), but it is real: a regulator can mandate a leaf early while its CA/HSM vendor lags, and the solver *should* then report infeasibility (a finding, not a bug). The generator (brief §6) can emit such adversarial instances on purpose; this seed deliberately stays feasible so the case-study roadmap is well-defined. The HNDL `shelf_life` weighting (high for #6/#7/#16 key-wrap, zero for signatures) and the per-period budget `B_t` are the other load-bearing modeling choices to sensitivity-test.

---

## Sources

CycloneDX / CBOM:
1. CycloneDX — *Authoritative Guide to CBOM* / cryptography use-cases: https://cyclonedx.org/guides/ and https://cyclonedx.org/use-cases/cryptographic-algorithm/
2. CycloneDX 1.6 release / "All about CycloneDX 1.6" (CBOM introduced in 1.6): https://www.interlynk.io/resources/all-about-cyclonedx-1-6
3. IBM/CBOM (origin of the CBOM design, contributed to CycloneDX): https://github.com/IBM/CBOM
4. Cryptographic bill of materials (overview): https://en.wikipedia.org/wiki/Cryptographic_bill_of_materials
5. CycloneDX 1.6 JSON schema (authoritative field/enum source) — `CycloneDX/specification` `schema/bom-1.6.schema.json`: https://github.com/CycloneDX/specification/blob/1.6/schema/bom-1.6.schema.json (verified locally against the `bom-1.6.SNAPSHOT.schema.json` bundled in `cyclonedx-python-lib` 11.10)
6. CycloneDX `bom-examples` — CBOM examples adapted for the sample: https://github.com/CycloneDX/bom-examples/tree/master/CBOM

Standards / timelines (deadline defaults):
7. NIST FIPS 203 (ML-KEM), 204 (ML-DSA), 205 (SLH-DSA): https://csrc.nist.gov/pubs/fips/203/final
8. NIST IR 8547 — *Transition to PQC Standards* (RSA/ECC deprecate ~2030, disallow ~2035): https://csrc.nist.gov/pubs/ir/8547/ipd
9. NSA CNSA 2.0: https://media.defense.gov/2022/Sep/07/2003071834/-1/-1/0/CSA_CNSA_2.0_ALGORITHMS_.PDF
10. India DST/PSA task-force PQC roadmap — "Implementation of a Quantum Safe Ecosystem in India" (2027 CII / 2028 / 2030 timeline): https://postquantum.com/security-pqc/indias-quantum-safe-roadmap/
11. ORF — *India's Post-Quantum Cryptography Migration Roadmap*: https://www.orfonline.org/expert-speak/india-s-post-quantum-cryptography-migration-roadmap
12. India National Quantum Mission (NQM) — Quantum Readiness / mission: https://dst.gov.in/national-quantum-mission-nqm
13. PQC performance/size references (ML-DSA vs ECDSA, ML-KEM vs ECDHE) for `perf_penalty` calibration — Open Quantum Safe / liboqs profiling: https://openquantumsafe.org/

India DPI architecture (crypto facts):
14. UIDAI — Aadhaar Authentication API spec v2.5 (PID AES-256-GCM session key; RSA-2048 UIDAI public key; XML-DSig): https://uidai.gov.in/images/resource/aadhaar_authentication_api_2_5.pdf
15. UIDAI — Authentication / e-KYC developer & certificate details: https://uidai.gov.in/en/ecosystem/authentication-devices-documents/developer-section/data-and-downloads-section.html
16. Aadhaar e-KYC technical reference (AES-256-GCM + RSA-2048 PKCS1 envelope, corroborating): https://www.dpdpindia.in/ekyc-uidai-guide.html
17. PwC India — *Unified Payments Interface: Security* (TLS, PKI, HSM, defense-in-depth): https://www.pwc.in/assets/pdfs/consulting/cyber-security/banking/unified-payment-interface-security.pdf
18. NPCI / Google Pay — roles of NPCI, PSP, TPAP (UPI switch, PSP apps): https://pay.google.com/intl/en_in/about/external/npci/
19. UPI architecture & security deep-dive (PIN encrypted under issuer-bank key, HSM verification): https://blog.akshanshjaiswal.com/the-upi-architecture-a-security-look
20. DigiLocker — Issuer API Specification v1.13 (issuer-signed XML documents, URIs): https://cf-media.api-setu.in/resources/DigiLocker-Issuer-APISpecification-v1-13.pdf
21. CCA — eSign FAQ (30-minute one-time DSC; key pair used once, private key deleted): https://cca.gov.in/sites/files/pdf/esign/ESIGNFAQ.pdf
22. CCA — Framework on eSignature (ASP/ESP, Aadhaar e-KYC → DSC → CA chain): https://cca.gov.in/sites/files/pdf/guidelines/ESF.pdf
23. CCA — Root Certifying Authority of India (RCAI): https://cca.gov.in/rcai.html
24. CCA — India PKI hierarchy & policies (RCAI → licensed CAs → leaf): https://cca.gov.in/india_pki.html
25. CCA — Interoperability Guidelines for DSC (RSA+SHA-2; ECDSA+SHA-2 P-256): https://cca.gov.in/sites/files/pdf/guidelines/CCA-IOG.pdf
26. INDIA PKI FORUM — Certifying Authorities & certificates in India (≈17 licensed CAs incl. IDRBT/NIC): https://www.indiapki.org/ca-and-certificates-in-india.html
