-- EMRTS Electronic Claim Entry & Submission Portal
-- Initial PostgreSQL schema for CMS-1500 claim information capture.
--
-- Primary keys use UUIDs for internal database identity.
-- Business identifiers such as NPI numbers, payer identifiers, ICD-10 codes,
-- CPT codes, and HCPCS codes are stored as data fields, not primary keys.
--
-- Development and sample data must not contain real PHI.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE,
    sex VARCHAR(20),
    address_line_1 VARCHAR(255),
    address_line_2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(20),
    phone_number VARCHAR(30),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE insured_parties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE,
    sex VARCHAR(20),
    relationship_to_patient VARCHAR(50),
    insured_id_number VARCHAR(100),
    group_number VARCHAR(100),
    address_line_1 VARCHAR(255),
    address_line_2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(20),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE payers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payer_name VARCHAR(255) NOT NULL,
    payer_type VARCHAR(50) NOT NULL,
    payer_identifier VARCHAR(100),
    medicare_administrative_contractor VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_name VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    npi VARCHAR(20),
    taxonomy_code VARCHAR(20),
    tax_id VARCHAR(50),
    address_line_1 VARCHAR(255),
    address_line_2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(20),
    phone_number VARCHAR(30),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_number VARCHAR(100) UNIQUE,
    patient_id UUID NOT NULL REFERENCES patients(id),
    insured_party_id UUID REFERENCES insured_parties(id),
    payer_id UUID NOT NULL REFERENCES payers(id),
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    validation_status VARCHAR(50),
    validation_message TEXT,
    service_start_date DATE,
    service_end_date DATE,
    total_charge_amount NUMERIC(12, 2) DEFAULT 0.00,
    submitted_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE claim_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES providers(id),
    provider_role VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (claim_id, provider_id, provider_role)
);

CREATE TABLE claim_diagnoses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    diagnosis_code VARCHAR(20) NOT NULL,
    diagnosis_order INTEGER NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (claim_id, diagnosis_order)
);

CREATE TABLE service_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    service_from_date DATE,
    service_to_date DATE,
    place_of_service VARCHAR(10),
    procedure_code VARCHAR(20) NOT NULL,
    modifier_1 VARCHAR(10),
    modifier_2 VARCHAR(10),
    modifier_3 VARCHAR(10),
    modifier_4 VARCHAR(10),
    diagnosis_pointer_1 INTEGER,
    diagnosis_pointer_2 INTEGER,
    diagnosis_pointer_3 INTEGER,
    diagnosis_pointer_4 INTEGER,
    charge_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    units INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE claim_audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    event_description TEXT,
    changed_by VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_patients_name ON patients(last_name, first_name);
CREATE INDEX idx_patients_dob ON patients(date_of_birth);

CREATE INDEX idx_insured_parties_name ON insured_parties(last_name, first_name);
CREATE INDEX idx_payers_identifier ON payers(payer_identifier);
CREATE INDEX idx_providers_npi ON providers(npi);
CREATE INDEX idx_providers_taxonomy_code ON providers(taxonomy_code);

CREATE INDEX idx_claims_status ON claims(status);
CREATE INDEX idx_claims_patient_id ON claims(patient_id);
CREATE INDEX idx_claims_payer_id ON claims(payer_id);
CREATE INDEX idx_claims_service_dates ON claims(service_start_date, service_end_date);

CREATE INDEX idx_claim_providers_claim_id ON claim_providers(claim_id);
CREATE INDEX idx_claim_providers_provider_id ON claim_providers(provider_id);

CREATE INDEX idx_claim_diagnoses_claim_id ON claim_diagnoses(claim_id);
CREATE INDEX idx_claim_diagnoses_code ON claim_diagnoses(diagnosis_code);

CREATE INDEX idx_service_lines_claim_id ON service_lines(claim_id);
CREATE INDEX idx_service_lines_procedure_code ON service_lines(procedure_code);

CREATE INDEX idx_claim_audit_events_claim_id ON claim_audit_events(claim_id);
CREATE INDEX idx_claim_audit_events_event_type ON claim_audit_events(event_type);
