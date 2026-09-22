--
-- PostgreSQL database dump
--

-- Dumped from database version 16.15 (Debian 16.15-1.pgdg12+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg12+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: assets; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA assets;


--
-- Name: catalog; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA catalog;


--
-- Name: community; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA community;


--
-- Name: config; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA config;


--
-- Name: engine; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA engine;


--
-- Name: evidence; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA evidence;


--
-- Name: identity; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA identity;


--
-- Name: notification; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA notification;


--
-- Name: planning; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA planning;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: file_object; Type: TABLE; Schema: assets; Owner: -
--

CREATE TABLE assets.file_object (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bucket text NOT NULL,
    object_key text NOT NULL,
    storage_version text NOT NULL,
    original_filename text NOT NULL,
    mime_type text NOT NULL,
    byte_size bigint NOT NULL,
    sha256 text NOT NULL,
    access_scope text DEFAULT 'internal'::text NOT NULL,
    use_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    scan_status text DEFAULT 'pending'::text NOT NULL,
    storage_status text DEFAULT 'pending'::text NOT NULL,
    uploaded_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT file_object_access_scope_check CHECK ((access_scope = ANY (ARRAY['public'::text, 'internal'::text]))),
    CONSTRAINT file_object_check CHECK (((byte_size > 0) AND (length(sha256) = 64))),
    CONSTRAINT file_object_scan_status_check CHECK ((scan_status = ANY (ARRAY['pending'::text, 'clean'::text, 'rejected'::text]))),
    CONSTRAINT file_object_storage_status_check CHECK ((storage_status = ANY (ARRAY['pending'::text, 'available'::text, 'quarantined'::text, 'purged'::text])))
);


--
-- Name: material_applicability; Type: TABLE; Schema: assets; Owner: -
--

CREATE TABLE assets.material_applicability (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id uuid NOT NULL,
    product_id uuid NOT NULL,
    variant_id uuid,
    conditions jsonb DEFAULT '{}'::jsonb NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: material_revision; Type: TABLE; Schema: assets; Owner: -
--

CREATE TABLE assets.material_revision (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    material_id uuid NOT NULL,
    revision_no integer NOT NULL,
    file_object_id uuid NOT NULL,
    source_url text,
    language text NOT NULL,
    issued_at date,
    retrieved_at timestamp with time zone NOT NULL,
    active_ingestion_id uuid,
    status text DEFAULT 'staged'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT material_revision_status_check CHECK ((status = ANY (ARRAY['staged'::text, 'published'::text, 'superseded'::text, 'revoked'::text])))
);


--
-- Name: product_material; Type: TABLE; Schema: assets; Owner: -
--

CREATE TABLE assets.product_material (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_id uuid NOT NULL,
    title text NOT NULL,
    material_type text NOT NULL,
    current_revision_id uuid,
    status text DEFAULT 'draft'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT product_material_material_type_check CHECK ((material_type = ANY (ARRAY['manual'::text, 'spec_sheet'::text, 'image'::text, 'certification'::text]))),
    CONSTRAINT product_material_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'active'::text, 'retired'::text])))
);


--
-- Name: case_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.case_spec (
    product_id uuid NOT NULL,
    supported_motherboard text,
    cpu_cooler_height_mm integer,
    gpu_max_length_mm integer,
    psu_form_factor text,
    case_type text,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    max_psu_length_mm integer,
    expansion_slots integer,
    radiator_front_mm text,
    radiator_top_mm text,
    radiator_rear_mm text,
    color text,
    expansion_source_url text
);


--
-- Name: cooler_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.cooler_spec (
    product_id uuid NOT NULL,
    cooling_type text,
    supported_socket text,
    cooler_height_mm integer,
    radiator_mm integer,
    case_check_note text,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cpu_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.cpu_spec (
    product_id uuid NOT NULL,
    socket text,
    tdp_w integer,
    memory_type text,
    integrated_graphics text,
    cooler_included text,
    lineup text,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    max_power_w integer,
    family text,
    power_family_source_url text,
    perf_score numeric,
    perf_score_source_url text
);


--
-- Name: gpu_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.gpu_spec (
    product_id uuid NOT NULL,
    gpu_class text,
    vram_gb text,
    memory_type text,
    pcie_interface text,
    power_w integer,
    recommended_psu_w integer,
    length_mm integer,
    height_mm integer,
    slot_thickness text,
    power_connector text,
    aux_power text,
    ecc text,
    lineup text,
    spec_basis text,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    dimension_source_url text,
    dimension_gap_reason text,
    perf_score numeric,
    perf_score_source_url text
);


--
-- Name: keyboard_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.keyboard_spec (
    product_id uuid NOT NULL,
    switch_kind text,
    switch_method text,
    rapid_trigger boolean,
    connectivity text[],
    weight_g numeric(10,2),
    size_mm text,
    product_url text,
    manual_reference text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    connectivity_interface text[]
);


--
-- Name: mainboard_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.mainboard_spec (
    product_id uuid NOT NULL,
    socket text,
    chipset text,
    form_factor text,
    memory_type text,
    board_size_mm text,
    supported_cpu_family text,
    bios_note text,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    dimm_slots integer,
    max_memory_gb integer,
    max_memory_speed_mts integer,
    m2_slots integer,
    m2_pcie_gen text,
    sata_ports integer,
    min_bios text,
    expansion_source_url text
);


--
-- Name: merchant; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.merchant (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    platform text NOT NULL,
    external_seller_id text NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: monitor_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.monitor_spec (
    product_id uuid NOT NULL,
    model_code text,
    screen_size_inch numeric(5,2),
    resolution text,
    max_refresh_hz numeric(7,2),
    panel text,
    response_ms_gtg numeric(7,2),
    brightness_nit integer,
    curvature text,
    hdmi_version text,
    hdmi_ports integer,
    dp_version text,
    dp_ports integer,
    dp_connector text,
    usb_c_video_input text,
    usb_c_power_w integer,
    vesa_mount_mm text,
    port_limits text,
    note text,
    weight_g numeric(10,2),
    size_mm text,
    product_url text,
    manual_reference text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT monitor_spec_dp_ports_check CHECK (((dp_ports IS NULL) OR (dp_ports >= 0))),
    CONSTRAINT monitor_spec_hdmi_ports_check CHECK (((hdmi_ports IS NULL) OR (hdmi_ports >= 0)))
);


--
-- Name: mouse_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.mouse_spec (
    product_id uuid NOT NULL,
    model_number text,
    category_label text,
    form_factor text,
    sensor text,
    dpi_range text,
    polling_rate text,
    button_count text,
    switch_click text,
    connectivity text[],
    battery_power text,
    color_options text,
    software_url text,
    weight_g numeric(10,2),
    size_mm text,
    product_url text,
    manual_reference text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    connectivity_interface text[]
);


--
-- Name: offer; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.offer (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    variant_id uuid NOT NULL,
    merchant_id uuid NOT NULL,
    external_offer_id text NOT NULL,
    purchase_url text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT offer_status_check CHECK ((status = ANY (ARRAY['active'::text, 'sold_out'::text, 'expired'::text])))
);


--
-- Name: offer_observation; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.offer_observation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    offer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    price numeric(18,2),
    currency character(3) DEFAULT 'KRW'::bpchar NOT NULL,
    stock_status text NOT NULL,
    pricing_terms jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_status text NOT NULL,
    valid_until timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT offer_observation_check CHECK (((quality_status <> 'valid'::text) OR (price IS NOT NULL))),
    CONSTRAINT offer_observation_price_check CHECK (((price IS NULL) OR (price >= (0)::numeric))),
    CONSTRAINT offer_observation_quality_status_check CHECK ((quality_status = ANY (ARRAY['valid'::text, 'failed'::text, 'stale'::text]))),
    CONSTRAINT offer_observation_stock_status_check CHECK ((stock_status = ANY (ARRAY['available'::text, 'sold_out'::text, 'unknown'::text])))
);


--
-- Name: peripheral_price_snapshot; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.peripheral_price_snapshot (
    product_id uuid NOT NULL,
    price_krw integer,
    price_observed_at timestamp with time zone,
    source_file text NOT NULL,
    source_row integer NOT NULL,
    source_sha256 character(64) NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT peripheral_price_snapshot_price_krw_check CHECK (((price_krw IS NULL) OR (price_krw > 0))),
    CONSTRAINT peripheral_price_snapshot_source_row_check CHECK ((source_row >= 2))
);


--
-- Name: product; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.product (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    brand text NOT NULL,
    model text NOT NULL,
    product_type text NOT NULL,
    attributes jsonb DEFAULT '{}'::jsonb NOT NULL,
    image_url text,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    category_id uuid,
    CONSTRAINT product_status_check CHECK ((status = ANY (ARRAY['active'::text, 'discontinued'::text])))
);


--
-- Name: product_category; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.product_category (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_id uuid,
    code text NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: product_fact; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.product_fact (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    product_id uuid NOT NULL,
    variant_id uuid,
    attribute_key text NOT NULL,
    value jsonb NOT NULL,
    unit_code text,
    evidence_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    valid_until timestamp with time zone,
    status text DEFAULT 'proposed'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT product_fact_status_check CHECK ((status = ANY (ARRAY['proposed'::text, 'verified'::text, 'superseded'::text, 'revoked'::text])))
);


--
-- Name: product_variant; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.product_variant (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    product_id uuid NOT NULL,
    variant_key text NOT NULL,
    gtin text,
    attributes jsonb DEFAULT '{}'::jsonb NOT NULL,
    pack_quantity numeric(18,4) DEFAULT 1 NOT NULL,
    unit_code text DEFAULT 'each'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT product_variant_pack_quantity_check CHECK ((pack_quantity > (0)::numeric))
);


--
-- Name: psu_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.psu_spec (
    product_id uuid NOT NULL,
    wattage_w integer,
    efficiency_rating text,
    form_factor text,
    cable_type text,
    gpu_power_connector text,
    atx_spec text,
    modular text,
    length_mm integer,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    pcie_8pin_count integer,
    connector_12v2x6_count integer,
    dimension_source_url text
);


--
-- Name: ram_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.ram_spec (
    product_id uuid NOT NULL,
    memory_type text,
    speed_mts integer,
    total_capacity_gb integer,
    module_config text,
    capacity_per_module_gb integer,
    cas_latency integer,
    form_factor text,
    pin_count integer,
    voltage_v numeric(4,2),
    ecc text,
    buffer_type text,
    oc_profile text,
    heatsink text,
    rgb text,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    height_mm numeric,
    height_source_url text
);


--
-- Name: speaker_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.speaker_spec (
    product_id uuid NOT NULL,
    speaker_form text,
    connectivity text[],
    channels text,
    output_power text,
    impedance text,
    signal_noise_ratio text,
    sensitivity text,
    power_source text,
    enclosure text,
    note text,
    weight_g numeric(10,2),
    size_mm text,
    product_url text,
    manual_reference text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    connectivity_interface text[]
);


--
-- Name: ssd_spec; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.ssd_spec (
    product_id uuid NOT NULL,
    interface text,
    protocol text,
    form_factor text,
    heatsink text,
    capacity_options text,
    nand_type text,
    dram text,
    ps5_compat text,
    size_note text,
    weight_note text,
    spec_url text,
    sale_status text,
    status_checked_at date,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pc_build; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.pc_build (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_user_id uuid NOT NULL,
    name text NOT NULL,
    current_version_id uuid,
    visibility text DEFAULT 'private'::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pc_build_status_check CHECK ((status = ANY (ARRAY['active'::text, 'deleted'::text]))),
    CONSTRAINT pc_build_visibility_check CHECK ((visibility = ANY (ARRAY['private'::text, 'public'::text])))
);


--
-- Name: pc_build_component; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.pc_build_component (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    build_version_id uuid NOT NULL,
    slot_key text NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    variant_id uuid NOT NULL,
    quantity integer DEFAULT 1 NOT NULL,
    component_snapshot jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pc_build_component_check CHECK (((quantity > 0) AND ("position" >= 0)))
);


--
-- Name: pc_build_version; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.pc_build_version (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    build_id uuid NOT NULL,
    version_no integer NOT NULL,
    source_plan_revision_id uuid,
    state text DEFAULT 'draft'::text NOT NULL,
    usage_status text DEFAULT 'planned'::text NOT NULL,
    assembled_at date,
    environment jsonb DEFAULT '{}'::jsonb NOT NULL,
    configuration_hash text,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pc_build_version_state_check CHECK ((state = ANY (ARRAY['draft'::text, 'published'::text]))),
    CONSTRAINT pc_build_version_usage_status_check CHECK ((usage_status = ANY (ARRAY['planned'::text, 'assembled_self_reported'::text])))
);


--
-- Name: review; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.review (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    author_user_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    current_revision_id uuid,
    status text DEFAULT 'draft'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT review_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'published'::text, 'hidden'::text, 'deleted'::text])))
);


--
-- Name: review_revision; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.review_revision (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    review_id uuid NOT NULL,
    revision_no integer NOT NULL,
    domain_version_id uuid NOT NULL,
    rating smallint NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    axis_scores jsonb DEFAULT '{}'::jsonb NOT NULL,
    usage_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    moderation_status text DEFAULT 'pending'::text NOT NULL,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT review_revision_moderation_status_check CHECK ((moderation_status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text, 'redacted'::text]))),
    CONSTRAINT review_revision_rating_check CHECK (((rating >= 1) AND (rating <= 5)))
);


--
-- Name: domain; Type: TABLE; Schema: config; Owner: -
--

CREATE TABLE config.domain (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT domain_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'active'::text, 'disabled'::text])))
);


--
-- Name: domain_version; Type: TABLE; Schema: config; Owner: -
--

CREATE TABLE config.domain_version (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    domain_id uuid NOT NULL,
    version_no integer NOT NULL,
    definition jsonb NOT NULL,
    attribute_schema jsonb NOT NULL,
    content_hash text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT domain_version_version_no_check CHECK ((version_no > 0))
);


--
-- Name: feedback_event; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.feedback_event (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    plan_id uuid NOT NULL,
    revision_id uuid NOT NULL,
    recommendation_run_id uuid,
    user_id uuid,
    event_type text NOT NULL,
    event_key text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT feedback_event_check CHECK (((event_type <> 'recommendation_shown'::text) OR (recommendation_run_id IS NOT NULL))),
    CONSTRAINT feedback_event_event_type_check CHECK ((event_type = ANY (ARRAY['recommendation_shown'::text, 'item_replaced'::text, 'item_removed'::text, 'plan_confirmed'::text])))
);


--
-- Name: recommendation_candidate; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.recommendation_candidate (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    requirement_id uuid NOT NULL,
    variant_id uuid NOT NULL,
    offer_observation_id uuid,
    result text NOT NULL,
    score numeric(8,4),
    score_method_version text,
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    reason_status text DEFAULT 'pending'::text NOT NULL,
    evidence_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    selected boolean DEFAULT true NOT NULL,
    qty integer DEFAULT 1 NOT NULL,
    timing text DEFAULT 'now'::text NOT NULL,
    checks text,
    checks_status text DEFAULT 'pending'::text NOT NULL,
    CONSTRAINT recommendation_candidate_check CHECK (((score IS NULL) OR (score_method_version IS NOT NULL))),
    CONSTRAINT recommendation_candidate_checks_content_check CHECK (((checks_status = 'ready'::text) = (checks IS NOT NULL))),
    CONSTRAINT recommendation_candidate_checks_status_check CHECK ((checks_status = ANY (ARRAY['pending'::text, 'ready'::text, 'failed'::text]))),
    CONSTRAINT recommendation_candidate_qty_check CHECK (((qty >= 1) AND (qty <= 99))),
    CONSTRAINT recommendation_candidate_reason_content_check CHECK (((reason_status = 'ready'::text) = (reason IS NOT NULL))),
    CONSTRAINT recommendation_candidate_reason_status_check CHECK ((reason_status = ANY (ARRAY['pending'::text, 'ready'::text, 'failed'::text]))),
    CONSTRAINT recommendation_candidate_result_check CHECK ((result = ANY (ARRAY['pending'::text, 'passed'::text, 'rejected'::text, 'selected'::text]))),
    CONSTRAINT recommendation_candidate_timing_check CHECK ((timing = ANY (ARRAY['now'::text, 'soon'::text, 'later'::text])))
);


--
-- Name: recommendation_run; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.recommendation_run (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id uuid NOT NULL,
    domain_version_id uuid NOT NULL,
    input_snapshot jsonb NOT NULL,
    input_hash text NOT NULL,
    draft_lock_version integer NOT NULL,
    engine_versions jsonb NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    explanation_status text DEFAULT 'pending'::text NOT NULL,
    explanation_headline text,
    explanation_text text,
    reasoning_log jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT recommendation_run_explanation_content_check CHECK (((explanation_status = 'ready'::text) = (explanation_text IS NOT NULL))),
    CONSTRAINT recommendation_run_explanation_status_check CHECK ((explanation_status = ANY (ARRAY['pending'::text, 'ready'::text, 'failed'::text]))),
    CONSTRAINT recommendation_run_reasoning_log_check CHECK ((jsonb_typeof(reasoning_log) = 'array'::text)),
    CONSTRAINT recommendation_run_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'completed'::text, 'failed'::text, 'stale'::text])))
);


--
-- Name: validation_result; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.validation_result (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    rule_key text NOT NULL,
    rule_version text NOT NULL,
    executor_version text NOT NULL,
    status text NOT NULL,
    severity text NOT NULL,
    measured_values jsonb DEFAULT '{}'::jsonb NOT NULL,
    threshold jsonb DEFAULT '{}'::jsonb NOT NULL,
    message text NOT NULL,
    checked_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    issues jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT validation_result_severity_check CHECK ((severity = ANY (ARRAY['info'::text, 'warning'::text, 'critical'::text]))),
    CONSTRAINT validation_result_status_check CHECK ((status = ANY (ARRAY['pass'::text, 'fail'::text, 'unknown'::text, 'not_applicable'::text])))
);


--
-- Name: evidence; Type: TABLE; Schema: evidence; Owner: -
--

CREATE TABLE evidence.evidence (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_id uuid NOT NULL,
    kind text NOT NULL,
    retrieval_hit_id uuid,
    review_aggregate_id uuid,
    source_url text,
    facts jsonb DEFAULT '{}'::jsonb NOT NULL,
    citation_snapshot jsonb NOT NULL,
    retrieved_at timestamp with time zone NOT NULL,
    valid_until timestamp with time zone,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT evidence_check CHECK ((((kind = 'material'::text) AND (retrieval_hit_id IS NOT NULL) AND (review_aggregate_id IS NULL) AND (source_url IS NULL)) OR ((kind = 'review_aggregate'::text) AND (review_aggregate_id IS NOT NULL) AND (retrieval_hit_id IS NULL) AND (source_url IS NULL)) OR ((kind = 'external_fact'::text) AND (source_url IS NOT NULL) AND (retrieval_hit_id IS NULL) AND (review_aggregate_id IS NULL)))),
    CONSTRAINT evidence_kind_check CHECK ((kind = ANY (ARRAY['material'::text, 'review_aggregate'::text, 'external_fact'::text]))),
    CONSTRAINT evidence_status_check CHECK ((status = ANY (ARRAY['active'::text, 'superseded'::text, 'revoked'::text])))
);


--
-- Name: review_aggregate; Type: TABLE; Schema: evidence; Owner: -
--

CREATE TABLE evidence.review_aggregate (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    subject_id uuid NOT NULL,
    domain_version_id uuid NOT NULL,
    source_scope text NOT NULL,
    processing_version text NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    analyzed_count integer DEFAULT 0 NOT NULL,
    excluded_count integer DEFAULT 0 NOT NULL,
    retained_count integer DEFAULT 0 NOT NULL,
    ratings jsonb DEFAULT '{}'::jsonb NOT NULL,
    axis_scores jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'building'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT review_aggregate_check CHECK (((analyzed_count = (excluded_count + retained_count)) AND (excluded_count >= 0) AND (retained_count >= 0))),
    CONSTRAINT review_aggregate_check1 CHECK ((window_end >= window_start)),
    CONSTRAINT review_aggregate_source_scope_check CHECK ((source_scope = ANY (ARRAY['external'::text, 'first_party'::text, 'combined'::text]))),
    CONSTRAINT review_aggregate_status_check CHECK ((status = ANY (ARRAY['building'::text, 'ready'::text, 'stale'::text, 'revoked'::text])))
);


--
-- Name: review_aggregate_member; Type: TABLE; Schema: evidence; Owner: -
--

CREATE TABLE evidence.review_aggregate_member (
    aggregate_id uuid NOT NULL,
    summary_id uuid NOT NULL,
    disposition text NOT NULL,
    weight numeric(8,4) DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT review_aggregate_member_disposition_check CHECK ((disposition = ANY (ARRAY['retained'::text, 'excluded'::text]))),
    CONSTRAINT review_aggregate_member_weight_check CHECK ((weight > (0)::numeric))
);


--
-- Name: review_subject; Type: TABLE; Schema: evidence; Owner: -
--

CREATE TABLE evidence.review_subject (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    product_id uuid,
    variant_id uuid,
    offer_id uuid,
    build_version_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT review_subject_check CHECK ((num_nonnulls(product_id, variant_id, offer_id, build_version_id) = 1))
);


--
-- Name: review_summary; Type: TABLE; Schema: evidence; Owner: -
--

CREATE TABLE evidence.review_summary (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    subject_id uuid NOT NULL,
    source_id uuid NOT NULL,
    origin text NOT NULL,
    external_review_key text,
    original_url text,
    review_revision_id uuid,
    summary text NOT NULL,
    normalized_rating numeric(3,2),
    collected_at timestamp with time zone NOT NULL,
    processing_version text NOT NULL,
    cleaning_status text NOT NULL,
    exclusion_reason text,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    author_ref text,
    review_posted_at timestamp with time zone,
    CONSTRAINT review_summary_check CHECK ((((origin = 'external'::text) AND (external_review_key IS NOT NULL) AND (original_url IS NOT NULL) AND (review_revision_id IS NULL)) OR ((origin = 'first_party'::text) AND (review_revision_id IS NOT NULL) AND (external_review_key IS NULL)))),
    CONSTRAINT review_summary_cleaning_status_check CHECK ((cleaning_status = ANY (ARRAY['retained'::text, 'excluded'::text, 'pending'::text]))),
    CONSTRAINT review_summary_normalized_rating_check CHECK (((normalized_rating IS NULL) OR ((normalized_rating >= (0)::numeric) AND (normalized_rating <= (5)::numeric)))),
    CONSTRAINT review_summary_origin_check CHECK ((origin = ANY (ARRAY['external'::text, 'first_party'::text]))),
    CONSTRAINT review_summary_status_check CHECK ((status = ANY (ARRAY['active'::text, 'superseded'::text, 'revoked'::text])))
);


--
-- Name: COLUMN review_summary.author_ref; Type: COMMENT; Schema: evidence; Owner: -
--

COMMENT ON COLUMN evidence.review_summary.author_ref IS '외부 작성자 식별자의 소스별 솔트 해시. 관계·행동 축(공유 리뷰어·신규성·간격)용. 원식별자는 저장하지 않는다.';


--
-- Name: COLUMN review_summary.review_posted_at; Type: COMMENT; Schema: evidence; Owner: -
--

COMMENT ON COLUMN evidence.review_summary.review_posted_at IS '리뷰가 원 소스에 게시된 시각(UTC). collected_at(우리 수집 시각)과 다르다. 7일 몰림·간격 계산용.';


--
-- Name: source; Type: TABLE; Schema: evidence; Owner: -
--

CREATE TABLE evidence.source (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    source_type text NOT NULL,
    base_url text,
    rating_scale jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT source_source_type_check CHECK ((source_type = ANY (ARRAY['manufacturer'::text, 'public_registry'::text, 'merchant'::text, 'external_review'::text, 'first_party'::text, 'derived'::text])))
);


--
-- Name: app_user; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.app_user (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email_normalized text NOT NULL,
    auth_subject text NOT NULL,
    display_name text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    password_hash text,
    password_updated_at timestamp with time zone,
    failed_login_count integer DEFAULT 0 NOT NULL,
    locked_until timestamp with time zone,
    last_login_at timestamp with time zone,
    terms_version text,
    terms_agreed_at timestamp with time zone,
    privacy_agreed_at timestamp with time zone,
    marketing_agreed_at timestamp with time zone,
    deleted_at timestamp with time zone,
    email_verified_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ui_settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    notification_settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT app_user_deleted_at_check CHECK (((status = 'deleted'::text) = (deleted_at IS NOT NULL))),
    CONSTRAINT app_user_failed_login_count_check CHECK ((failed_login_count >= 0)),
    CONSTRAINT app_user_password_time_check CHECK (((password_hash IS NULL) OR (password_updated_at IS NOT NULL))),
    CONSTRAINT app_user_status_check CHECK ((status = ANY (ARRAY['active'::text, 'suspended'::text, 'deleted'::text]))),
    CONSTRAINT app_user_terms_pair_check CHECK (((terms_version IS NULL) = (terms_agreed_at IS NULL)))
);


--
-- Name: conversation; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.conversation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    guest_session_hash text,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT conversation_check CHECK (((user_id IS NOT NULL) OR (guest_session_hash IS NOT NULL)))
);


--
-- Name: message; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.message (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    client_message_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT message_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text])))
);


--
-- Name: price_watch; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.price_watch (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id uuid NOT NULL,
    purchase_line_id uuid,
    target_amount numeric(18,2) NOT NULL,
    currency character(3) DEFAULT 'KRW'::bpchar NOT NULL,
    pricing_policy jsonb NOT NULL,
    state text DEFAULT 'active'::text NOT NULL,
    ends_at timestamp with time zone NOT NULL,
    last_condition_state text DEFAULT 'unknown'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT price_watch_last_condition_state_check CHECK ((last_condition_state = ANY (ARRAY['unknown'::text, 'above'::text, 'reached'::text]))),
    CONSTRAINT price_watch_state_check CHECK ((state = ANY (ARRAY['active'::text, 'paused'::text, 'expired'::text]))),
    CONSTRAINT price_watch_target_amount_check CHECK ((target_amount >= (0)::numeric))
);


--
-- Name: plan; Type: TABLE; Schema: planning; Owner: -
--

CREATE TABLE planning.plan (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid NOT NULL,
    owner_user_id uuid,
    name text NOT NULL,
    current_revision_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT plan_deleted_at_check CHECK (((status = 'deleted'::text) = (deleted_at IS NOT NULL))),
    CONSTRAINT plan_status_check CHECK ((status = ANY (ARRAY['active'::text, 'deleted'::text])))
);


--
-- Name: plan_condition; Type: TABLE; Schema: planning; Owner: -
--

CREATE TABLE planning.plan_condition (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id uuid NOT NULL,
    condition_key text NOT NULL,
    value jsonb NOT NULL,
    origin text NOT NULL,
    source_message_id uuid,
    supersedes_id uuid,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT plan_condition_origin_check CHECK ((origin = ANY (ARRAY['explicit'::text, 'extracted'::text, 'inferred'::text]))),
    CONSTRAINT plan_condition_status_check CHECK ((status = ANY (ARRAY['active'::text, 'superseded'::text, 'deleted'::text])))
);


--
-- Name: plan_node; Type: TABLE; Schema: planning; Owner: -
--

CREATE TABLE planning.plan_node (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id uuid NOT NULL,
    parent_id uuid,
    node_type text NOT NULL,
    template_key text NOT NULL,
    name text NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    context jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT plan_node_node_type_check CHECK ((node_type = ANY (ARRAY['group'::text, 'slot'::text])))
);


--
-- Name: plan_revision; Type: TABLE; Schema: planning; Owner: -
--

CREATE TABLE planning.plan_revision (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    plan_id uuid NOT NULL,
    revision_no integer NOT NULL,
    domain_version_id uuid NOT NULL,
    state text DEFAULT 'draft'::text NOT NULL,
    lock_version integer DEFAULT 0 NOT NULL,
    name_snapshot text NOT NULL,
    confirmed_at timestamp with time zone,
    planned_purchase_at timestamp with time zone,
    confirmed_total numeric(18,2),
    currency character(3) DEFAULT 'KRW'::bpchar NOT NULL,
    pricing_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    target_amount numeric(18,2),
    memo text DEFAULT ''::text NOT NULL,
    CONSTRAINT plan_revision_check CHECK (((revision_no > 0) AND (lock_version >= 0))),
    CONSTRAINT plan_revision_check1 CHECK (((state <> 'confirmed'::text) OR ((confirmed_at IS NOT NULL) AND (confirmed_total IS NOT NULL)))),
    CONSTRAINT plan_revision_confirmed_total_check CHECK (((confirmed_total IS NULL) OR (confirmed_total >= (0)::numeric))),
    CONSTRAINT plan_revision_memo_length_check CHECK ((char_length(memo) <= 1000)),
    CONSTRAINT plan_revision_state_check CHECK ((state = ANY (ARRAY['draft'::text, 'confirmed'::text]))),
    CONSTRAINT plan_revision_target_amount_check CHECK (((target_amount IS NULL) OR (target_amount >= (0)::numeric)))
);


--
-- Name: purchase_line; Type: TABLE; Schema: planning; Owner: -
--

CREATE TABLE planning.purchase_line (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id uuid NOT NULL,
    offer_id uuid NOT NULL,
    selected_observation_id uuid NOT NULL,
    pack_count integer DEFAULT 1 NOT NULL,
    line_amount numeric(18,2) NOT NULL,
    currency character(3) DEFAULT 'KRW'::bpchar NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT purchase_line_check CHECK (((pack_count > 0) AND (line_amount >= (0)::numeric)))
);


--
-- Name: requirement; Type: TABLE; Schema: planning; Owner: -
--

CREATE TABLE planning.requirement (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision_id uuid NOT NULL,
    node_id uuid NOT NULL,
    quantity numeric(18,4) DEFAULT 1 NOT NULL,
    unit_code text DEFAULT 'each'::text NOT NULL,
    required boolean DEFAULT true NOT NULL,
    needed_at timestamp with time zone,
    timing_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    match_spec jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT requirement_quantity_check CHECK ((quantity > (0)::numeric)),
    CONSTRAINT requirement_status_check CHECK ((status = ANY (ARRAY['active'::text, 'excluded'::text])))
);


--
-- PostgreSQL database dump complete
--
