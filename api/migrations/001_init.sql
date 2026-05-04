-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── sessions ──────────────────────────────────────────────────────────────────
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    tenant_name  TEXT,
    role         TEXT NOT NULL,
    patient_id   TEXT,
    patient_name TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── messages ───────────────────────────────────────────────────────────────────
CREATE TABLE messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    agent       TEXT NOT NULL,
    role        TEXT,
    content     TEXT,
    data        JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX messages_session_agent_idx ON messages (session_id, agent, id);

-- ── appointments ──────────────────────────────────────────────────────────────
-- Flat denormalized mirror of the practice management system appointments
CREATE TABLE appointments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    appointment_id  TEXT NOT NULL,
    patient_name    TEXT NOT NULL,
    patient_id      TEXT NOT NULL,
    provider        TEXT NOT NULL,
    date            DATE NOT NULL,
    time            TIME NOT NULL,
    procedure_code  TEXT,
    procedure_desc  TEXT,
    status           TEXT NOT NULL DEFAULT 'scheduled',
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    notes            TEXT,
    tenant_id        TEXT NOT NULL,
    search_vector   TSVECTOR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX appointments_tenant_idx    ON appointments (tenant_id);
CREATE INDEX appointments_date_idx      ON appointments (tenant_id, date);
CREATE INDEX appointments_provider_idx  ON appointments (tenant_id, provider);
CREATE INDEX appointments_patient_idx   ON appointments (tenant_id, patient_id);
CREATE INDEX appointments_status_idx    ON appointments (tenant_id, status);
CREATE INDEX appointments_search_idx    ON appointments USING GIN (search_vector);

CREATE OR REPLACE FUNCTION appointments_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        coalesce(NEW.patient_name, '') || ' ' ||
        coalesce(NEW.provider, '') || ' ' ||
        coalesce(NEW.procedure_desc, '') || ' ' ||
        coalesce(NEW.notes, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER appointments_search_trigger
    BEFORE INSERT OR UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION appointments_search_vector_update();

-- ── claims ────────────────────────────────────────────────────────────────────
CREATE TABLE claims (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id        TEXT NOT NULL,
    patient_id      TEXT NOT NULL,
    patient_name    TEXT NOT NULL,
    date_of_service DATE NOT NULL,
    procedure_code  TEXT,
    procedure_desc  TEXT,
    billed_amount   NUMERIC(10, 2),
    insurance_paid  NUMERIC(10, 2),
    patient_owed    NUMERIC(10, 2),
    status          TEXT NOT NULL DEFAULT 'pending',
    payer           TEXT,
    notes           TEXT,
    tenant_id       TEXT NOT NULL,
    search_vector   TSVECTOR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX claims_tenant_idx   ON claims (tenant_id);
CREATE INDEX claims_patient_idx  ON claims (tenant_id, patient_id);
CREATE INDEX claims_status_idx   ON claims (tenant_id, status);
CREATE INDEX claims_search_idx   ON claims USING GIN (search_vector);

CREATE OR REPLACE FUNCTION claims_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        coalesce(NEW.patient_name, '') || ' ' ||
        coalesce(NEW.payer, '') || ' ' ||
        coalesce(NEW.procedure_desc, '') || ' ' ||
        coalesce(NEW.notes, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER claims_search_trigger
    BEFORE INSERT OR UPDATE ON claims
    FOR EACH ROW EXECUTE FUNCTION claims_search_vector_update();

-- ── data_sources ──────────────────────────────────────────────────────────────
-- RAG store for unstructured documents (FAQs, policies, PDFs)
CREATE TABLE data_sources (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    text            TEXT NOT NULL,
    embedding       vector(1536),
    search_vector   TSVECTOR,
    tenant_id       TEXT NOT NULL,
    doc_type        TEXT NOT NULL,
    source          TEXT NOT NULL,
    document_id     TEXT NOT NULL,
    audience        TEXT NOT NULL DEFAULT 'staff',
    page            INTEGER NOT NULL DEFAULT 1,
    chunk_index     INTEGER NOT NULL,
    effective_date  DATE,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX data_sources_tenant_idx       ON data_sources (tenant_id);
CREATE INDEX data_sources_tenant_doc_idx   ON data_sources (tenant_id, doc_type);
CREATE INDEX data_sources_document_idx     ON data_sources (document_id);
CREATE INDEX data_sources_search_idx       ON data_sources USING GIN (search_vector);
CREATE INDEX data_sources_embedding_idx    ON data_sources USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE OR REPLACE FUNCTION data_sources_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', NEW.text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_sources_search_trigger
    BEFORE INSERT OR UPDATE OF text ON data_sources
    FOR EACH ROW EXECUTE FUNCTION data_sources_search_vector_update();
